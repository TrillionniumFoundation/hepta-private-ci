#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
mode="${1:---dev}"
case "$mode" in --dev|--audit|--staged|--push) ;; *) exit 10 ;; esac
python3 scripts/ci/project_boundary.py "$mode" "${2:-}" "${3:-}"
