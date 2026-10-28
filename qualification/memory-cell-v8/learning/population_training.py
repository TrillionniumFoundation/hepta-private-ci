"""V3 candidate fits from a bounded completed access trace and owner export.

All shards are freshly trained. This module neither authorizes the supplied
trace nor publishes or selects an artifact. The host retains the owner snapshot,
the actual completed request/readout receipts, and the prospective task lock.
"""

from copy import deepcopy
import sys
import time

from native_export import export_cell
from population_training import configuration
from training import AssociativeCell, KINDS, canonical, current_rows, sha
from learning.allocation import PARTITION, learn_routes


SCHEMA = "hepta.memory.population.native.v3"


def process_peak_rss_bytes():
    """Fresh-process HWM observed now; final serialization/exit can peak later."""
    if sys.platform not in {"linux", "darwin"}:
        return None
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value) * (1024 if sys.platform == "linux" else 1)


def fit_kind(rows, kind, config, trace):
    addresses = sorted(sha(row["record"]["entity"].encode()) for row in rows)
    routes, routing_receipt = learn_routes(addresses, config["shard_count"], trace)
    shards, originals, reports = [], [], []
    for index in range(config["shard_count"]):
        selected = [row for row in rows if routes[sha(row["record"]["entity"].encode())] == index]
        width = config["total_hidden"] // config["shard_count"] + int(index < config["total_hidden"] % config["shard_count"])
        cell = AssociativeCell.fit([row["record"]["entity"] for row in selected],
            [row["record"]["value"] for row in selected], (config["seed"] + index) % 2**32,
            kind=kind, support_ids=[[row["source_id"]] for row in selected], hidden=width,
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
        "shards": shards, "routes": routes, "lineage_sources": lineage, "routing_trace": trace})
    return {"native": native.decode(), "originals": originals}, {
        "native_digest": sha(native), "shards": reports, "routing": routing_receipt,
        "serialized_bytes": len(native), "raw_payload_bytes": sum(len(shard["payload"].encode()) for shard in shards),
        "route_bytes": len(canonical(routes)), "routing_trace_bytes": len(canonical(trace)),
        "lineage_bytes": len(canonical(lineage)),
        "resident_parameters_bytes": sum(report["parameter_bytes"] for report in reports),
        "catalog_bytes": sum(report["catalog_bytes"] for report in reports),
    }


def train_populations(export, configuration_value, trace):
    config = configuration(configuration_value)
    rows = current_rows(export)
    if not isinstance(trace, dict) or trace.get("source_cut_digest") != export["owner_cut_digest"]:
        raise ValueError("routing trace belongs to a different owner cut")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    artifacts, reports = {}, {}
    for kind in KINDS:
        artifacts[kind], reports[kind] = fit_kind(rows[kind], kind, config, trace)
    return {"schema": "hepta.memory.population-training-result.v3", "scope": export["scope"],
        "owner_cut_digest": export["owner_cut_digest"], "configuration": config,
        "artifacts": artifacts, "receipt": {"types": reports,
            "fit_calls": len(KINDS) * config["shard_count"],
            "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
            "process_peak_rss_bytes": process_peak_rss_bytes(),
            "source_export_bytes": len(canonical(export)), "source_ledger_bytes": None,
            "partition_uses_memory_values": False, "routing_trace_digest": trace["trace_digest"],
            "routing_prefix_end_sequence": trace["prefix_end_sequence"],
            "independent_future_task_evaluation": False,
            "clean_parameters": True, "language_model_finetuning": False, "authority": False}}
