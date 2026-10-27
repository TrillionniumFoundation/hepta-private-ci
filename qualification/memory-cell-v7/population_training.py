"""Actual bounded shard fits from owner exports, with target-independent routing.

Structural training is clean: every shard starts from fresh parameters and its
complete lineage equals its exact support partition. These are candidate bytes;
the native owner and independent signed release remain authoritative.
"""

from copy import deepcopy
import hashlib
import json
import time

import numpy as np

from native_export import export_cell
from training import AssociativeCell, KINDS, canonical, current_rows


SCHEMA = "hepta.memory.population.native.v2"
PARTITION = "hepta.memory.sha256-address-rank.v1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def address_partition(keys, count):
    """Balanced ranks of address hashes; no values, domains, or answer labels."""
    if type(count) is not int or not 1 <= count <= min(8, len(keys)):
        raise ValueError("population shard count exceeds written addresses")
    addresses = sorted(sha(key.encode()) for key in keys)
    if len(set(addresses)) != len(addresses):
        raise ValueError("duplicate written address")
    return {address: rank * count // len(addresses) for rank, address in enumerate(addresses)}


def configuration(value):
    expected = {"shard_count", "seed", "steps", "dimension", "total_hidden", "threshold"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid population configuration")
    for name, low, high in (("shard_count", 1, 8), ("seed", 0, 2**32 - 1), ("steps", 1, 1000),
                            ("dimension", 8, 256), ("total_hidden", 1, 256)):
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError("population training budget exceeded")
    if value["total_hidden"] < value["shard_count"]:
        raise ValueError("each parameter shard needs at least one hidden unit")
    if type(value["threshold"]) not in (float, int) or not np.isfinite(value["threshold"]) or not 0 <= value["threshold"] <= 1:
        raise ValueError("invalid fixed acceptance threshold")
    return deepcopy(value)


def fit_kind(rows, kind, config):
    count = config["shard_count"]
    routes = address_partition([row["record"]["entity"] for row in rows], count)
    shards, originals, reports = [], [], []
    for index in range(count):
        selected = [row for row in rows if routes[sha(row["record"]["entity"].encode())] == index]
        width = config["total_hidden"] // count + int(index < config["total_hidden"] % count)
        keys = [row["record"]["entity"] for row in selected]
        values = [row["record"]["value"] for row in selected]
        cell = AssociativeCell.fit(keys, values, (config["seed"] + index) % 2**32, kind=kind,
            support_ids=[[row["source_id"]] for row in selected], hidden=width,
            dimension=config["dimension"], steps=config["steps"])
        cell.threshold = float(config["threshold"])
        original = cell.to_bytes()
        native = export_cell(original)
        shards.append({"digest": sha(native), "payload": native.decode()})
        originals.append(original.decode())
        reports.append({"training": deepcopy(cell.training_receipt), "native_digest": sha(native),
            "parameter_digest": cell.parameters_digest(), "source_ids": cell.lineage_sources,
            "parameter_bytes": sum(array.nbytes for array in (cell.A, cell.a, cell.B, cell.b)),
            "catalog_bytes": len(canonical(cell.catalog)), "support_bytes": len(canonical(cell.supports)),
            "lineage_bytes": len(canonical(cell.lineage_sources)), "native_bytes": len(native),
            "original_bytes": len(original)})
    lineage = sorted(row["source_id"] for row in rows)
    native = canonical({"schema": SCHEMA, "kind": kind, "partition_profile": PARTITION,
        "shards": shards, "routes": routes, "lineage_sources": lineage})
    return {"native": native.decode(), "originals": originals}, {
        "native_digest": sha(native), "shards": reports, "serialized_bytes": len(native),
        "raw_payload_bytes": sum(len(shard["payload"].encode()) for shard in shards),
        "route_bytes": len(canonical(routes)), "lineage_bytes": len(canonical(lineage)),
        "resident_parameters_bytes": sum(report["parameter_bytes"] for report in reports),
        "catalog_bytes": sum(report["catalog_bytes"] for report in reports),
    }


def train_populations(export, configuration_value):
    config = configuration(configuration_value)
    rows = current_rows(export)
    started = time.perf_counter_ns()
    cpu = time.process_time_ns()
    artifacts, reports = {}, {}
    for kind in KINDS:
        artifacts[kind], reports[kind] = fit_kind(rows[kind], kind, config)
    return {"schema": "hepta.memory.population-training-result.v2", "scope": export["scope"],
        "owner_cut_digest": export["owner_cut_digest"], "configuration": config,
        "artifacts": artifacts, "receipt": {"types": reports,
            "fit_calls": len(KINDS) * config["shard_count"],
            "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "source_export_bytes": len(canonical(export)), "source_ledger_bytes": None,
            "partition_uses_targets": False, "independent_future_task_evaluation": False,
            "clean_parameters": True, "language_model_finetuning": False, "authority": False}}


def load_shards(artifact):
    """Python diagnostic only; production execution uses the native V2 loader."""
    wire = json.loads(artifact["native"])
    cells = [AssociativeCell.from_bytes(raw.encode()) for raw in artifact["originals"]]
    if len(cells) != len(wire["shards"]):
        raise ValueError("shard count differs")
    for raw, shard in zip(artifact["originals"], wire["shards"]):
        if export_cell(raw.encode()) != shard["payload"].encode() or sha(shard["payload"].encode()) != shard["digest"]:
            raise ValueError("diagnostic shards differ from native population")
    return wire, cells
