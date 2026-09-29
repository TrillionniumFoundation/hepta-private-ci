#!/usr/bin/env bash
set -euo pipefail

: "${EXPECTED_PARENT:?missing EXPECTED_PARENT}"
: "${RESTORE_COMMIT:?missing RESTORE_COMMIT}"
: "${TARGET_BRANCH:?missing TARGET_BRANCH}"

test "$GITHUB_HEAD_REF" = "$TARGET_BRANCH"
test "$(git rev-parse HEAD^)" = "$EXPECTED_PARENT"
test "$(git diff --name-only "$EXPECTED_PARENT" HEAD)" = ".github/workflows/cognitive-read-qualification.yml"
input_head="$(git rev-parse HEAD)"

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
source_commit="$(git rev-parse HEAD)"
source_tree="$(git rev-parse HEAD^{tree})"

python3 scripts/hepta-implementation-maps.py migrate --module cognitive.read
git add docs/modules/cognitive.read/IMPLEMENTATION_MAP.json
git diff --cached --quiet || \
  git commit -m 'docs(cognitive.read): rebind repaired source evidence'
final_commit="$(git rev-parse HEAD)"
final_tree="$(git rev-parse HEAD^{tree})"

python3 scripts/verify-cognitive-read-map.py \
  --expected-sha "$final_commit" \
  --expected-tree "$final_tree"
python3 scripts/cognitive_read_consumers.py \
  --expected-sha "$final_commit" \
  --output "$RUNNER_TEMP/cognitive-read-consumers.json"
python3 scripts/hepta-implementation-maps.py verify \
  --expected-sha "$final_commit" \
  --expected-tree "$final_tree"
test -z "$(git status --porcelain --untracked-files=no)"

out="$RUNNER_TEMP/cognitive-read-maintenance-artifact"
rm -rf "$out"
mkdir -p "$out/files"
git diff --name-only --diff-filter=ACMRT "$input_head" "$final_commit" > "$out/files.txt"
git diff --name-only --diff-filter=D "$input_head" "$final_commit" > "$out/deletions.txt"
while IFS= read -r path; do
  test -n "$path" || continue
  mkdir -p "$out/files/$(dirname "$path")"
  cp "$path" "$out/files/$path"
done < "$out/files.txt"
git diff --binary "$input_head" "$final_commit" > "$out/candidate.patch"
INPUT_HEAD="$input_head" SOURCE_COMMIT="$source_commit" SOURCE_TREE="$source_tree" \
FINAL_COMMIT="$final_commit" FINAL_TREE="$final_tree" python3 - <<'PY'
import json
import os
from pathlib import Path

out = Path(os.environ["RUNNER_TEMP"]) / "cognitive-read-maintenance-artifact"
metadata = {
    "schema": "hepta.cognitive.read.maintenance-artifact.v1",
    "inputHead": os.environ["INPUT_HEAD"],
    "sourceCommit": os.environ["SOURCE_COMMIT"],
    "sourceTree": os.environ["SOURCE_TREE"],
    "finalCommit": os.environ["FINAL_COMMIT"],
    "finalTree": os.environ["FINAL_TREE"],
    "activation": False,
    "release": False,
}
(out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
PY
cp "$RUNNER_TEMP/cognitive-read-consumers.json" "$out/consumers.json"
(
  cd "$out"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)
