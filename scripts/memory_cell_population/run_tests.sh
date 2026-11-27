#!/usr/bin/env bash
set -euo pipefail

population_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$population_repo"
export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
export PYTHONPATH="$population_repo/scripts/memory_cell:$population_repo/scripts/memory_cell_growth:$population_repo/scripts/memory_cell_router:$population_repo/scripts/memory_cell_codec:$population_repo/scripts/memory_cell_population:${PYTHONPATH:-}"
population_python="${POPULATION_PYTHON:-python}"
"$population_python" -B -m unittest discover -s scripts/memory_cell_router -p 'test_*.py' -v
"$population_python" -B -m unittest discover -s scripts/memory_cell_codec -p 'test_*.py' -v
"$population_python" -B -m unittest discover -s scripts/memory_cell_population -p 'test_*.py' -v
