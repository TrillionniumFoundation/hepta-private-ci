#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export PYTHONPATH="$PWD/scripts/memory_cell_distributed:$PWD/scripts/memory_cell_network:$PWD/scripts/memory_cell_service:$PWD/scripts/memory_cell:${PYTHONPATH:-}"
python -B -m unittest discover -s scripts/memory_cell_distributed -p 'test_*.py' -v
