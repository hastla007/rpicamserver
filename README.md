# Raspberry Pi Camera Server

FastAPI-based camera server that exposes both MJPEG video feeds and JPEG snapshot
endpoints for multiple USB or Raspberry Pi cameras. Each camera can be assigned
a dedicated port while a central API handles configuration and a simple
front-end viewer.

## Features
- Background frame grabber per camera using OpenCV
- MJPEG video and snapshot endpoints per camera: `http://<host>:<port>/video` and `/snapshot`
- Central FastAPI app with configuration APIs and built-in viewer
- JSON-based configuration persisted to `cameras.json`
- Hot reload of camera processes when configuration is updated via the API

## Getting started

### Install dependencies
Install system prerequisites for OpenCV (varies by distro) and the Python
packages:

```bash
sudo apt update
sudo apt install python3-opencv python3-pip
pip3 install -r requirements.txt
```

### Configure cameras
Create a `cameras.json` file describing your devices. You can start from the
included example:

```bash
cp cameras.example.json cameras.json
```

Update each camera entry to point to the correct device index and choose a port
for the per-camera HTTP server. Device indices map to `/dev/video*` devices on
most Linux systems.

### Run the server
Start the main FastAPI control plane (defaults to port 8000):

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

On startup the app loads `cameras.json`, spins up background frame grabbers, and
launches lightweight FastAPI instances on the configured camera ports. Visit
`http://<host>:8000/` for the built-in viewer.

### Configure via API
You can update cameras at runtime with a POST to `/api/cameras`:

```bash
curl -X POST http://<host>:8000/api/cameras \
  -H "Content-Type: application/json" \
  -d '{
    "host": "0.0.0.0",
    "cameras": [
      {"id": "cam1", "name": "USB Cam 1", "device": 0, "port": 8081},
      {"id": "cam2", "name": "USB Cam 2", "device": 1, "port": 8082}
    ]
  }'
```

The server saves the configuration, restarts background capture threads, and
relaunches the per-camera HTTP servers.

## Notes
- OpenCV requires access to camera devices; ensure the user running the server
  has permissions for `/dev/video*`.
- If a camera fails to start, the server logs the error and continues with the
  remaining devices.
- You can also run `python app.py` to start uvicorn with default settings.
