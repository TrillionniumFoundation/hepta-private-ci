#!/usr/bin/env bash
set -euo pipefail

memory_system_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$memory_system_repo"
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
memory_system_paths=""
for memory_system_package in memory_cell memory_cell_growth memory_cell_catalog memory_cell_router memory_cell_codec memory_cell_population memory_cell_service memory_cell_network memory_cell_domain memory_cell_system; do
  memory_system_paths="$memory_system_paths$memory_system_repo/scripts/$memory_system_package:"
done
export PYTHONPATH="$memory_system_paths${PYTHONPATH:-}"
memory_system_python="${MEMORY_SYSTEM_PYTHON:-python}"
for memory_system_suite in memory_cell_service memory_cell_domain memory_cell_network; do
  "$memory_system_python" -B -m unittest discover -s "scripts/$memory_system_suite" -p 'test_*.py' -v
done
