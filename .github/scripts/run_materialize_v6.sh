#!/usr/bin/env bash
set -Eeuo pipefail

python3 - <<'PY'
from pathlib import Path

path = Path('.github/scripts/materialize_source_v6.sh')
text = path.read_text(encoding='utf-8')
needle = '''cargo fmt --all
git diff --check
git add -A
'''
replacement = '''cargo fmt --all
# The TLS classifier may run several exact regression trials. Raw logs remain
# workflow artifacts; only its machine-readable selection receipt belongs in
# the immutable repository tree.
find "$report_dir" -type f -name '*.log' -delete
git diff --check
git add -A
'''
if needle not in text:
    raise SystemExit('materializer commit boundary not found')
path.write_text(text.replace(needle, replacement, 1), encoding='utf-8')
PY

bash -n .github/scripts/materialize_source_v6.sh
exec bash .github/scripts/materialize_source_v6.sh
