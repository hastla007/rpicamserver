"""Command-line helper for managing rpicamserver in headless environments."""

import argparse
import base64
import json
import os
import sys
from typing import Any, Dict

import httpx

DEFAULT_BASE = os.getenv("RPICAM_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_AUTH = os.getenv("RPICAM_AUTH", "")


def _build_headers() -> Dict[str, str]:
    if not DEFAULT_AUTH:
        return {}
    if ":" not in DEFAULT_AUTH:
        return {}
    user, pwd = DEFAULT_AUTH.split(":", 1)
    token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url.rstrip("/"), headers=_build_headers(), timeout=10)


def cmd_devices(args: argparse.Namespace) -> int:
    params = {}
    if args.max is not None:
        params["max"] = args.max
    if args.probe_missing is not None:
        params["probe_missing"] = str(args.probe_missing).lower()
    with _client(args.base_url) as client:
        res = client.get("/api/devices", params=params)
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    with _client(args.base_url) as client:
        res = client.get("/health")
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    with _client(args.base_url) as client:
        res = client.get("/api/cameras")
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    payload: Dict[str, Any]
    if args.file == "-":
        payload = json.load(sys.stdin)
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            payload = json.load(f)

    with _client(args.base_url) as client:
        res = client.post("/api/cameras", json=payload)
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    with _client(args.base_url) as client:
        res = client.get(f"/cam/{args.camera}/snapshot")
        res.raise_for_status()
        data = res.content
    if args.output == "-":
        sys.stdout.buffer.write(data)
    else:
        with open(args.output, "wb") as f:
            f.write(data)
        print(f"Saved snapshot to {args.output}")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    with _client(args.base_url) as client:
        res = client.post(f"/api/cameras/{args.camera}/restart")
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    with _client(args.base_url) as client:
        res = client.delete(f"/api/cameras/{args.camera}")
        res.raise_for_status()
        json.dump(res.json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=f"Server base URL (default: {DEFAULT_BASE})")
    sub = parser.add_subparsers(dest="command", required=True)

    dev = sub.add_parser("devices", help="List detected cameras")
    dev.add_argument("--max", type=int, help="Max device indices to probe")
    dev.add_argument("--probe-missing", dest="probe_missing", action="store_true", help="Probe when no /dev/video* nodes")
    dev.add_argument("--no-probe-missing", dest="probe_missing", action="store_false", help="Skip probing when missing")
    dev.set_defaults(func=cmd_devices)

    health = sub.add_parser("health", help="Show camera health summary")
    health.set_defaults(func=cmd_health)

    cfg = sub.add_parser("config", help="Fetch current configuration")
    cfg.set_defaults(func=cmd_config)

    set_cfg = sub.add_parser("set", help="Apply configuration JSON")
    set_cfg.add_argument("file", help="Path to JSON payload or - for stdin")
    set_cfg.set_defaults(func=cmd_set)

    snap = sub.add_parser("snapshot", help="Download a snapshot for a camera")
    snap.add_argument("camera", help="Camera id")
    snap.add_argument("--output", default="-", help="Output path or - for stdout")
    snap.set_defaults(func=cmd_snapshot)

    restart = sub.add_parser("restart", help="Request a manual camera restart")
    restart.add_argument("camera", help="Camera id")
    restart.set_defaults(func=cmd_restart)

    delete = sub.add_parser("delete", help="Remove a camera from the configuration")
    delete.add_argument("camera", help="Camera id")
    delete.set_defaults(func=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except httpx.HTTPStatusError as exc:  # noqa: BLE001
        sys.stderr.write(f"Request failed: {exc.response.text}\n")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Error: {exc}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
