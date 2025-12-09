import json
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Provide a lightweight cv2 stub so tests can run without system OpenCV libraries.


class _DummyCap:
    def __init__(self, *_args, **_kwargs):
        self._opened = False

    def isOpened(self):
        return self._opened

    def release(self):  # noqa: D401 - stub
        self._opened = False

    def read(self):
        return False, None

    def set(self, *_args):
        return True

    def get(self, *_args):
        return 0


cv2_stub = types.SimpleNamespace(
    VideoCapture=lambda *_args, **_kwargs: _DummyCap(),
    CAP_PROP_FRAME_WIDTH=3,
    CAP_PROP_FRAME_HEIGHT=4,
    CAP_PROP_FPS=5,
    IMWRITE_JPEG_QUALITY=1,
    imencode=lambda *_args, **_kwargs: (False, None),
)

sys.modules.setdefault("cv2", cv2_stub)

import app  # noqa: E402  # needs stubbed cv2 before importing


@pytest.fixture(autouse=True)
def isolate_app(monkeypatch, tmp_path):
    """Isolate global state and side effects for each test run."""

    tmp_config = tmp_path / "cameras.json"
    tmp_nginx = tmp_path / "nginx.conf"

    monkeypatch.setattr(app, "CONFIG_PATH", tmp_config)
    monkeypatch.setattr(app, "NGINX_CONFIG_PATH", tmp_nginx)
    monkeypatch.setattr(app, "init_cameras", lambda: None)
    monkeypatch.setattr(app, "generate_nginx_config", lambda config, output_path=tmp_nginx: None)

    original_startup = list(app.app.router.on_startup)
    original_shutdown = list(app.app.router.on_shutdown)
    app.app.router.on_startup.clear()
    app.app.router.on_shutdown.clear()

    app.CAMERA_CONFIG = app.default_config()
    app.CAMERAS = {}

    yield tmp_config

    app.app.router.on_startup.extend(original_startup)
    app.app.router.on_shutdown.extend(original_shutdown)


def test_assign_ports_handles_duplicates_and_missing():
    cameras = [
        {"id": "cam1", "name": "One", "device": 0, "port": 8082},
        {"id": "cam2", "name": "Two", "device": 1},
        {"id": "cam3", "name": "Three", "device": 2, "port": 8082},
    ]

    assigned = app.assign_ports(cameras)
    ports = [cam["port"] for cam in assigned]

    assert ports[0] == 8082
    assert len(set(ports)) == len(ports)
    assert ports[1] == 8083
    assert ports[2] == 8084


def test_validate_camera_entries_detects_conflicts():
    valid = [{"id": "cam1", "name": "One", "device": 0, "port": 8081}]
    app.validate_camera_entries(valid)

    with pytest.raises(ValueError):
        app.validate_camera_entries(
            [
                {"id": "cam1", "name": "Dup", "device": 1, "port": 8081},
                {"id": "cam1", "name": "Dup2", "device": 2, "port": 8082},
            ]
        )

    with pytest.raises(ValueError):
        app.validate_camera_entries(
            [
                {"id": "camA", "name": "One", "device": 0, "port": 8081},
                {"id": "camB", "name": "Two", "device": 1, "port": 8081},
            ]
        )


def test_camera_api_round_trip(isolate_app, tmp_path):
    payload = {
        "host": "0.0.0.0",
        "cameras": [
            {"id": "cam1", "name": "One", "device": 0, "port": 8081},
            {"id": "cam2", "name": "Two", "device": 1},
        ],
    }

    response = app.set_cameras(app.CamerasUpdate(**payload))
    data = response["cameras"]
    assert data["host"] == "0.0.0.0"
    ports = [cam["port"] for cam in data["cameras"]]
    assert ports[0] == 8081
    assert ports[1] == 8082

    saved = json.loads(Path(isolate_app).read_text())
    assert saved["cameras"][0]["id"] == "cam1"

    fetched = app.get_cameras()
    assert fetched["cameras"][0]["id"] == "cam1"


def test_invalid_camera_post_returns_error():
    payload = {
        "host": "0.0.0.0",
        "cameras": [
            {"id": "cam1", "name": "One", "device": 0},
            {"id": "cam1", "name": "Du", "device": 1},
        ],
    }
    with pytest.raises(HTTPException) as exc:
        app.set_cameras(app.CamerasUpdate(**payload))

    assert exc.value.status_code == 400
    assert "Duplicate camera id" in exc.value.detail
