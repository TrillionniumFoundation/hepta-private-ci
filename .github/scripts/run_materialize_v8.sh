#!/usr/bin/env bash
set -Eeuo pipefail

source_script=".github/scripts/materialize_source_v6.sh"
patched_script="$RUNNER_TEMP/materialize_source_v8.sh"
cp "$source_script" "$patched_script"

python3 - "$patched_script" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

replacements = [
    (
        'cp .github/scripts/fix_http_tls_classification.py "$patcher"',
        'cp .github/scripts/fix_http_tls_classification_v8.py "$patcher"',
        "deterministic TLS patcher selection",
    ),
    (
        'python3 .github/scripts/fix_http_tls_classification.py\ncargo fmt --all\n',
        'python3 .github/scripts/fix_http_tls_classification.py\n(cd codex-rs && cargo fmt --all)\n',
        "post-repair Cargo workspace",
    ),
    (
        '''cargo fmt --all
git diff --check
git add -A
''',
        '''# The Hepta Rust workspace lives under codex-rs. Keep the candidate's
# workflow subtree byte-identical to main so the Actions installation token is
# not asked to author workflow changes while publishing the immutable branch.
rm -rf .g1/trillionnium_os_external_evidence
git restore --source=origin/main --staged --worktree -- .github/workflows
(cd codex-rs && cargo fmt --all)
find "$report_dir" -type f -name '*.log' -delete
git diff --check
git add -A
''',
        "candidate commit boundary",
    ),
    (
        '''            "tree_policy": "normal-merge-current-history-only-superseded",
''',
        '''            "tree_policy": "normal-merge-current-history-only-superseded",
            "controller_revision": "v8",
            "workflow_policy": "preserve-main-workflows-for-actions-token-boundary",
            "external_os_evidence_policy": "excluded-from-hepta-product-tree",
''',
        "V8 source-selection metadata",
    ),
]

for old, new, label in replacements:
    if old not in text:
        raise SystemExit(f"materializer patch point missing: {label}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
PY

bash -n "$patched_script"
exec bash "$patched_script"
