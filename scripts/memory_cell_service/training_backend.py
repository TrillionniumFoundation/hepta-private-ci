"""Fresh-base source replay and pinned, metadata-only publication artifacts.

The checkpoint receipt binds the exact source snapshot. It is local research
evidence, not an attestation of an untrusted trainer or proof of unlearning.
"""

import hashlib
import os
from pathlib import Path

from durability import create_directory, sync_directory
from metadata_catalog import MetadataCatalog, SCHEMA
from service_types import canonical, digest, verify_snapshot
from tensor_contract import bounded_read, strict_json


DEFAULT_TEMPLATES = [
    "What is the {relation} for {entity}?",
    "Recall the {relation} of {entity}.",
    "For {entity}, return the stored {relation}.",
    "Give {entity}'s {relation}.",
]
POLICY = "fresh_base_all_current_unconflicted_sources"
CANDIDATE_FIELDS = {
    "schema",
    "scope",
    "cell_id",
    "role",
    "source_epoch",
    "source_snapshot_digest",
    "directory",
    "manifest_sha256",
    "catalog_path",
    "catalog_sha256",
    "replay_policy",
    "production_accepted",
}


def seal_candidate(snapshot, directory, manifest_sha256):
    """Persist the exact key/root catalog next to an already saved checkpoint."""
    verify_snapshot(snapshot)
    directory = Path(directory).absolute()
    catalog = {
        "schema": SCHEMA,
        "scope": snapshot["scope"],
        "cell_id": snapshot["cell_id"],
        "manifest_sha256": manifest_sha256,
        "entries": [
            {k: fact[k] for k in ("entity", "relation", "source_digest")}
            for fact in snapshot["facts"]
        ],
        "production_accepted": False,
    }
    payload = canonical(catalog)
    path = directory.parent / "catalog.json"
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)
    return {
        "schema": "hepta.memory-service.candidate.v1",
        "scope": snapshot["scope"],
        "cell_id": snapshot["cell_id"],
        "role": snapshot["role"],
        "source_epoch": snapshot["epoch"],
        "source_snapshot_digest": snapshot["digest"],
        "directory": str(directory),
        "manifest_sha256": manifest_sha256,
        "catalog_path": str(path),
        "catalog_sha256": hashlib.sha256(payload).hexdigest(),
        "replay_policy": POLICY,
        "production_accepted": False,
    }


def verify_candidate(candidate, snapshot, artifacts):
    """Bind persisted metadata, clean replay receipt, keys and checkpoint bytes."""
    verify_snapshot(snapshot)
    if (
        type(candidate) is not dict
        or set(candidate) != CANDIDATE_FIELDS
        or candidate["schema"] != "hepta.memory-service.candidate.v1"
        or candidate["replay_policy"] != POLICY
        or candidate["production_accepted"] is not False
        or any(
            candidate[k] != snapshot[v]
            for k, v in (
                ("scope", "scope"),
                ("cell_id", "cell_id"),
                ("role", "role"),
                ("source_epoch", "epoch"),
                ("source_snapshot_digest", "digest"),
            )
        )
    ):
        raise ValueError("candidate source version, role or replay policy mismatch")
    directory = Path(candidate["directory"])
    catalog_path = Path(candidate["catalog_path"])
    artifacts = Path(artifacts).resolve()
    if (
        directory != directory.resolve()
        or not directory.is_relative_to(artifacts)
        or catalog_path != directory.parent / "catalog.json"
    ):
        raise ValueError("candidate must remain in its retained artifact directory")
    data = bounded_read(directory / "lineage.json", 256 * 1024)
    if hashlib.sha256(data).hexdigest() != candidate["manifest_sha256"]:
        raise ValueError("candidate checkpoint manifest changed")
    manifest = strict_json(data)
    training = manifest.get("training", {})
    roots = sorted({f["source_digest"] for f in snapshot["facts"]})
    if (
        not roots
        or manifest.get("scope") != snapshot["scope"]
        or manifest.get("roots") != roots
        or training.get("initialization") != "frozen_base"
        or training.get("learned_parent_manifest_sha256") is not None
        or training.get("inherited_roots") != []
        or training.get("source_facts_sha256") != digest(snapshot["facts"])
        or training.get("roots") != roots
        or training.get("source_digests")
        != [f["source_digest"] for f in snapshot["facts"]]
    ):
        raise ValueError("candidate was not clean-replayed from the exact live facts")
    MetadataCatalog(catalog_path, candidate["catalog_sha256"])
    catalog = strict_json(bounded_read(catalog_path, 128 * 1024))
    expected = {
        "schema": SCHEMA,
        "scope": snapshot["scope"],
        "cell_id": snapshot["cell_id"],
        "manifest_sha256": candidate["manifest_sha256"],
        "entries": [
            {k: f[k] for k in ("entity", "relation", "source_digest")}
            for f in snapshot["facts"]
        ],
        "production_accepted": False,
    }
    if catalog != expected:
        raise ValueError("metadata catalog differs from the sealed source facts")
    return training


def train_candidate(
    snapshot,
    destination,
    base_dir,
    *,
    steps=128,
    rank=8,
    seed=2718,
    learning_rate=0.001,
    templates=None,
):
    """Run actual LoRA optimization; every current fact must receive an update."""
    from parametric_model import SourceMemoryCell
    import torch

    verify_snapshot(snapshot)
    templates = list(DEFAULT_TEMPLATES) if templates is None else list(templates)
    if type(steps) is not int or steps < len(snapshot["facts"]) * len(templates):
        raise ValueError("replay requires at least one full source/template pass")
    destination = Path(destination)
    create_directory(destination, parents=True, exist_ok=False)
    torch.set_num_threads(2)
    cell = SourceMemoryCell(base_dir, rank=rank, seed=seed)
    cell.reset(snapshot["scope"])
    cell.fit_sources(snapshot["facts"], steps, learning_rate, templates)
    directory = destination / "checkpoint"
    manifest = cell.save(directory)
    return seal_candidate(snapshot, directory, manifest)
