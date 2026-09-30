#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# One command contract drives both execution and receipt verification. No source
# repair, success-field editing, or duplicate shell matrix is permitted here.
exec python3 scripts/memory_federation_execution_receipt.py run
