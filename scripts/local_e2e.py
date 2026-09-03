"""Exercise the built SPA and API in-process when Docker is unavailable."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.main import app, room_analysis_locks, rooms  # noqa: E402
from check_demo_result import validate_demo_result  # noqa: E402


def main() -> None:
    rooms.clear()
    room_analysis_locks.clear()
    data = json.loads((ROOT / "demo_data.json").read_text(encoding="utf-8"))

    with TestClient(app) as client:
        health = client.get("/api/health")
        health.raise_for_status()

        index = client.get("/")
        index.raise_for_status()
        asset_match = re.search(r'src="([^"]+\.js)"', index.text)
        if asset_match is None:
            raise SystemExit("local E2E failed: frontend JavaScript asset not found")
        bundle = client.get(asset_match.group(1))
        bundle.raise_for_status()
        if "LIVE API" not in bundle.text or "MOCK MODE" in bundle.text:
            raise SystemExit("local E2E failed: frontend bundle is not in LIVE API mode")

        room = client.post("/api/rooms", json=data["room"])
        room.raise_for_status()
        code = room.json()["code"]
        for submission in data["submissions"]:
            with TestClient(app) as participant:
                participant.get(f"/api/rooms/{code}").raise_for_status()
                response = participant.post(f"/api/rooms/{code}/submit", json=submission)
                response.raise_for_status()
        analysis = client.get(f"/api/rooms/{code}/analysis")
        analysis.raise_for_status()
        decision = client.post(
            f"/api/rooms/{code}/decision-record",
            json={
                "final_choice": analysis.json()["robust_choice"],
                "final_reason": "분석 결과와 대응 가능한 위험을 검토했습니다.",
            },
        )
        decision.raise_for_status()
        stored_decision = client.get(f"/api/rooms/{code}/decision-record")
        stored_decision.raise_for_status()
        if stored_decision.json() != decision.json():
            raise SystemExit("local E2E failed: decision record did not round trip")

    print(validate_demo_result({"room_code": code, "analysis": analysis.json()}))
    print("local in-process E2E passed")


if __name__ == "__main__":
    main()
