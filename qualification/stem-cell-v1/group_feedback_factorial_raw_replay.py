"""Replay all four raw research campaigns in all six fixed seed/optimizer blocks.

This is an immutable-source structural and numerical receipt audit, not an
independent host signature, original human outcome, future efficacy result or
production authorization. It never invokes Torch or any model weights.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from group_checkpoint_audit import strict_json_file
from group_feedback_factorial_aggregate import audit_six, SEEDS, PROFILES, FACTORS
from group_feedback_factorial_review import review_factorial

SOURCE_SHA = "d16fb15ef9d15a83dffa0886438d3e9432f97b66"
MODELS = ("core_initial", "static", "wide", "core", "attention")
JSONS = ("protocol", "report", "observations", "teacher", "encoder", "system2-traces")
MAX_RAW_BYTES = 64_000_000


def _regular_file(path: Path) -> bytes:
    """Acquire bounded original bytes; forbid symlinks and nonregular files."""
    # A prior lstat followed by Path.read_bytes() trusts a second path lookup.
    # Pin one descriptor, never follow final-component symlinks, and validate
    # both pre- and post-read identity on the actual opened file.
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("read-once POSIX O_NOFOLLOW support required")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError("raw receipt unavailable without following links") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_RAW_BYTES:
            raise ValueError("opened original receipt is not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as source:
            data = source.read(before.st_size + 1)
        after = os.fstat(fd)
        if (len(data) != before.st_size or before.st_dev != after.st_dev
                or before.st_ino != after.st_ino or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise ValueError("raw original receipt mutated during read")
        return data
    finally:
        os.close(fd)


def _inventory(bundle: Path):
    """Bind exact immutable source receipts and *all* five model Head archives."""
    files = []
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("original factorial artifact directory is absent or symlinked")
    for factor in FACTORS:
        root = bundle / factor
        if root.is_symlink() or not root.is_dir():
            raise ValueError("missing original factorial arm directory")
        files.extend(root / (name + ".json") for name in JSONS)
        files.extend(root / ("group-" + name + ".safetensors") for name in MODELS)
    files.extend((bundle / "external-recheck.json", bundle / "factorial-independent-review.json"))
    return {p.relative_to(bundle).as_posix(): hashlib.sha256(_regular_file(p)).hexdigest()
            for p in files}


def replay_original_six(root, *, run_id, source_commit=SOURCE_SHA):
    """Reopen 24 original model/trace receipts; reject summary-only evidence."""
    root = Path(root)
    if (type(run_id) is not int or not 1 <= run_id < 10**18
            or type(source_commit) is not str or source_commit != SOURCE_SHA
            or root.is_symlink() or not root.is_dir()):
        raise ValueError("explicit original successful source SHA, run ID and archive root required")
    hashes, original_paths = {}, {}
    expected_names = {
        f"hepta-group-2x2-{seed}-{profile}-{run_id}"
        for seed in SEEDS for profile in PROFILES
    }
    # A mixed-run download directory is unsafe, even if some original receipts match.
    observed_names = {entry.name for entry in root.iterdir()}
    if observed_names != expected_names:
        raise ValueError("exactly six artifacts from one original run required")
    for seed in SEEDS:
        for profile in PROFILES:
            name = f"hepta-group-2x2-{seed}-{profile}-{run_id}"
            path = root / name
            start_inventory = _inventory(path)
            originals = {factor: path / factor for factor in FACTORS}
            # The original stdlib reviewer also validates every original
            # checkpoint, source batch, public symbolic task, trace and cost.
            independently_recomputed = review_factorial(originals)
            original = strict_json_file(path / "factorial-independent-review.json")
            second = strict_json_file(path / "external-recheck.json")
            if (original != second or original != independently_recomputed
                    or original.get("production_promotion_permitted") is not False
                    or original.get("source_consistent_not_independently_attested") is not True):
                raise ValueError("raw original factorial replay differs from both archived audits")
            end_inventory = _inventory(path)
            if start_inventory != end_inventory:
                raise ValueError("raw original receipts changed during independent replay")
            key = (seed, profile)
            hashes[key] = dict(sorted(end_inventory.items()))
            original_paths[key] = path / "external-recheck.json"
    # This independently replays the six report-level arithmetic/cost checks;
    # it does not treat repeated seeds as independent natural future sources.
    result = audit_six(original_paths)
    if result.get("passed") is not True or result.get("winner_selected") is not False:
        raise ValueError("six-block study not independently admissible")
    return dict(schema="hepta.group.factorial-raw-replay.v1",
                original_workflow_source_sha=SOURCE_SHA, original_run_id=run_id,
                source_complete=True, all_original_24_model_checkpoints_reopened=True,
                exact_four_original_audit_replay_per_block=True,
                no_production_authority=True, authority="DENY_ALL",
                physical_execution_attested_independently=False,
                future_natural_task_efficacy_proven=False,
                equal_total_compute_demonstrated=False,
                production_promotion_permitted=False,
                original_raw_file_sha256_by_block={f"{seed}.{profile}": hashes[seed, profile]
                                                   for seed in SEEDS for profile in PROFILES},
                six_block_review=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = replay_original_six(args.artifacts_root, run_id=args.run_id,
                                 source_commit=args.source_commit)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False)


if __name__ == "__main__":
    main()
