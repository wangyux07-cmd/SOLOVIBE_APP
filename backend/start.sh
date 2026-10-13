#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port "${SOLOVIBE_PORT:-8000}"
