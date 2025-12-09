import sys
import types
from pathlib import Path

import numpy as np
import pytest

# Registry-driven cv2 stub so tests run without actual camera devices.
DEVICE_REGISTRY: dict[int, dict] = {}


class _DummyCap:
    def __init__(self, index=0):
        cfg = DEVICE_REGISTRY.get(index, {})
        self.index = index
        self._opened = cfg.get("opened", True)
        self.frames = list(cfg.get("frames", []))
        self.properties = cfg.get("properties", {})

    def isOpened(self):
        return self._opened

    def release(self):  # noqa: D401 - stub
        self._opened = False

    def read(self):
        if not self._opened:
            return False, None
        if not self.frames:
            return False, None
        frame = self.frames[0]
        if len(self.frames) > 1:
            self.frames.pop(0)
        return True, frame

    def set(self, prop_id, value):
        self.properties[prop_id] = value
        return True

    def get(self, prop_id):
        return self.properties.get(prop_id, 0)


cv2_stub = types.SimpleNamespace(
    VideoCapture=lambda index: _DummyCap(index),
    CAP_PROP_FRAME_WIDTH=3,
    CAP_PROP_FRAME_HEIGHT=4,
    CAP_PROP_FPS=5,
    CAP_PROP_BRIGHTNESS=10,
    CAP_PROP_EXPOSURE=15,
    CAP_PROP_WB_TEMPERATURE=20,
    IMWRITE_JPEG_QUALITY=1,
    FONT_HERSHEY_SIMPLEX=0,
    LINE_AA=16,
    imencode=lambda *_args, **_kwargs: (True, types.SimpleNamespace(tobytes=lambda: b"jpeg-bytes")),
    putText=lambda img, *args, **kwargs: img,
)

sys.modules.setdefault("cv2", cv2_stub)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402  # ensure stubbed cv2 is used


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
    DEVICE_REGISTRY.clear()


@pytest.fixture
def device_registry():
    DEVICE_REGISTRY.clear()
    yield DEVICE_REGISTRY
    DEVICE_REGISTRY.clear()


@pytest.fixture
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(app.app)


@pytest.fixture
def sample_frame():
    return np.zeros((8, 8, 3), dtype=np.uint8)
