"""Reconstruct retained model, metadata, evaluation and baseline cost accounting."""

import hashlib
import json
import math
from pathlib import Path
import struct

from population_audit_artifacts import _bytes, _json, _read, _require, _same


def _costs(directory, result, points, receipts):
    costs, training, selection, final, codec, baseline = (
        result[k]
        for k in ("costs", "training", "selection", "final", "codec", "baseline")
    )
    acquisition = _json(directory / "model-acquisition.json")
    model = Path(_json(directory / "final/final-single-request.json")["model"])
    _require(
        acquisition["revision"] == "12fd25f77366fa6b3b4b768ec3050bf629380bac",
        "publisher model revision",
    )
    for entry in acquisition["files"]:
        path, digest = model / entry["path"], hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        _require(
            path.stat().st_size == entry["bytes"]
            and digest.hexdigest() == entry["sha256"],
            "actual shared base artifact",
        )
    base_bytes = sum(row["bytes"] for row in acquisition["files"])
    _require(
        acquisition["total_bytes"] == base_bytes == costs["shared_base_disk_bytes"],
        "full shared base counted",
    )
    with (model / "model.safetensors").open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        _require(0 < length <= 1024 * 1024, "bounded shared base header")
        header = json.loads(stream.read(length))
    _require(
        costs["base_tensor_bytes_loaded_float32"]
        == sum(
            math.prod(v["shape"]) * 4 for k, v in header.items() if k != "__metadata__"
        ),
        "loaded float32 base size separate from storage",
    )
    snapshots = sum(p["retained_bytes"] for entries in points.values() for p in entries)
    snapshots += sum(
        p.stat().st_size
        for p in Path(training["expanded_parent"]["directory"]).iterdir()
        if p.is_file()
    )
    packed = sum(
        sum(
            p.stat().st_size
            for p in (directory / f"codec/int{bits}-packed").iterdir()
            if p.is_file()
        )
        for bits in (8, 4)
    )
    materialized = sum(
        sum(
            p.stat().st_size
            for p in (directory / f"codec/int{bits}-materialized").iterdir()
            if p.is_file()
        )
        for bits in (8, 4)
    )
    ledger, router = (
        len(_read(directory / "exact-baselines/complete_records.json")),
        len(_read(directory / "selection/learned-router.bin")),
    )
    owners = sum(
        (directory / part / "owners.sqlite3").stat().st_size
        for part in ("final", "codec")
    )
    source_fields = {
        "semantic": ("kind", "entity", "relation", "source_digest"),
        "episode": ("kind", "entity", "day", "source_digest"),
        "procedure": ("kind", "rule", "source_digest"),
    }
    capabilities = len(
        _bytes(
            [
                {key: row[key] for key in source_fields[row["kind"]]}
                for row in _json(directory / "dataset.json")["sources"]
            ]
        )
    )
    active = selection["choice"]["selected_cost"]
    hot = (
        active["retained_checkpoint_bytes"]
        + active["router_artifact_bytes"]
        + ledger
        + capabilities
        + (directory / "final/owners.sqlite3").stat().st_size
    )
    expected = {
        "source_ledger_bytes": ledger,
        "router_artifact_bytes": router,
        "owner_database_bytes": owners,
        "all_training_checkpoint_bytes": snapshots,
        "all_codec_packed_bytes": packed,
        "all_codec_materialized_bytes": materialized,
        "capability_metadata_bytes": capabilities,
        "selected_hot_artifacts_excluding_shared_base_bytes": hot,
        "selected_hot_artifacts_including_shared_base_bytes": hot + base_bytes,
        "retained_data_and_model_lower_bound_bytes": base_bytes
        + snapshots
        + packed
        + materialized
        + ledger
        + router
        + owners
        + capabilities,
        "data_only_exact_best_bytes": baseline[
            "smallest_complete_exact_representation"
        ]["bytes"],
    }
    for key, value in expected.items():
        _same(costs[key], value, "complete retained cost: " + key)
    for key, value in (
        ("total_optimizer_updates", 2560),
        ("candidate_optimizer_updates", 2048),
        ("common_parent_updates", 512),
        ("common_parent_input_tokens", receipts["parent"]["input_tokens"]),
        (
            "candidate_input_tokens",
            sum(receipts[k]["input_tokens"] for k in ("single", "split-0", "split-1")),
        ),
        ("all_retained_snapshot_bytes", snapshots),
    ):
        _same(training["costs"][key], value, "raw training cost totals")
    _same(costs["training"], training["costs"], "training costs included")
    _same(
        costs["source_selection"],
        selection["source_work"],
        "selection evaluation charged",
    )
    _same(
        costs["final_reads"], final["work"], "all diagnostic final evaluation charged"
    )
    _require(
        costs["full_system_costs_and_comparable_baseline_accounted"] is False,
        "declared cost lower bound cannot certify positive complete-system compression",
    )
    _require(
        costs["retained_data_and_model_lower_bound_bytes"]
        > costs["data_only_exact_best_bytes"],
        "fixture retains a negative net storage outcome",
    )
