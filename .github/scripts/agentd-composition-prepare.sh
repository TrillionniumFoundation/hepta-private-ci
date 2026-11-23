set -euo pipefail
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
test "$(git rev-parse HEAD^2)" = "$BASE"
test "$(git rev-parse "$BASE^")" = "e3277e9677688be5c4c235a7a127f0b51e373399"
test "$(git rev-parse "$CANDIDATE^")" = "43e5da1bb81369e4e999adfa8558f5ccb5460eb6"
dest=$RUNNER_TEMP/composition-evidence
mkdir -p "$dest"
cp .github/scripts/agentd-composition-driver.py "$RUNNER_TEMP/composition-driver.py"
cp .github/scripts/agentd-composition-cases.json "$RUNNER_TEMP/composition-cases.json"
cp "$RUNNER_TEMP/composition-cases.json" "$dest/cases.json"
for arm in base candidate; do
  if [ "$arm" = base ]; then ref=$BASE; else ref=$CANDIDATE; fi
  git worktree add --quiet --detach "$RUNNER_TEMP/composition-$arm" "$ref"
  git -C "$RUNNER_TEMP/composition-$arm" rev-parse HEAD | tee "$dest/identity-$arm.txt"
  python3 - "$RUNNER_TEMP/composition-cases.json" "$ref" "$dest/fixtures-$arm.txt" <<'PY'
import json,subprocess,sys
from pathlib import Path
cases=json.loads(Path(sys.argv[1]).read_text());names=sorted({n for row in cases.values()for n in row});rows=subprocess.check_output(['git','ls-tree',sys.argv[2],'--',*['codex-rs/hepta-agentd/src/'+n for n in names]]);assert len(rows.splitlines())==len(names);Path(sys.argv[3]).write_bytes(rows)
PY
done
cmp "$dest/fixtures-base.txt" "$dest/fixtures-candidate.txt"
