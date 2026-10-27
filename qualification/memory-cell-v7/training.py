"""Fit bounded parameter candidates from a real owner's serialized export.

An export is evidence, never authority. The Rust host keeps its opaque SQLite
snapshot and revalidates the live cut before accepting these candidate bytes.
Training diagnostics and softmax thresholds are not independent task outcomes.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT.parent / "memory-cell-v6"))

from native_export import export_cell
from v6.cells import AssociativeCell, canonical
from v6.values import validate_typed_value


KINDS = ("semantic", "procedure")
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require_digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value) or int(value, 16) == 0:
        raise ValueError("nonzero canonical digest required")


def current_rows(export):
    fields = {"schema", "owner_agent_id", "scope", "owner_cut_digest", "observed_at_unix_seconds", "records", "withdrawn_addresses", "current_source_ids"}
    if not isinstance(export, dict) or set(export) != fields or export["schema"] != "hepta.memory.owner-snapshot.v1":
        raise ValueError("invalid owner snapshot export")
    require_digest(export["owner_cut_digest"])
    for field in ("owner_agent_id", "scope"):
        if not isinstance(export[field], str) or not 0 < len(export[field].encode()) <= 128:
            raise ValueError("invalid owner identity or scope")
    now = export["observed_at_unix_seconds"]
    if type(now) is not int or not 0 <= now < 2**53:
        raise ValueError("invalid owner observation time")
    if not isinstance(export["records"], list) or not 1 <= len(export["records"]) <= 512:
        raise ValueError("bounded owner records required")
    records, addresses = {}, set()
    for row in export["records"]:
        if not isinstance(row, dict) or set(row) != {"source_id", "owner_memory_id", "revision", "record"}:
            raise ValueError("invalid source record")
        source, record = row["source_id"], row["record"]
        require_digest(source)
        if source in records or type(row["revision"]) is not int or row["revision"] < 1:
            raise ValueError("duplicate source or invalid revision")
        if not isinstance(record, dict) or set(record) != {"schema", "entity", "kind", "effective_at", "value"} or record["schema"] != "hepta.memory.cell-record.v1":
            raise ValueError("invalid typed record")
        entity, effective = record["entity"], record["effective_at"]
        if not isinstance(entity, str) or not 0 < len(entity.encode()) <= 128 or any(ord(c) < 32 for c in entity) or type(effective) is not int or not 0 <= effective < 2**53:
            raise ValueError("invalid typed address")
        validate_typed_value(record["kind"], record["value"])
        address = (entity, record["kind"], effective)
        if address in addresses:
            raise ValueError("duplicate current address head")
        addresses.add(address)
        records[source] = row
    withdrawn = export["withdrawn_addresses"]
    if not isinstance(withdrawn, list) or len(withdrawn) > 512:
        raise ValueError("withdrawn address bound")
    tombstones = set()
    for address in withdrawn:
        if not isinstance(address, dict) or set(address) != {"entity", "kind", "effective_at"} or address["kind"] not in (*KINDS, "event") or not isinstance(address["entity"], str) or type(address["effective_at"]) is not int:
            raise ValueError("invalid withdrawn address")
        key = (address["entity"], address["kind"], address["effective_at"])
        if key in tombstones or key in addresses:
            raise ValueError("duplicate or live withdrawn address")
        tombstones.add(key)
    heads = {}
    for source, row in records.items():
        record = row["record"]
        key = (record["entity"], record["kind"])
        if record["effective_at"] <= now and (key not in heads or record["effective_at"] > heads[key][0]):
            heads[key] = (record["effective_at"], source)
    expected = {source for (entity, kind), (effective, source) in heads.items() if not any(e == entity and k == kind and effective <= t <= now for e, k, t in tombstones)}
    current = export["current_source_ids"]
    if not isinstance(current, list) or len(current) != len(set(current)) or set(current) != expected:
        raise ValueError("exported current heads disagree with tombstones or time")
    return {kind: sorted([records[source] for source in expected if records[source]["record"]["kind"] == kind], key=lambda row: row["record"]["entity"]) for kind in KINDS}


def configuration(value):
    if not isinstance(value, dict) or set(value) != {"mode", "seed", "steps", "dimension", "hidden", "threshold"} or value["mode"] not in {"clean", "replay"}:
        raise ValueError("invalid training configuration")
    for name, low, high in (("seed", 0, 2**32 - 1), ("steps", 1, 1000), ("dimension", 8, 256), ("hidden", 1, 128)):
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError("training budget exceeded")
    if type(value["threshold"]) not in (float, int) or not np.isfinite(value["threshold"]) or not 0 <= value["threshold"] <= 1:
        raise ValueError("invalid fixed acceptance threshold")
    return deepcopy(value)


def train(frame):
    if not isinstance(frame, dict) or set(frame) != {"schema", "export", "configuration", "parents"} or frame["schema"] != "hepta.memory.training-request.v1":
        raise ValueError("invalid training request")
    config = configuration(frame["configuration"])
    rows = current_rows(frame["export"])
    parents = frame["parents"]
    if not isinstance(parents, dict) or (config["mode"] == "clean" and parents) or (config["mode"] == "replay" and set(parents) != set(KINDS)):
        raise ValueError("clean rebuild must not consume parent parameters")
    started, cpu = time.perf_counter(), time.process_time()
    artifacts, reports = {}, {}
    for kind in KINDS:
        current = rows[kind]
        if not current:
            raise ValueError("each trained type requires current owner sources")
        keys = [row["record"]["entity"] for row in current]
        values = [row["record"]["value"] for row in current]
        sources = [[row["source_id"]] for row in current]
        parent = None
        if config["mode"] == "replay":
            item = parents[kind]
            if not isinstance(item, dict) or set(item) != {"payload", "native_digest"} or not isinstance(item["payload"], str):
                raise ValueError("invalid pinned parent")
            require_digest(item["native_digest"])
            raw = item["payload"].encode()
            if sha(export_cell(raw)) != item["native_digest"]:
                raise ValueError("parent differs from the selected native model")
            parent = AssociativeCell.from_bytes(raw)
            if parent.kind != kind or parent.dimension != config["dimension"] or not set(parent.lineage_sources) <= {source[0] for source in sources}:
                raise ValueError("withdrawn or superseded parameter ancestry requires clean rebuild")
        cell = AssociativeCell.fit(keys, values, config["seed"], kind=kind, support_ids=sources, hidden=config["hidden"], dimension=config["dimension"], steps=config["steps"], parent=parent)
        cell.threshold = float(config["threshold"])
        original = cell.to_bytes()
        native = export_cell(original)
        readbacks = [cell.read(key) for key in keys]
        reports[kind] = {
            "training": deepcopy(cell.training_receipt),
            "current_source_ids": [source[0] for source in sources],
            "native_digest": sha(native),
            "original_digest": sha(original),
            "parameter_digest": cell.parameters_digest(),
            "original_bytes": len(original),
            "native_bytes": len(native),
            "numeric_parameter_bytes": sum(array.nbytes for array in (cell.A, cell.a, cell.B, cell.b)),
            "catalog_bytes": len(canonical(cell.catalog)),
            "written_address_diagnostic": {"rows": len(keys), "correct": sum(read["abstain"] is None and read["value"] == value for read, value in zip(readbacks, values))},
            "independent_future_task_evaluation": False,
        }
        artifacts[kind] = {"original": original.decode(), "native": native.decode()}
    return {
        "schema": "hepta.memory.training-result.v1",
        "scope": frame["export"]["scope"],
        "owner_cut_digest": frame["export"]["owner_cut_digest"],
        "request_digest": sha(canonical(frame)),
        "configuration": config,
        "artifacts": artifacts,
        "receipt": {"schema": "hepta.memory.training-receipt.v1", "mode": config["mode"], "types": reports, "wall_seconds": time.perf_counter() - started, "cpu_seconds": time.process_time() - cpu, "fit_calls": 2, "source_export_bytes": len(canonical(frame["export"])), "fixed_threshold": config["threshold"], "calibration_population_risk_established": False, "catalog_contains_explicit_values": True, "language_model_finetuning": False, "authority": False},
    }


def decode_unique(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
