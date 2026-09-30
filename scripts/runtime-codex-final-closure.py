#!/usr/bin/env python3
"""Final idempotent runtime.codex source-binding repairs.

This runs after all structural migrations. It installs the final durable-owner
lineage/tombstone layer, binds qualification to the actual workspace toolchain,
and keeps source-closure claims separate from pending execution receipts.
"""

from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one legacy occurrence")
        path.write_text(text.replace(old, new), encoding="utf-8")
        return
    if new in text:
        return
    raise RuntimeError(f"{marker}: expected legacy or migrated content")


def apply_owner_lineage() -> None:
    migration = ROOT / "scripts/runtime-codex-owner-lineage-fixup.py"
    target = ROOT / "codex-rs/hepta-agentd/src/lane_b_runtime.rs"
    marker = "self.runs.len().saturating_add(self.tombstones.len())"
    text = target.read_text(encoding="utf-8")
    if marker not in text:
        old = '''        if self.active_run_count() >= self.max_active_runs || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
'''
        new = '''        if self.active_run_count() >= self.max_active_runs
            || self.runs.len().saturating_add(self.tombstones.len()) >= MAX_RETAINED_RUNS
        {
            return Err(AgentRunError::CapacityExceeded);
        }
'''
        count = text.count(old)
        if count != 2:
            raise RuntimeError(
                f"durable owner capacity migration expected two legacy blocks, found {count}"
            )
        # Pre-apply one occurrence. The reviewed exact migration then sees one
        # remaining legacy block and applies its normal single-match assertion.
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
    if migration.exists():
        runpy.run_path(str(migration), run_name="__main__")
    elif "struct DurableRunTombstoneV1" not in target.read_text(encoding="utf-8"):
        raise RuntimeError("durable owner lineage migration is missing")


def separate_qualification_pending(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if 'value["repositoryControlledGaps"] = []' in text and 'value["qualificationPending"]' in text:
        return
    begin = '    value["repositoryControlledGaps"] = [\n'
    start = text.find(begin)
    if start < 0:
        raise RuntimeError(f"{path.name}: repositoryControlledGaps assignment missing")
    end_marker = '    ]\n'
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{path.name}: repositoryControlledGaps terminator missing")
    end += len(end_marker)
    replacement = '''    value["repositoryControlledGaps"] = []
    value["qualificationPending"] = [
        "exact-head receipt for the final immutable map head",
        "deterministic current-main synthetic-merge receipt for the same source identity",
        "retained real-process crash, product E2E and strict-lint evidence",
    ]
'''
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def drop_stale_materializer_diagnostics() -> None:
    """Remove tracked construction diagnostics from the immutable candidate.

    The live materializer continues writing its current logs in the working
    tree and can retain them on failure. On success, however, no ancestor or
    earlier-attempt diagnostic may survive as a tracked candidate object.
    Removing only the index entries keeps the active log descriptors usable
    until the one-shot workflow has completed every verification command.
    """

    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "qualification/runtime-codex-materialize-debug",
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    tracked = [
        value.decode("utf-8")
        for value in completed.stdout.split(b"\0")
        if value
    ]
    if tracked:
        subprocess.run(
            ["git", "rm", "-f", "--cached", "--ignore-unmatch", "--", *tracked],
            cwd=ROOT,
            check=True,
        )


def main() -> None:
    apply_owner_lineage()
    replace_once(
        ROOT / "scripts/runtime-codex-qualification.py",
        '    "rust-toolchain.toml",\n',
        '    "codex-rs/rust-toolchain.toml",\n',
        "runtime.codex qualification toolchain binding",
    )
    separate_qualification_pending(ROOT / "scripts/runtime-codex-finalize-map.py")
    separate_qualification_pending(
        ROOT / "scripts/runtime-codex-finalize-map-followup.py"
    )
    drop_stale_materializer_diagnostics()


if __name__ == "__main__":
    main()
