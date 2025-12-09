import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials
import pytest

import app


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

    # Zero-valued controls should be accepted
    app.validate_camera_entries(
        [
            {
                "id": "camZero",
                "name": "Zero",
                "device": 0,
                "brightness": 0,
                "exposure": 0,
                "white_balance": 0,
            }
        ]
    )

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

    with pytest.raises(ValueError):
        app.validate_camera_entries(
            [{"id": "camC", "name": "Ctrl", "device": 0, "brightness": "abc"}]
        )

    with pytest.raises(ValueError):
        app.validate_camera_entries(
            [
                {
                    "id": "camBad",
                    "name": "Ctrl",
                    "device": 0,
                    "brightness": 5,
                    "exposure": -1,
                    "white_balance": 20000,
                }
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


def test_invalid_auth_is_reported(tmp_path, monkeypatch):
    config_path = tmp_path / "cameras.json"
    monkeypatch.setattr(app, "CONFIG_PATH", config_path)
    config_path.write_text(
        json.dumps(
            {
                "host": "0.0.0.0",
                "auth": {"enabled": True, "username": "", "password": ""},
                "cameras": [],
            }
        )
    )

    cfg = app.load_config()
    assert cfg.get("auth_error")
    assert cfg["auth"].get("enabled") is False


def test_require_auth_guard(monkeypatch):
    app.CAMERA_CONFIG = {
        "host": "0.0.0.0",
        "auth": {"enabled": True, "username": "user", "password": "pass"},
        "cameras": [],
    }

    ok = HTTPBasicCredentials(username="user", password="pass")
    assert app.require_auth(ok) is None

    bad = HTTPBasicCredentials(username="user", password="nope")
    with pytest.raises(HTTPException):
        app.require_auth(bad)
