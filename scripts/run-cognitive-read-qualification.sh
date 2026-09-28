#!/usr/bin/env bash
set -euo pipefail
# Source and merge use the same explicit gate inventory. This runner is read-only.
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
exec python3 scripts/cognitive_read_evidence.py "$@"
