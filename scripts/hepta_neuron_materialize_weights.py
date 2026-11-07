#!/usr/bin/env python3
"""Explicit, create-only acquisition of pinned Laya weights for offline shadow trials.

Acquisition is a target-host operator action. The default does not use the network;
--allow-network explicitly opts into Hugging Face transport. Publisher metadata,
physical byte equality, and local tensor shape checks are separate evidence levels.
This tool grants no NDU, serving, activation, or promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path

from hepta_neuron_artifact_preflight import REQUIRED, inspect_local, verify_catalog
from hepta_neuron_model_trials import (
    InvalidTrial,
    physical_absolute_directory,
    read_json,
    require,
    sha_file,
    write_new,
)

SCHEMA = "hepta.neuron.weight-materialization.v1"
MAX_FILE_BYTES = {
    "model.safetensors": 2_000_000_000,
    "tokenizer/tokenizer.json": 128_000_000,
}


def _sync_directory(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_source(src: Path, target: Path, expected_sha: str | None):
    """Copy from the HF cache into a fresh, owned physical file and hash bytes."""
    src = Path(src)
    require(src.is_file(), "acquired cache path is not a file")
    rel = target.as_posix()
    suffix = (
        "model.safetensors"
        if target.name == "model.safetensors"
        else (
            "tokenizer/tokenizer.json"
            if target.name == "tokenizer.json"
            else "metadata"
        )
    )
    limit = MAX_FILE_BYTES.get(suffix, 16_000_000)
    size = src.stat().st_size
    require(0 < size <= limit, f"unexpected artifact size: {rel}")
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with open(src, "rb") as from_file, open(target, "xb") as to_file:
        os.chmod(target, 0o600)
        total = 0
        while piece := from_file.read(1 << 20):
            total += len(piece)
            require(total <= limit, "artifact exceeds maximum allowed bytes")
            to_file.write(piece)
            digest.update(piece)
        to_file.flush()
        os.fsync(to_file.fileno())
    require(total == size, "cache file changed during copy")
    value = digest.hexdigest()
    require(
        expected_sha is None or value == expected_sha,
        "weight digest mismatch; acquired source is not the locked checkpoint",
    )
    return value


def _hf_fetch(repo_id, relative_file, revision, allow_network, cache_dir):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise InvalidTrial(
            "huggingface_hub required for operator-authorized acquisition"
        ) from exc
    return Path(
        hf_hub_download(
            repo_id=repo_id,
            filename=relative_file,
            revision=revision,
            local_files_only=not allow_network,
            cache_dir=cache_dir,
        )
    )


def materialize(
    catalog,
    arm: str,
    destination: Path,
    *,
    allow_network=False,
    cache_dir: str | None = None,
    fetcher=None,
):
    """Create an exclusive destination; never overwrite, infer a branch or accept symlinks.

    Failed downloads are deliberately left under the new destination for operator
    quarantine; they cannot produce a successful receipt or be silently retried.
    """
    verify_catalog(catalog)
    require(arm in catalog["variants"], "unknown model arm")
    require(type(allow_network) is bool, "network admission must be explicit")
    destination = Path(destination)
    require(
        destination.is_absolute()
        and not destination.exists()
        and not destination.is_symlink(),
        "destination must be a new absolute directory",
    )
    parent = destination.parent
    require(
        physical_absolute_directory(parent), "untrusted destination parent ancestry"
    )
    checkout_root = Path(__file__).resolve().parents[1]
    require(
        not destination.resolve().is_relative_to(checkout_root),
        "weight bytes may not be staged inside the source checkout",
    )
    if cache_dir is not None:
        cache = Path(cache_dir)
        require(
            physical_absolute_directory(cache),
            "HF cache must be an existing physical absolute directory",
        )
        cache_dir = str(cache)
    variant = catalog["variants"][arm]
    fetcher = fetcher or _hf_fetch
    # Exclusive reservation: a failed attempt cannot be mistaken for a complete
    # physical checkpoint. Operator must inspect/quarantine any partial directory.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    saved = {}
    try:
        for rel in REQUIRED:
            remote_rel = "/".join(x for x in (variant["subfolder"], rel) if x)
            source = Path(
                fetcher(
                    catalog["repository"],
                    remote_rel,
                    catalog["revision"],
                    allow_network,
                    cache_dir,
                )
            )
            dst = destination / rel
            expected = variant["weights_sha256"] if rel == "model.safetensors" else None
            saved[rel] = _copy_source(source, dst, expected)
        for subdir in (destination / "encoder", destination / "tokenizer"):
            _sync_directory(subdir)
        _sync_directory(destination)
        receipt = inspect_local(catalog, arm, destination)
        require(
            receipt["weights_sha256"] == saved["model.safetensors"],
            "physical byte digest drift during metadata validation",
        )
        _sync_directory(parent)
        return {
            "schema": SCHEMA,
            "catalog_revision": catalog["revision"],
            "model_id": variant["model_id"],
            "arm": arm,
            "relative_file_sha256": saved,
            "physical_artifact_tree_sha256": receipt["artifact_tree_sha256"],
            "local_weight_bytes_verified": True,
            "tensor_inventory_verified": True,
            "network_permission_used": allow_network,
            "independently_attested_host": False,
            "model_forward_executed": False,
            "production_evidence_verified": False,
            "ndu_selection_authorized": False,
            "promotion_authorized": False,
        }
    except Exception:
        # Fail closed. Preserve partial bytes for postmortem; do not call them
        # a completed artifact or publish any success receipt.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--arm", choices=("laya", "typed", "multilingual"), required=True
    )
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--allow-network", action="store_true")
    args = parser.parse_args()
    try:
        require(
            args.output.is_absolute() and not args.output.exists(),
            "receipt must be a new absolute file",
        )
        catalog = verify_catalog(read_json(args.catalog))
        outcome = materialize(
            catalog,
            args.arm,
            args.destination,
            allow_network=args.allow_network,
            cache_dir=args.cache_dir,
        )
        outcome["catalog_sha256"] = sha_file(args.catalog)
        write_new(args.output, outcome)
    except (
        InvalidTrial,
        OSError,
        ImportError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
    ) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
