"""Fresh-process adapter reads; no corpus import, fitting, or answer scoring.

Oracle addresses are explicit experimental interventions, never ordinary routing
inputs. Parameter arms are denied SQLite source payload columns. Their memory
values come from checkpoints; exact events and exception authority stay in the
owner. This is a Python research reader, not a native Hepta serving profile.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import resource
import sqlite3
import sys
import time
import zipfile

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from owner import Owner
import routing
from runtime_contract import ENTITIES, OPCODES, ROLES, WORKFLOWS, canonical
from tensor_cell import TensorCell


ARMS = ("learned/parameter", "deterministic/parameter", "oracle/parameter",
        "learned/retrieval", "deterministic/retrieval", "oracle/retrieval",
        "zero/oracle", "headonly/oracle", "joint/oracle")
INPUT_LIMIT = 32 * 1024 * 1024
CHECKPOINT_NAMES = {"semantic", "skill", "router", "joint", "semantic-zero", "skill-zero",
                    "semantic-head-only", "skill-head-only"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate-json-field")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite-json-value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def absolute_existing(value, directory=False):
    require(isinstance(value, str) and Path(value).is_absolute(), "absolute-path-required")
    path = Path(value).resolve(strict=True)
    require(path.is_dir() if directory else path.is_file(), "input-path-kind")
    return path


def address(route):
    require(isinstance(route, dict) and set(route) == {"role", "entity", "workflow"}, "oracle-address-only-fields")
    role = route["role"]
    require(role in ROLES, "unrecognized-route-role")
    for key, needed, size in (("entity", role in ("semantic", "compose"), len(ENTITIES)),
                              ("workflow", role in ("skill", "compose"), len(WORKFLOWS))):
        value = route[key]
        require((type(value) is int and 0 <= value < size) if needed else value is None, "invalid-route-address")
    return dict(route)


def validate(frame):
    require(isinstance(frame, dict) and set(frame) == {
        "model_root", "encoder_sha", "database", "canonical_features_path", "queries", "seed", "arms"}, "reader-request-fields")
    sha = frame["encoder_sha"]
    require(isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), "encoder-sha-required")
    require(type(frame["seed"]) is int and 0 <= frame["seed"] < 2**63, "invalid-study-seed")
    require(isinstance(frame["arms"], list) and frame["arms"] and len(set(frame["arms"])) == len(frame["arms"])
            and all(arm in ARMS for arm in frame["arms"]), "unknown-or-duplicate-arm")
    require(isinstance(frame["queries"], list) and 1 <= len(frame["queries"]) <= 2048, "bounded-query-list-required")
    ids, features = set(), []
    for query in frame["queries"]:
        require(isinstance(query, dict) and set(query) == {"id", "text", "feature", "oracle_route"}, "query-fields-no-targets")
        require(isinstance(query["id"], str) and 0 < len(query["id"].encode()) <= 128
                and query["id"] not in ids, "unique-query-id-required")
        ids.add(query["id"])
        require(isinstance(query["text"], str) and 0 < len(query["text"].encode()) <= 8192, "query-text-bound")
        value = query["feature"]
        require(isinstance(value, list) and len(value) == 384
                and all(type(v) in (int, float) and math.isfinite(v) for v in value), "query-feature-shape")
        value = np.asarray(value, dtype=np.float32)
        require(np.isfinite(value).all(), "query-feature-f32-range")
        features.append(value)
        address(query["oracle_route"])
    return np.stack(features)


def canonical_features(path):
    require(path.stat().st_size <= 1_048_576, "canonical-feature-file-bound")
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        require(sorted(archive.namelist()) == ["semantic.npy", "skill.npy"]
                and all(item.file_size <= 8*384*8+4096 for item in archive.infolist()), "canonical-features-must-exclude-training-data")
    with np.load(path, allow_pickle=False) as archive:
        require(set(archive.files) == {"semantic", "skill"}, "canonical-feature-keys")
        result = {}
        for kind in ("semantic", "skill"):
            value = archive[kind]
            require(value.shape == (8, 384) and value.dtype.kind == "f", "canonical-feature-shape")
            value = value.astype(np.float32)
            require(np.isfinite(value).all(), "nonfinite-canonical-features")
            result[kind] = value.copy()
    return result, {"sha256": digest(raw), "bytes": len(raw), "keys_loaded": sorted(result),
                    "f32_sha256": {kind: digest(value.tobytes()) for kind, value in result.items()}}


class MeasuredCell:
    def __init__(self, cell):
        self.cell = cell
        self.source_ids = cell.source_ids
        self.calls = self.forward_rows = self.wall_ns = 0

    def _call(self, method, features):
        began = time.monotonic_ns()
        try:
            return getattr(self.cell, method)(features)
        finally:
            self.calls += 1
            self.forward_rows += len(features)
            self.wall_ns += time.monotonic_ns()-began

    def predict(self, features):
        return self._call("predict", features)

    def predict_proba(self, features):
        return self._call("predict_proba", features)

    def snapshot(self):
        return {"calls": self.calls, "forward_rows": self.forward_rows, "wall_ns": self.wall_ns}


class Registry:
    def __init__(self, root, encoder_sha):
        self.root, self.encoder_sha = root, encoder_sha
        self.cells, self.identities, self.supports = {}, {}, {}

    def support(self, name):
        require(name in CHECKPOINT_NAMES, "checkpoint-name")
        if name not in self.supports:
            raw = (self.root / name / "manifest.json").read_bytes()
            require(len(raw) <= 512000, "manifest-bound")
            manifest = decode(raw)
            require(manifest["schema"] == "memory-adapter.checkpoint.v1"
                    and manifest["base_encoder_sha"] == self.encoder_sha, "support-manifest-binding")
            ids = manifest["source_ids"]
            require(isinstance(ids, list) and all(isinstance(item, str) and item for item in ids)
                    and ids == sorted(set(ids)), "source-id-inventory")
            self.supports[name] = {"ids": set(ids), "manifest_sha256": digest(raw),
                                   "source_ids_sha256": digest(canonical(ids)), "source_count": len(ids)}
        return self.supports[name]["ids"]

    def get(self, name):
        if name not in self.cells:
            self.support(name)
            began = time.monotonic_ns()
            cell = TensorCell.load(self.root / name, self.encoder_sha)
            require(cell.config.input_dim == 384, "checkpoint-feature-dimension")
            expected = ({"bits": ("binary", 12)} if name.startswith("semantic") else
                        {f"op{i}": ("multiclass", len(OPCODES)) for i in range(4)} if name.startswith("skill") else
                        {"role": ("multiclass", len(ROLES)), "entity": ("multiclass", 9), "workflow": ("multiclass", 9)} if name == "router" else
                        {"bits": ("binary", 12), **{f"op{i}": ("multiclass", len(OPCODES)) for i in range(4)}})
            require({spec.name: (spec.kind, spec.size) for spec in cell.config.outputs} == expected, "checkpoint-output-contract")
            cell.eval()
            self.cells[name] = MeasuredCell(cell)
            self.identities[name] = {"manifest_sha256": self.supports[name]["manifest_sha256"],
                "parameter_sha256": cell.parameter_digest(), "encoder_sha256": cell.base_encoder_sha,
                "parameter_counts": cell.parameter_counts(), "load_wall_ns": time.monotonic_ns()-began,
                "stored_bytes": sum(p.stat().st_size for p in (self.root / name).iterdir() if p.is_file())}
        return self.cells[name]

    def counters(self):
        return {name: cell.snapshot() for name, cell in self.cells.items()}


def difference(after, before):
    return {name: value-before.get(name, 0) for name, value in after.items()}


def model_difference(after, before):
    return {name: delta for name, counts in after.items()
            if (delta := difference(counts, before.get(name, {})))["calls"]}


class JointQuery:
    """One joint prediction per query; two typed views share the same parameters."""
    def __init__(self, joint, feature):
        self.joint, self.feature, self.result = joint, feature, None

    def predict(self):
        if self.result is None:
            self.result = self.joint.predict(self.feature)
        return self.result


class JointPort:
    def __init__(self, query, source_ids):
        self.query, self.source_ids = query, source_ids

    def predict(self, _canonical_features):
        return self.query.predict()


def database_guard(owner, allow_values):
    owner.db.execute("PRAGMA query_only=ON")
    audit = {"source_payload_column_authorizations": 0, "denied_source_payload_reads": 0}

    def authorize(action, table, column, _database, _trigger):
        if action == sqlite3.SQLITE_READ and table == "sources" and column == "payload":
            audit["source_payload_column_authorizations"] += 1
            if not allow_values:
                audit["denied_source_payload_reads"] += 1
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    owner.db.set_authorizer(authorize)
    owner.db.execute("BEGIN")
    return audit


def snapshot_identity(owner):
    # Metadata only: this never hashes the SQLite file, which contains payloads.
    events = owner.db.execute("SELECT entity,sequence,identity FROM events ORDER BY entity,sequence").fetchall()
    exceptions = owner.db.execute("SELECT entity,identity FROM exceptions ORDER BY entity").fetchall()
    return digest(canonical({"sources": owner.identity(), "events": events, "exceptions": exceptions}))


def run(frame):
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    features = validate(frame)
    root = absolute_existing(frame["model_root"], directory=True)
    database = absolute_existing(frame["database"])
    canonical_path = absolute_existing(frame["canonical_features_path"])
    stored_features, feature_identity = canonical_features(canonical_path)
    registry = Registry(root, frame["encoder_sha"])
    selection, selection_identity = None, None
    if any(arm.startswith("learned/") for arm in frame["arms"]):
        raw = (root / "route-selection.json").read_bytes()
        require(len(raw) <= 65536, "route-selection-bound")
        selection = decode(raw)
        require(type(selection["threshold"]) in (int, float) and math.isfinite(selection["threshold"])
                and 0 <= selection["threshold"] <= 1.1 and selection["selection_used_held"] is False, "frozen-route-selection-required")
        selection_identity = {"sha256": digest(raw), "bytes": len(raw), "threshold": selection["threshold"]}
        registry.get("router")
    rows, summaries, common_cut = [], [], None
    for arm in frame["arms"]:
        arm_began = time.monotonic_ns()
        arm_models_before = registry.counters()
        retrieve = arm.endswith("/retrieval")
        policy = arm.split("/")[0] if arm not in ("zero/oracle", "headonly/oracle", "joint/oracle") else "oracle"
        variant = "zero" if arm == "zero/oracle" else "head-only" if arm == "headonly/oracle" else "trained"
        cells = {}
        if arm == "joint/oracle":
            joint = registry.get("joint")
            bindings = {kind: registry.support(kind) for kind in ("semantic", "skill")}
            require(set.union(*bindings.values()) <= joint.source_ids, "joint-fact-lineage-incomplete")
        elif not retrieve:
            cells = {kind: registry.get(kind if variant == "trained" else f"{kind}-{variant}") for kind in ("semantic", "skill")}
        owner = Owner(str(database), cells, stored_features, allow_value_reads=retrieve)
        sql_audit, stopped = {}, None
        try:
            sql_audit = database_guard(owner, retrieve)
            cut = snapshot_identity(owner)
            if common_cut is None:
                common_cut = cut
            require(common_cut == cut, "owner-snapshot-changed-between-arms")
            routing_wall = 0
            for index, query in enumerate(frame["queries"]):
                before, models_before = dict(owner.reads), registry.counters()
                route_began = time.monotonic_ns()
                if policy == "learned":
                    route = routing.learned(registry.get("router"), features[index:index+1], selection["threshold"])[0]
                elif policy == "deterministic":
                    route = routing.deterministic(query["text"])
                else:
                    route = {**address(query["oracle_route"]), "confidence": 1.0}
                route_elapsed = time.monotonic_ns()-route_began
                routing_wall += route_elapsed
                if arm == "joint/oracle" and route["role"] != "compose":
                    result = {"status": "not_applicable", "value": None, "sources": [], "trace": []}
                else:
                    if arm == "joint/oracle":
                        joint_query = JointQuery(joint, features[index:index+1])
                        owner.cells = {kind: JointPort(joint_query, bindings[kind]) for kind in bindings}
                    result = owner.execute(route, max_steps=4)
                rows.append({"query_id": query["id"], "arm": arm, "route": route, "result": result,
                             "skipped": arm == "joint/oracle" and route["role"] != "compose",
                             "reads": difference(owner.reads, before),
                             "model_reads": model_difference(registry.counters(), models_before),
                             "routing_wall_ns": route_elapsed, "oracle_intervention": policy == "oracle"})
            require(snapshot_identity(owner) == cut, "owner-snapshot-changed-within-arm")
            owner.stop()
            before = dict(owner.reads)
            stopped = owner.execute({"role": "unknown", "entity": None, "workflow": None})
            require(stopped["status"] == "owner_stopped" and owner.reads == before, "owner-stop-not-effective")
            require(retrieve or owner.reads["explicit_values"] == 0, "parameter-arm-read-explicit-targets")
            summaries.append({"arm": arm, "route_policy": policy, "value_access": "explicit-retrieval" if retrieve else "parameter-only",
                "owner_snapshot_sha256": cut, "reads": dict(owner.reads), "sql_audit": dict(sql_audit),
                "owner_stop_probe": stopped, "snapshot_metadata_queries": 6,
                "model_reads": model_difference(registry.counters(), arm_models_before),
                "routing_wall_ns": routing_wall, "wall_ns_through_stop": time.monotonic_ns()-arm_began})
        finally:
            owner.stop()
            owner.close()
    forbidden = [name for name in sys.modules if name == "corpus" or name == "train" or name.startswith(("corpus.", "train."))]
    require(not forbidden, "training-data-module-loaded")
    return {"schema": "memory-adapter.fresh-reader.v1", "pid": os.getpid(), "parent_pid": os.getppid(),
        "seed": frame["seed"], "encoder_sha": frame["encoder_sha"], "request_sha256": digest(canonical(frame)),
        "execution_path": "python-adapter-owner", "native_runtime_executed": False, "training_modules_loaded": bool(forbidden),
        "training_module_import_audit": forbidden,
        "canonical_features": feature_identity, "route_selection": selection_identity,
        "modelsha": registry.identities,
        "source_bindings": {name: {k: v for k, v in item.items() if k != "ids"} for name, item in registry.supports.items()},
        "rows": rows, "arms": list(frame["arms"]), "arm_receipts": summaries, "model_reads": registry.counters(),
        "planner": {"algorithm_alias_of": "deterministic/retrieval", "independent_arm": False,
                    "description": "same-information static typed plan from deterministic natural-language addressing and explicit records; oracle/retrieval is the separate address upper bound"},
        "cost": {"wall_ns_before_response": time.monotonic_ns()-started, "cpu_ns_before_response": time.process_time_ns()-cpu,
                 "checkpoint_load_wall_ns": sum(item["load_wall_ns"] for item in registry.identities.values()),
                 "checkpoint_stored_bytes": sum(item["stored_bytes"] for item in registry.identities.values()),
                 "peak_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                 "peak_rss_unit": "bytes" if sys.platform == "darwin" else "KiB",
                 "scope": "sequential arms in one fresh process; shared model loads and nested model/route times are not independent end-to-end arm costs"},
        "boundaries": {"oracle_contains_targets": False, "score_computed": False, "gradient_steps": 0,
                       "text_feature_consistency_verified": False, "encoder_executed_in_reader": False,
                       "source_values_available_only_to_retrieval": True,
                       "canonical_features_are_declared_address_inputs": True}}


def main():
    torch.set_num_threads(1)
    raw = sys.stdin.buffer.read(INPUT_LIMIT+1)
    try:
        require(0 < len(raw) <= INPUT_LIMIT, "request-byte-bound")
        with torch.inference_mode():
            result = run(decode(raw))
        result["request_wire_sha256"] = digest(raw)
        encoded = canonical(result)
        require(len(encoded) <= 32*1024*1024, "response-byte-bound")
        sys.stdout.buffer.write(encoded+b"\n")
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.DatabaseError) as error:
        result = {"schema": "memory-adapter.fresh-reader-error.v1", "pid": os.getpid(),
                  "request_wire_sha256": digest(raw), "error": f"{type(error).__name__}: {error}",
                  "native_runtime_executed": False, "training_executed": False}
        sys.stdout.buffer.write(canonical(result)+b"\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
