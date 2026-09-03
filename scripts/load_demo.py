"""Create a room and submit demo_data.json to a running API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]


def browser():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def post_json(opener, url: str, payload: dict) -> dict:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"POST {url} failed ({exc.code}): {detail}") from exc


def get_json(opener, url: str) -> dict:
    try:
        with opener.open(url, timeout=15) as response:
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
    creator = browser()
    room = post_json(creator, f"{base_url}/api/rooms", data["room"])
    code = room["code"]

    for submission in data["submissions"]:
        participant = browser()
        get_json(participant, f"{base_url}/api/rooms/{code}")
        post_json(participant, f"{base_url}/api/rooms/{code}/submit", submission)

    result = get_json(creator, f"{base_url}/api/rooms/{code}/analysis")
    print(json.dumps({"room_code": code, "analysis": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
