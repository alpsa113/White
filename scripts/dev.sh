#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"

cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  echo "[WARN] 루트 .env 파일이 없습니다. RDS/S3/API 설정이 기본값으로 동작할 수 있습니다."
fi

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "[ERROR] frontend 디렉토리를 찾지 못했습니다: $FRONTEND_DIR"
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "[ERROR] python 명령을 찾지 못했습니다."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm 명령을 찾지 못했습니다. Node.js 설치 또는 PATH 설정을 확인하세요."
  exit 1
fi

if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "[ERROR] uvicorn이 설치되어 있지 않습니다. pip install -r requirements.txt 를 먼저 실행하세요."
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "[INFO] frontend/node_modules가 없어 npm install을 실행합니다."
  (cd "$FRONTEND_DIR" && npm install)
fi

cleanup() {
  echo
  echo "[INFO] 개발 서버를 종료합니다."
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

echo "[INFO] FastAPI 시작: http://127.0.0.1:8000"
python -m uvicorn backend:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

echo "[INFO] React/Vite 시작: http://127.0.0.1:5173"
(cd "$FRONTEND_DIR" && npm run dev -- --host 0.0.0.0) &
FRONTEND_PID=$!

if command -v open >/dev/null 2>&1; then
  (
    sleep 3
    open "http://127.0.0.1:5173/login"
  ) &
else
  echo "[INFO] 브라우저에서 http://127.0.0.1:5173/login 접속"
fi

wait "$API_PID" "$FRONTEND_PID"
