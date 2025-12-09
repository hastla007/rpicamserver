"""
Raspberry Pi camera server exposing MJPEG video and snapshot endpoints per camera.

Run with uvicorn:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000

The main FastAPI app provides configuration APIs and a basic viewer. Individual
camera streams are also exposed on dedicated ports defined in the camera
configuration.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

CONFIG_PATH = Path("cameras.json")
DEFAULT_CAMERA_HOST = "0.0.0.0"
DEFAULT_START_PORT = 8081

app = FastAPI(title="Raspberry Pi Camera Server")


###############################################################################
# Camera capture
###############################################################################


class Camera:
    """Background frame grabber for a single video device."""

    def __init__(self, device_index: int):
        self.device_index = device_index
        self.cap = cv2.VideoCapture(device_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera device {device_index}")

        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.running = True

        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def _update_loop(self) -> None:
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            with self.frame_lock:
                self.latest_frame = frame
            time.sleep(1 / 30.0)

    def get_frame(self):
        with self.frame_lock:
            if self.latest_frame is None:
                return None
            return self.latest_frame.copy()

    def stop(self) -> None:
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()


###############################################################################
# Camera HTTP servers
###############################################################################


def _encode_frame(frame, quality: int = 80) -> Optional[bytes]:
    ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ret:
        return None
    return jpeg.tobytes()


class CameraHTTPServer(threading.Thread):
    """Dedicated FastAPI + uvicorn server exposing one camera."""

    def __init__(self, cam_id: str, camera: Camera, host: str, port: int):
        super().__init__(daemon=True)
        self.cam_id = cam_id
        self.camera = camera
        self.host = host
        self.port = port
        self.server: Optional[uvicorn.Server] = None
        self.started = threading.Event()

    def _create_app(self) -> FastAPI:
        boundary = "frame"
        cam = self.camera

        server_app = FastAPI(title=f"Camera {self.cam_id}")

        def mjpeg_generator():
            while True:
                frame = cam.get_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue

                jpg_bytes = _encode_frame(frame, quality=80)
                if jpg_bytes is None:
                    continue

                yield (
                    b"--" + boundary.encode() + b"\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
                )

        @server_app.get("/video")
        def video_stream():
            return StreamingResponse(
                mjpeg_generator(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

        @server_app.get("/snapshot")
        def snapshot():
            frame = cam.get_frame()
            if frame is None:
                raise HTTPException(status_code=503, detail="No frame available yet")

            jpg_bytes = _encode_frame(frame, quality=90)
            if jpg_bytes is None:
                raise HTTPException(status_code=500, detail="Failed to encode frame")

            return Response(content=jpg_bytes, media_type="image/jpeg")

        @server_app.get("/")
        def index():
            return HTMLResponse(
                f"""
                <html>
                <head><title>Camera {self.cam_id}</title></head>
                <body>
                    <h2>Camera {self.cam_id}</h2>
                    <p>Video stream: <a href='/video'>/video</a></p>
                    <img src='/video' style='max-width: 640px; border: 1px solid #ccc;'/>
                    <p>Snapshot: <a href='/snapshot'>/snapshot</a></p>
                    <img src='/snapshot' style='max-width: 320px; border: 1px solid #ccc;'/>
                </body>
                </html>
                """
            )

        return server_app

    def run(self) -> None:
        config = uvicorn.Config(
            app=self._create_app(), host=self.host, port=self.port, log_level="info"
        )
        self.server = uvicorn.Server(config)
        self.started.set()
        self.server.run()

    def stop(self) -> None:
        self.started.wait(timeout=1)
        if self.server is not None:
            self.server.should_exit = True
            self.server.force_exit = True


###############################################################################
# Configuration
###############################################################################


def default_config() -> Dict[str, Any]:
    return {"host": DEFAULT_CAMERA_HOST, "cameras": []}


def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return default_config()


def save_config(config: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


###############################################################################
# Models
###############################################################################


class CameraConfig(BaseModel):
    id: str = Field(description="Unique camera identifier")
    name: str
    device: int = Field(description="cv2.VideoCapture device index")
    port: int = Field(description="Port for the per-camera HTTP server")


class CamerasUpdate(BaseModel):
    host: str = Field(default=DEFAULT_CAMERA_HOST, description="Binding host")
    cameras: List[CameraConfig]


###############################################################################
# App state helpers
###############################################################################


CAMERAS: Dict[str, Camera] = {}
CAMERA_SERVERS: Dict[str, CameraHTTPServer] = {}
CAMERA_CONFIG: Dict[str, Any] = default_config()


def stop_cameras() -> None:
    for server in CAMERA_SERVERS.values():
        server.stop()
    for server in CAMERA_SERVERS.values():
        server.join(timeout=2)
    CAMERA_SERVERS.clear()

    for camera in CAMERAS.values():
        camera.stop()
    CAMERAS.clear()


def init_cameras() -> None:
    stop_cameras()

    host = CAMERA_CONFIG.get("host", DEFAULT_CAMERA_HOST)
    for cam_cfg in CAMERA_CONFIG.get("cameras", []):
        cam_id = cam_cfg["id"]
        device_index = cam_cfg["device"]
        port = cam_cfg.get("port") or DEFAULT_START_PORT

        try:
            camera = Camera(device_index)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to start camera {cam_id}: {exc}")
            continue

        CAMERAS[cam_id] = camera
        server = CameraHTTPServer(cam_id=cam_id, camera=camera, host=host, port=port)
        server.start()
        CAMERA_SERVERS[cam_id] = server
        print(f"Started camera {cam_id} on device {device_index} (port {port})")


###############################################################################
# Shared streaming helpers for the main API
###############################################################################


def mjpeg_generator(cam_id: str):
    if cam_id not in CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")

    camera = CAMERAS[cam_id]
    boundary = "frame"
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.1)
            continue

        jpg_bytes = _encode_frame(frame, quality=80)
        if jpg_bytes is None:
            continue

        yield (
            b"--" + boundary.encode() + b"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
        )


def get_snapshot_bytes(cam_id: str) -> bytes:
    if cam_id not in CAMERAS:
        raise HTTPException(status_code=404, detail="Camera not found")
    frame = CAMERAS[cam_id].get_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet")

    jpg_bytes = _encode_frame(frame, quality=90)
    if jpg_bytes is None:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return jpg_bytes


###############################################################################
# API endpoints
###############################################################################


@app.on_event("startup")
def startup_event() -> None:
    global CAMERA_CONFIG
    CAMERA_CONFIG = load_config()
    init_cameras()


@app.on_event("shutdown")
def shutdown_event() -> None:
    stop_cameras()


@app.get("/", response_class=HTMLResponse)
def index_page():
    cam_list_html = ""
    host = CAMERA_CONFIG.get("host", DEFAULT_CAMERA_HOST)
    for cam in CAMERA_CONFIG.get("cameras", []):
        cam_id = cam["id"]
        port = cam.get("port", "")
        cam_list_html += f"""
        <div style='margin-bottom: 20px;'>
            <h3>{cam_id} - {cam['name']}</h3>
            <div>
                Dedicated endpoints on port {port}:<br>
                <code>http://{host}:{port}/video</code><br>
                <code>http://{host}:{port}/snapshot</code>
            </div>
            <div style='margin-top: 10px;'>
                Video (main API):<br>
                <img src='/cam/{cam_id}/video' style='max-width: 480px; border: 1px solid #ccc;'>
            </div>
            <div style='margin-top: 10px;'>
                Snapshot (main API):<br>
                <img id='snap-{cam_id}' src='/cam/{cam_id}/snapshot' style='max-width: 320px; border: 1px solid #ccc;'>
            </div>
        </div>
        """

    return f"""
    <html>
    <head>
        <title>Pi Camera Server</title>
        <meta charset="utf-8" />
    </head>
    <body>
        <h1>Pi Camera Server</h1>
        <p>Streams are available both from this API and on per-camera ports.</p>
        {cam_list_html or '<p>No cameras configured. POST to /api/cameras to add one.</p>'}
        <script>
        setInterval(() => {{
            const imgs = document.querySelectorAll("img[id^='snap-']");
            imgs.forEach(img => {{
                const base = img.src.split('?')[0];
                img.src = base + "?t=" + Date.now();
            }});
        }}, 2000);
        </script>
    </body>
    </html>
    """


@app.get("/api/cameras")
def get_cameras():
    return CAMERA_CONFIG


@app.post("/api/cameras")
def set_cameras(data: CamerasUpdate):
    global CAMERA_CONFIG
    CAMERA_CONFIG = {"host": data.host, "cameras": [cam.dict() for cam in data.cameras]}
    save_config(CAMERA_CONFIG)
    init_cameras()
    return {"status": "ok", "cameras": CAMERA_CONFIG}


@app.get("/cam/{cam_id}/video")
def video_stream(cam_id: str):
    return StreamingResponse(
        mjpeg_generator(cam_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/cam/{cam_id}/snapshot")
def snapshot(cam_id: str):
    img_bytes = get_snapshot_bytes(cam_id)
    return Response(content=img_bytes, media_type="image/jpeg")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
