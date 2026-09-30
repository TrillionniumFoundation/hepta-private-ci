#!/usr/bin/env python3
"""Fail-closed structural qualification for the immutable ui.native candidate."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")

FORBIDDEN_WORKFLOWS = {
    "hepta-ui-native-acceptance-proposal.yml",
    "hepta-ui-native-current-source.yml",
    "hepta-ui-native-fix-materializer.yml",
    "hepta-ui-native-integrate-20260928.yml",
    "hepta-ui-native-operational-materialize.yml",
    "hepta-ui-native-projections.yml",
    "hepta-ui-native-qualified-integration.yml",
    "hepta-ui-native-remediation-format.yml",
    "hepta-ui-native-remediation.yml",
    "hepta-ui-native-slim-materializer.yml",
    "hepta-ui-native-source-integrity.yml",
    "ui-native-direct-apply-once.yml",
    "ui-native-remediation-apply-once.yml",
    "ui-native-source-export-pr.yml",
    "ui-native-wal-index-apply-once.yml",
    "ui-native-wal-index-export-pr.yml",
}
ALLOWED_WORKFLOW = "ui-native-qualification.yml"

STATE_FILES = (
    "apps/hepta-native/CURRENT_SOURCE.json",
    "apps/hepta-native/CANDIDATE.json",
    "apps/hepta-native/STORAGE_BUDGETS.json",
    "docs/modules/ui.native/CURRENT_SOURCE.json",
    "docs/modules/ui.native/CURRENT_DELIVERY.json",
    "docs/modules/ui.native/IMPLEMENTATION_MAP.json",
    "docs/modules/ui.native/QUALIFICATION_MANIFEST.json",
)

IMPLEMENTATION_PATHS = (
    "apps/hepta-native/src",
    "apps/hepta-native/tests",
    "apps/hepta-native/Cargo.toml",
    "apps/hepta-native/Cargo.lock",
    "codex-rs/hepta-native-gateway",
    "codex-rs/hepta-private-state",
    "codex-rs/hepta-contracts/src/authority_lease.rs",
    "codex-rs/hepta-contracts/src/final_use.rs",
    "codex-rs/hepta-contracts/src/final_use_control.rs",
    "codex-rs/hepta-contracts/src/final_use_store.rs",
    "codex-rs/hepta-contracts/src/native_gateway.rs",
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_json(path: str) -> dict[str, Any]:
    value = json.loads(_read(path))
    _require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def _walk(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="strict"
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_success(*args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    ).returncode == 0


def check_repository() -> dict[str, Any]:
    workflows = ROOT / ".github" / "workflows"
    for name in FORBIDDEN_WORKFLOWS:
        _require(not (workflows / name).exists(), f"retired writer workflow remains: {name}")

    ui_native_workflows = sorted(path.name for path in workflows.glob("*ui-native*.yml"))
    _require(
        ui_native_workflows == [ALLOWED_WORKFLOW],
        f"unexpected ui.native workflow set: {ui_native_workflows}",
    )
    workflow = _read(f".github/workflows/{ALLOWED_WORKFLOW}")
    for forbidden in ("contents: write", "git push", "git commit", "git apply"):
        _require(forbidden not in workflow, f"qualification workflow contains {forbidden!r}")
    _require("persist-credentials: false" in workflow, "checkout credentials are persisted")
    _require("cancel-in-progress: false" in workflow, "exact-source run may be cancelled")
    _require("exact head" in workflow, "exact-head platform subjects are missing")
    _require("ordered-parent merge" in workflow, "ordered-parent merge subjects are missing")

    ci_root = ROOT / ".ci"
    if ci_root.exists():
        capsules = sorted(str(path.relative_to(ROOT)) for path in ci_root.glob("ui-native*"))
        _require(not capsules, f"ui.native patch capsules remain: {capsules}")

    journal = _read("apps/hepta-native/src/journal.rs")
    storage = _read("apps/hepta-native/src/journal_storage.rs")
    retirement = _read("apps/hepta-native/src/retirement.rs")
    platform = _read("apps/hepta-native/src/platform.rs")

    source_contracts = {
        "journal-v7": 'const JOURNAL_SCHEMA_V7: &str = "hepta.native-operation-journal.v7";',
        "wal-v1": 'const WAL_SCHEMA: &str = "hepta.native-operation-wal.v1";',
        "active-index": "operation_index: HashMap<OperationKey, usize>",
        "wal-magic": 'const WAL_MAGIC: &[u8; 8] = b"HPTNWAL1";',
        "retirement-v3": 'const HEAD_SCHEMA: &str = "hepta.native-retirement.v3";',
        "retirement-index-v1": 'const INDEX_SCHEMA: &str = "hepta.native-retirement-index.v1";',
        "retirement-bucket-v1": 'const BUCKET_SCHEMA: &str = "hepta.native-retirement-index-bucket.v1";',
    }
    joined = "\n".join((journal, storage, retirement))
    for name, token in source_contracts.items():
        _require(token in joined, f"missing source contract {name}: {token}")

    budgets = _load_json("apps/hepta-native/STORAGE_BUDGETS.json")
    structural = budgets.get("structural")
    _require(isinstance(structural, dict), "storage structural budgets are missing")
    _require(budgets.get("status") == "provisional-unqualified", "budgets claim qualification")
    _require(budgets.get("measurements") is None, "unreviewed measurements are embedded")
    exact_constants = {
        "maxActiveRecords": "const MAX_OPERATION_RECORDS: usize = 4096;",
        "maxSnapshotBytes": "const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;",
        "maxWalBytes": "const MAX_WAL_BYTES: u64 = 4 * 1024 * 1024;",
        "maxWalFrameBytes": "const MAX_WAL_FRAME_BYTES: u64 = 128 * 1024;",
        "checkpointWalEntries": "const WAL_CHECKPOINT_ENTRIES: usize = 128;",
        "retirementSegmentEntries": "const SEGMENT_ENTRIES: usize = 1024;",
        "retirementSegmentBytes": "const SEGMENT_BYTES: u64 = 512 * 1024;",
        "retirementRecordBytes": "const RECORD_BYTES: u64 = 32 * 1024;",
        "retirementIndexBucketEntries": "const MAX_INDEX_BUCKET_ENTRIES: usize = 65_536;",
        "retirementIndexCacheEntries": "const MAX_INDEX_CACHE_ENTRIES: usize = 65_536;",
    }
    for key, token in exact_constants.items():
        _require(key in structural, f"storage budget {key} is missing")
        _require(token in joined, f"source constant for {key} drifted")

    _require('Command::new("/usr/bin/osascript")' in platform, "macOS launcher is not absolute")
    _require('Command::new("/usr/bin/notify-send")' in platform, "Linux launcher is not absolute")
    _require('Command::new("osascript")' not in platform, "PATH-resolved osascript remains")
    _require('Command::new("notify-send")' not in platform, "PATH-resolved notify-send remains")
    _require("command.env_clear();" in platform, "launcher environment is not cleared")

    anchors: dict[str, str] = {}
    trees: dict[str, str] = {}
    for relative in STATE_FILES:
        state = _load_json(relative)
        anchor = state.get("implementationSourceSha")
        tree = state.get("implementationSourceTree")
        _require(
            isinstance(anchor, str) and SHA1_RE.fullmatch(anchor) is not None,
            f"{relative} lacks a valid implementationSourceSha",
        )
        _require(
            isinstance(tree, str) and SHA1_RE.fullmatch(tree) is not None,
            f"{relative} lacks a valid implementationSourceTree",
        )
        anchors[relative] = anchor
        trees[relative] = tree
        for key, value in _walk(state):
            if key in {"productionQualified", "deploymentQualified", "releaseAuthorized"}:
                _require(value is False, f"{relative} falsely sets {key}={value!r}")

    unique_anchors = sorted(set(anchors.values()))
    unique_trees = sorted(set(trees.values()))
    _require(len(unique_anchors) == 1, f"state anchors disagree: {anchors}")
    _require(len(unique_trees) == 1, f"state trees disagree: {trees}")
    implementation = unique_anchors[0]
    implementation_tree = unique_trees[0]
    _require(_git_success("cat-file", "-e", f"{implementation}^{{commit}}"),
             "implementation source commit is unavailable")
    _require(_git_value("rev-parse", f"{implementation}^{{tree}}") == implementation_tree,
             "implementation source tree does not match its commit")
    _require(
        _git_success("diff", "--quiet", implementation, "HEAD", "--", *IMPLEMENTATION_PATHS),
        "metadata continuation changes product implementation after the frozen source",
    )

    head = _git_value("rev-parse", "HEAD")
    tree = _git_value("rev-parse", "HEAD^{tree}")
    parents = (_git_value("show", "-s", "--format=%P", "HEAD") or "").split()
    return {
        "schema": "hepta.ui-native-source-evidence.v1",
        "status": "structural-pass",
        "implementationSourceSha": implementation,
        "implementationSourceTree": implementation_tree,
        "repositoryHead": head,
        "repositoryTree": tree,
        "orderedParents": parents,
        "workflow": ALLOWED_WORKFLOW,
        "retiredWorkflowCount": len(FORBIDDEN_WORKFLOWS),
        "sourceContracts": sorted(source_contracts),
        "limitations": [
            "structural evidence is not physical-platform acceptance",
            "performance budgets remain unqualified until measured artifacts are attached",
            "release flags remain false pending independent review",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit", type=Path)
    args = parser.parse_args()
    evidence = check_repository()
    encoded = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.emit is not None:
        args.emit.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
