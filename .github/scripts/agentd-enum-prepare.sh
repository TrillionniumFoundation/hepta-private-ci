set -euo pipefail
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
test "$(git rev-parse "$CANDIDATE^")" = "c254e66d7acd975ba62d7eadd78d2a7dc0e963f1"
test "$(git rev-parse "$CANDIDATE^^")" = "$BASE"
dest=$RUNNER_TEMP/enum-evidence
mkdir -p "$dest"
cp .github/scripts/agentd-enum-driver.py "$RUNNER_TEMP/enum-driver.py"
cp .github/scripts/agentd-enum-cases.json "$RUNNER_TEMP/enum-cases.json"
cp "$RUNNER_TEMP/enum-cases.json" "$dest/cases.json"
for arm in base candidate; do
  if [ "$arm" = base ]; then ref=$BASE; else ref=$CANDIDATE; fi
  git worktree add --quiet --detach "$RUNNER_TEMP/enum-$arm" "$ref"
  git -C "$RUNNER_TEMP/enum-$arm" rev-parse HEAD | tee "$dest/identity-$arm.txt"
  python3 - "$RUNNER_TEMP/enum-cases.json" "$ref" "$dest/fixtures-$arm.txt" <<'PY'
import json,subprocess,sys
from pathlib import Path
cases=json.loads(Path(sys.argv[1]).read_text());names=sorted({n for row in cases.values()for n in row});rows=subprocess.check_output(['git','ls-tree',sys.argv[2],'--',*['codex-rs/hepta-agentd/src/'+n for n in names]]);assert len(rows.splitlines())==len(names);Path(sys.argv[3]).write_bytes(rows)
PY
done
cmp "$dest/fixtures-base.txt" "$dest/fixtures-candidate.txt"
