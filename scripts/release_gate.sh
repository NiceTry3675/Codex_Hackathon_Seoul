#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
IMAGE_TAG="consensus:release-gate"
CONTAINER_NAME="consensus-release-gate-$$"
DEMO_RESULT="$(mktemp -t consensus-demo-result.XXXXXX.json)"
SKIP_DOCKER=false

if [[ "${1:-}" == "--skip-docker" ]]; then
  SKIP_DOCKER=true
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--skip-docker]" >&2
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

cleanup() {
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -f "$DEMO_RESULT"
}
trap cleanup EXIT

cd "$PROJECT_ROOT"

echo "[1/8] Backend tests"
"$PYTHON_BIN" -m pytest -q

echo "[2/8] Frontend calculation tests"
(cd frontend && npm test)

echo "[3/8] Frontend production build"
(cd frontend && VITE_USE_MOCK_API=false VITE_API_BASE_URL= npm run build)

echo "[4/8] Optional live OpenAI smoke"
OPENAI_SMOKE_CONFIGURED=false
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  OPENAI_SMOKE_CONFIGURED=true
elif [[ -f "$PROJECT_ROOT/.env" ]] && awk -F= '
  /^OPENAI_API_KEY=/ {
    value=$0
    sub(/^[^=]*=/, "", value)
    if (length(value) > 0) found=1
  }
  END { exit found ? 0 : 1 }
' "$PROJECT_ROOT/.env"; then
  OPENAI_SMOKE_CONFIGURED=true
fi
if [[ "$OPENAI_SMOKE_CONFIGURED" == true ]]; then
  "$PYTHON_BIN" scripts/smoke_openai.py
else
  echo "skip: OPENAI_API_KEY is not exported or present in .env"
fi

echo "[5/8] Docker availability and image build"
if [[ "$SKIP_DOCKER" == true ]]; then
  "$PYTHON_BIN" scripts/local_e2e.py
  echo "release gate passed without Docker; run again without --skip-docker before deployment"
  exit 0
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "release gate blocked: Docker CLI is not installed; install/start Docker and retry" >&2
  exit 2
fi
docker info >/dev/null
docker build -t "$IMAGE_TAG" .

echo "[6/8] Container health"
docker run --rm -d --name "$CONTAINER_NAME" -p 127.0.0.1::8080 "$IMAGE_TAG" >/dev/null
MAPPING="$(docker port "$CONTAINER_NAME" 8080/tcp | head -n 1)"
PORT="${MAPPING##*:}"
BASE_URL="http://127.0.0.1:$PORT"
for _attempt in {1..30}; do
  if curl --fail --silent "$BASE_URL/api/health" >/dev/null; then
    break
  fi
  sleep 0.5
done
curl --fail --silent "$BASE_URL/api/health" >/dev/null

echo "[7/8] LIVE API frontend bundle"
INDEX_HTML="$(curl --fail --silent "$BASE_URL/")"
ASSET_PATH="$(printf '%s' "$INDEX_HTML" | sed -n 's/.*src="\([^"]*\.js\)".*/\1/p' | head -n 1)"
if [[ -z "$ASSET_PATH" ]]; then
  echo "release gate failed: frontend JavaScript asset not found" >&2
  exit 1
fi
BUNDLE="$(curl --fail --silent "$BASE_URL$ASSET_PATH")"
if [[ "$BUNDLE" != *"LIVE API"* || "$BUNDLE" == *"MOCK MODE"* ]]; then
  echo "release gate failed: frontend bundle is not in LIVE API mode" >&2
  exit 1
fi

echo "[8/8] Live HTTP demo contract"
"$PYTHON_BIN" scripts/load_demo.py --base-url "$BASE_URL" >"$DEMO_RESULT"
"$PYTHON_BIN" scripts/check_demo_result.py "$DEMO_RESULT"

echo "release gate passed"
