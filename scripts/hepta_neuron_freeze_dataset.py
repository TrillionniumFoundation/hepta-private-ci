#!/usr/bin/env python3
"""Evaluator-owned, offline, create-only sealed/blinded Hepta experiment inputs.

Generates no synthetic labels, cannot access production routes, and never
certifies independent data origin, actual future elapsed time, or NDU utility.
The sealed source file stays solely with the evaluator; only the blinded export
may be forwarded to an inference runner.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from hepta_neuron_model_trials import (
    ARMS,
    InvalidTrial,
    blind_rows,
    canonical_jsonl,
    is_sha,
    load_inputs,
    read_json,
    require,
    sha_file,
    strict_json_loads,
    write_new,
)

SCHEMA = "hepta.neuron.dataset-freeze.v1"


def _write_bytes(path, data):
    with open(path, "xb") as target:
        os.chmod(path, 0o600)
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def freeze_dataset(template_path: Path, sealed_path: Path, output_dir: Path):
    """Preflight both roles before publishing a blind dataset + frozen manifest."""
    sealed_path = Path(sealed_path)
    output_dir = Path(output_dir)
    require(
        sealed_path.is_absolute()
        and sealed_path.is_file()
        and not sealed_path.is_symlink(),
        "sealed source must be an existing physical absolute file",
    )
    require(
        output_dir.is_absolute()
        and not output_dir.exists()
        and not output_dir.is_symlink(),
        "output must be a new absolute directory",
    )
    require(
        output_dir.parent.is_dir() and not output_dir.parent.is_symlink(),
        "unsafe output directory parent",
    )
    require(
        not sealed_path.resolve().is_relative_to(output_dir),
        "sealed data cannot be inside blinded export directory",
    )
    manifest = read_json(template_path)
    require(
        isinstance(manifest, dict) and manifest.get("family") in ARMS,
        "unknown experiment family",
    )
    rows = []
    with open(sealed_path, encoding="utf-8") as source:
        for line in source:
            if line.strip():
                value = strict_json_loads(line)
                require(isinstance(value, dict), "sealed row must be a JSON object")
                rows.append(value)
    require(rows, "empty sealed dataset")
    blinded = canonical_jsonl(blind_rows(rows, manifest["family"]))
    sealed_sha = sha_file(sealed_path)
    blinded_sha = hashlib.sha256(blinded).hexdigest()
    for field, value in (
        ("dataset_sha256", sealed_sha),
        ("blind_dataset_sha256", blinded_sha),
    ):
        prior = manifest.get(field)
        require(
            prior is None or not is_sha(prior) or prior == value,
            f"source manifest {field} conflicts with actual bytes",
        )
        manifest[field] = value

    # Evidence of chronological windows must be checked by the evaluator, not
    # trusted from a caller's split labels. load_inputs enforces all five splits,
    # source-group disjointness, token budget and model/Head dimensions.
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    try:
        os.chmod(staging, 0o700)
        frozen_path = staging / "manifest.json"
        blinded_path = staging / "blinded.jsonl"
        write_new(frozen_path, manifest)
        _write_bytes(blinded_path, blinded)
        _, sealed_rows = load_inputs(frozen_path, sealed_path, role="evaluator")
        _, blind_rows_checked = load_inputs(frozen_path, blinded_path, role="runner")
        require(
            len(sealed_rows) == len(blind_rows_checked),
            "not all cases survived blinding",
        )
        outcome = {
            "schema": SCHEMA,
            "family": manifest["family"],
            "sealed_dataset_sha256": sealed_sha,
            "blinded_dataset_sha256": blinded_sha,
            "manifest_sha256": sha_file(frozen_path),
            "observed_window_counts": dict(
                sorted(Counter(r["split"] for r in sealed_rows).items())
            ),
            "labels_exported_to_runner": False,
            "sealed_labels_independently_attested": False,
            "future_windows_independently_elapsed": False,
            "production_evidence_verified": False,
            "ndu_selection_authorized": False,
            "promotion_authorized": False,
        }
        write_new(staging / "freeze-diagnostic.json", outcome)
        _fsync_dir(staging)
        require(not output_dir.exists(), "destination appeared during freeze")
        # Stage first; only a validated complete directory becomes visible.
        staging.rename(output_dir)
        _fsync_dir(output_dir.parent)
        return outcome
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-template", type=Path, required=True)
    parser.add_argument("--sealed-dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        freeze_dataset(args.manifest_template, args.sealed_dataset, args.output_dir)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
