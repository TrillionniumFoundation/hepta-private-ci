#!/usr/bin/env bash
set -euo pipefail
exec python3 scripts/cognitive_read_release_evidence.py "$@"
