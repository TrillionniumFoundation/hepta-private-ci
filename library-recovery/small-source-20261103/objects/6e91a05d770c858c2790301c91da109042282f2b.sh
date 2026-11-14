#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python validate_manifest.py
python -m pytest -q
python p0_recompute.py > p0_run.log
set +e
python verify.py qualification.json > denial.log
code=$?
set -e
if [[ "$code" != 1 ]] || ! grep -q 'HOLD_NO_GO' denial.log; then
 echo 'FAIL: expected P0-P4 production denial did not happen' >&2
 exit 2
fi
echo 'P0-P4 remains HOLD_NO_GO, as required'
