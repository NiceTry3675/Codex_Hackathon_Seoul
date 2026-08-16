"""Create a room and submit demo_data.json to a running API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def post_json(url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"POST {url} failed ({exc.code}): {detail}") from exc


def get_json(url: str) -> dict:
    try:
        with urlopen(url, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GET {url} failed ({exc.code}): {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    data = json.loads((ROOT / "demo_data.json").read_text(encoding="utf-8"))
    room = post_json(f"{base_url}/api/rooms", data["room"])
    code = room["code"]

    for submission in data["submissions"]:
        post_json(f"{base_url}/api/rooms/{code}/submit", submission)

    result = get_json(f"{base_url}/api/rooms/{code}/analysis")
    print(json.dumps({"room_code": code, "analysis": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
