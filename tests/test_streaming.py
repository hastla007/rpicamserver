import pytest

import app


pytestmark = pytest.mark.anyio


async def _collect_frames(gen, count=2):
    frames = []
    async for chunk in gen:
        frames.append(chunk)
        if len(frames) >= count:
            break
    return frames


def test_discover_respects_probe_limits(monkeypatch, device_registry):
    # No /dev/video* nodes and probing disabled -> no discovery
    monkeypatch.setattr(app, "MAX_DEVICE_PROBE", 2)
    monkeypatch.setattr(app, "PROBE_WHEN_NO_DEVICES", False)
    monkeypatch.setattr(app.glob, "glob", lambda *_args: [])

    assert app.discover_cameras() == []

    # Enable probing and ensure it honors the limit
    monkeypatch.setattr(app, "PROBE_WHEN_NO_DEVICES", True)
    device_registry[0] = {"frames": [b"frame"]}
    devices = app.discover_cameras(max_devices=1)
    assert len(devices) == 1
    assert devices[0]["index"] == 0


def test_snapshot_placeholder_when_no_frame(device_registry):
    device_registry[0] = {"frames": []}
    cam = app.Camera(0)
    app.CAMERAS = {"cam0": cam}

    try:
        data = app.get_snapshot_bytes("cam0")
    finally:
        cam.stop()

    assert isinstance(data, (bytes, bytearray))
    assert data


async def test_mjpeg_generator_tracks_subscribers(device_registry, sample_frame):
    device_registry[0] = {"frames": [sample_frame for _ in range(5)]}
    cam = app.Camera(0)
    app.CAMERAS = {"cam0": cam}

    try:
        gen = app.mjpeg_generator("cam0")
        frames = await _collect_frames(gen, 2)
        assert len(frames) == 2
        assert cam._subscriber_count() == 1
    finally:
        await gen.aclose()
        cam.stop()
    assert cam._subscriber_count() == 0


def test_ui_routes_render(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Pi Camera Server" in res.text

    res = client.get("/api-docs")
    assert res.status_code == 200
    assert "HTTP endpoints" in res.text
