set -euo pipefail
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
test "$(git rev-parse "$CANDIDATE^")" = "$BASE"
dst="$RUNNER_TEMP/streams-lint-evidence"
mkdir -p "$dst"
cp .github/scripts/agentd-streams-cases.json "$RUNNER_TEMP/streams-cases.json"
cp .github/scripts/agentd-streams-driver.py "$RUNNER_TEMP/streams-driver.py"
for arm in base candidate; do
  if [ "$arm" = base ]; then ref="$BASE"; else ref="$CANDIDATE"; fi
  git worktree add --quiet --detach "$RUNNER_TEMP/streams-$arm" "$ref"
  git -C "$RUNNER_TEMP/streams-$arm" rev-parse HEAD | tee "$dst/identity-$arm.txt"
  python3 - "$RUNNER_TEMP/streams-cases.json" "$ref" "$dst/fixtures-$arm.txt" <<'PY'
import json,subprocess,sys
from pathlib import Path
files=json.loads(Path(sys.argv[1]).read_text())
rows=subprocess.check_output(['git','ls-tree',sys.argv[2],'--',*['codex-rs/hepta-agentd/src/'+p for p in sorted(files)]])
assert len(rows.splitlines())==len(files)
Path(sys.argv[3]).write_bytes(rows)
PY
done
cmp "$dst/fixtures-base.txt" "$dst/fixtures-candidate.txt"
