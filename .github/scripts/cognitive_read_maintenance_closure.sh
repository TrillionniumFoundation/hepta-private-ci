#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_PARENT:?missing EXPECTED_PARENT}"
: "${RESTORE_COMMIT:?missing RESTORE_COMMIT}"
: "${TARGET_BRANCH:?missing TARGET_BRANCH}"

test "$GITHUB_HEAD_REF" = "$TARGET_BRANCH"
test "$(git rev-parse HEAD^)" = "$EXPECTED_PARENT"
test "$(git diff --name-only "$EXPECTED_PARENT" HEAD)" = ".github/workflows/cognitive-read-qualification.yml"

python3 - <<'PY'
from pathlib import Path

verifier = Path("scripts/verify-cognitive-read-constants.py")
body = verifier.read_text(encoding="utf-8")
old = 'require("scripts/run-cognitive-read-qualification.sh", (\'exec python3 scripts/cognitive_read_evidence.py "$@"\',))'
new = 'require("scripts/run-cognitive-read-qualification.sh", (\'exec python3 scripts/cognitive_read_full_evidence.py "$@"\',))'
if body.count(old) != 1:
    raise SystemExit("unexpected qualification wrapper contract")
verifier.write_text(body.replace(old, new), encoding="utf-8")

evidence = Path("scripts/cognitive_read_evidence.py")
body = evidence.read_text(encoding="utf-8")
old = '''        if label == "test-runner":
            runner_lines = log.read_text(errors="replace").splitlines()
            first_line = runner_lines[0].strip() if runner_lines else ""
            version = re.escape(NEXTEST_VERSION)
            if re.fullmatch(rf"cargo-nextest {version}(?:[ \\t][^\\r\\n]*)?", first_line) is None:
                problems.append("test-runner: missing or unexpected pinned nextest version")
'''
new = '''        if label == "test-runner":
            runner_output = log.read_text(errors="replace").strip()
            version = re.escape(NEXTEST_VERSION)
            if re.fullmatch(rf"cargo-nextest {version}(?:[ \\t][^\\r\\n]*)?", runner_output) is None:
                problems.append("test-runner: missing or unexpected pinned nextest version")
'''
if body.count(old) != 1:
    raise SystemExit("unexpected nextest validation block")
evidence.write_text(body.replace(old, new), encoding="utf-8")

consumers = Path("docs/modules/cognitive.read/CONSUMERS.md")
body = consumers.read_text(encoding="utf-8")
if "\x00" not in body:
    raise SystemExit("expected embedded NUL marker is absent")
consumers.write_text(body.replace("\x00", ""), encoding="utf-8")
PY

cargo fmt --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-cognitive-read \
  -p codex-hepta-agentd

cargo check --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-cognitive-read \
  -p codex-hepta-agentd \
  --all-targets

git show "$RESTORE_COMMIT":.github/workflows/cognitive-read-qualification.yml \
  > .github/workflows/cognitive-read-qualification.yml
rm -f \
  .github/workflows/cognitive-read-maintenance-closure.yml \
  .github/scripts/cognitive_read_maintenance_closure.sh

python3 -m unittest discover -s scripts -p 'test_cognitive_read_*.py'
python3 scripts/verify-cognitive-read-constants.py
cargo fmt --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-cognitive-read \
  -p codex-hepta-agentd -- --check
cargo check --manifest-path codex-rs/Cargo.toml --locked \
  -p codex-hepta-cognitive-read \
  -p codex-hepta-agentd \
  --all-targets
git diff --check

python3 - <<'PY'
import subprocess

changed = subprocess.check_output(
    ["git", "diff", "--name-only", "HEAD", "--"], text=True
).splitlines()
allowed_exact = {
    ".github/scripts/cognitive_read_maintenance_closure.sh",
    ".github/workflows/cognitive-read-maintenance-closure.yml",
    ".github/workflows/cognitive-read-qualification.yml",
    "codex-rs/Cargo.lock",
    "docs/modules/cognitive.read/CONSUMERS.md",
    "scripts/cognitive_read_evidence.py",
    "scripts/verify-cognitive-read-constants.py",
}
allowed_prefixes = (
    "codex-rs/hepta-agentd/src/cognitive_context",
    "codex-rs/hepta-cognitive-read/",
)
unexpected = [
    path for path in changed
    if path not in allowed_exact
    and not any(path.startswith(prefix) for prefix in allowed_prefixes)
]
if unexpected:
    raise SystemExit(f"unexpected maintenance paths: {unexpected}")
required = {
    ".github/scripts/cognitive_read_maintenance_closure.sh",
    ".github/workflows/cognitive-read-maintenance-closure.yml",
    ".github/workflows/cognitive-read-qualification.yml",
    "codex-rs/Cargo.lock",
    "docs/modules/cognitive.read/CONSUMERS.md",
    "scripts/cognitive_read_evidence.py",
    "scripts/verify-cognitive-read-constants.py",
}
missing = sorted(required.difference(changed))
if missing:
    raise SystemExit(f"required maintenance paths unchanged: {missing}")
print("\n".join(changed))
PY

git config user.name 'Cognitive Read Maintenance'
git config user.email 'cognitive-read-maintenance@users.noreply.github.com'
git add -A
git diff --cached --check
git commit -m 'fix(cognitive.read): close exact qualification blockers'

python3 scripts/hepta-implementation-maps.py migrate --module cognitive.read
git add docs/modules/cognitive.read/IMPLEMENTATION_MAP.json
git diff --cached --quiet || \
  git commit -m 'docs(cognitive.read): rebind repaired source evidence'

candidate="$(git rev-parse HEAD)"
tree="$(git rev-parse HEAD^{tree})"
python3 scripts/verify-cognitive-read-map.py \
  --expected-sha "$candidate" \
  --expected-tree "$tree"
python3 scripts/cognitive_read_consumers.py \
  --expected-sha "$candidate" \
  --output "$RUNNER_TEMP/cognitive-read-consumers.json"
python3 scripts/hepta-implementation-maps.py verify \
  --expected-sha "$candidate" \
  --expected-tree "$tree"
test -z "$(git status --porcelain --untracked-files=no)"

git push origin "HEAD:$TARGET_BRANCH"
