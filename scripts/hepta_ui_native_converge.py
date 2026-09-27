#!/usr/bin/env python3
"""Materialize the reviewed ui.native convergence proposal exactly once.

The branch carries a content-addressed patch only as a transport envelope. This
program verifies that envelope, applies it without hand-editing the generated
module registry, closes the review-found portability/lint regressions, and
leaves release/signing/independent-acceptance authority false.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH_B64 = ROOT / ".github/materializers/ui-native-convergence.patch.gz.b64"
PATCH_SHA256 = "94c62379e1dcfe220040a21c3db5febcc140e5c3a5d4fef4158e667f7487263c"
BRANCH = "work/ui-native-integration-convergence-20260927"


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one convergence site in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def materialize_patch() -> None:
    encoded = "".join(PATCH_B64.read_text(encoding="utf-8").split())
    patch = gzip.decompress(base64.b64decode(encoded, validate=True))
    observed = hashlib.sha256(patch).hexdigest()
    if observed != PATCH_SHA256:
        raise SystemExit(
            f"ui.native convergence patch digest mismatch: {observed} != {PATCH_SHA256}"
        )
    with tempfile.NamedTemporaryFile(prefix="ui-native-", suffix=".patch") as handle:
        handle.write(patch)
        handle.flush()
        # MODULE_DOCS.json is a generated projection and has advanced on the
        # integration base. Rebuild it from authoritative module documents
        # after the source changes instead of applying a stale generated hunk.
        command = [
            "git",
            "apply",
            "--exclude=docs/modules/MODULE_DOCS.json",
            handle.name,
        ]
        run(*command[:2], "--check", *command[2:])
        run(*command)


def close_review_regressions() -> None:
    replace_once(
        "apps/hepta-native/src/retirement.rs",
        """            if let Some(previous) = self.record_digests.get(&identity) {\n                if previous != &digest {\n                    return Err(ShellError::State(\n                        \"retired observation is immutable\".to_owned(),\n                    ));\n                }\n            }\n""",
        """            if let Some(previous) = self.record_digests.get(&identity)\n                && previous != &digest\n            {\n                return Err(ShellError::State(\n                    \"retired observation is immutable\".to_owned(),\n                ));\n            }\n""",
    )
    replace_once(
        "apps/hepta-native/tools/prepare_current_source.py",
        """        committed = committed_blob(source_path)\n        if source_path.read_bytes() != committed:\n            raise RuntimeError(f\"native source differs from committed bytes: {relative}\")\n        observed[relative] = hashlib.sha256(committed).hexdigest()\n""",
        """        committed = committed_blob(source_path)\n        committed_oid = git(\"rev-parse\", f\"HEAD:{relative}\")\n        worktree_oid = git(\"hash-object\", f\"--path={relative}\", relative)\n        if worktree_oid != committed_oid:\n            raise RuntimeError(f\"native source differs from committed bytes: {relative}\")\n        observed[relative] = hashlib.sha256(committed).hexdigest()\n""",
    )
    replace_once(
        "scripts/test_hepta_ui_native_source.py",
        "self.git('checkout', '--quiet', '-b', 'work/ui-native-closure-20260927')",
        "self.git('checkout', '--quiet', '-b', source.BRANCH)",
    )
    replace_once(
        "scripts/test_hepta_ui_native_source.py",
        "env = patch.dict(os.environ, HEPTA_UI_NATIVE_WRITE_BRANCH='work/ui-native-closure-20260927')",
        "env = patch.dict(os.environ, HEPTA_UI_NATIVE_WRITE_BRANCH=source.BRANCH)",
    )
    replace_once(
        ".github/workflows/hepta-ui-native-current-source.yml",
        """      - name: Bind canonical exact head and current main\n        id: identity\n        env:\n          EVENT_NAME: ${{ github.event_name }}\n          EVENT_SHA: ${{ github.sha }}\n        run: |\n          set -euo pipefail\n          candidate=$(git rev-parse HEAD)\n          test \"$candidate\" = \"$(git rev-parse HEAD)\"\n          base=a126987b84737dbc2ee2592442a314117bddb4a2\n""",
        """      - name: Bind canonical exact head and pinned merge base\n        id: identity\n        run: |\n          set -euo pipefail\n          candidate=$(git rev-parse HEAD)\n          remote_candidate=$(git ls-remote --exit-code origin refs/heads/work/ui-native-integration-convergence-20260927 | awk '{print $1}')\n          test -n \"$remote_candidate\"\n          test \"$candidate\" = \"$remote_candidate\"\n          base=a126987b84737dbc2ee2592442a314117bddb4a2\n""",
    )


def main() -> None:
    if not PATCH_B64.is_file():
        raise SystemExit("missing content-addressed ui.native convergence patch")
    materialize_patch()
    close_review_regressions()
    run("git", "diff", "--check")


if __name__ == "__main__":
    main()
