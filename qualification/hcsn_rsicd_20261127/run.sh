#!/usr/bin/env bash
set -euo pipefail
: "${HCSN_CATALOG_DATA:?Set the path prepared by prepare.py}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
runner="${PYTHON:-python}"
here="$(cd "$(dirname "$0")" && pwd)"
export PYTHONUNBUFFERED=1
for method in literal smooth linear conventional; do
  for seed in 109 271 463; do
    [[ -f "$HCSN_CATALOG_DATA/short/$method-$seed/complete.json" ]] || "$runner" "$here/study.py" fit short "$method" "$seed"
  done
done
"$runner" "$here/study.py" seal short
"$runner" "$here/study.py" confirm short
for seed in 109 271 463; do
  [[ -f "$HCSN_CATALOG_DATA/long/conventional-$seed/complete.json" ]] || "$runner" "$here/study.py" fit long conventional "$seed"
done
"$runner" "$here/study.py" seal long
"$runner" "$here/study.py" confirm long
