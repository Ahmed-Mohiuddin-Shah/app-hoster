#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

uv sync
exec uv run fastapi run --entrypoint main:app --workers 1
