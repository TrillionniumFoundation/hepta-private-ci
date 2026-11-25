#!/usr/bin/env python3
"""Pinned sufficient-statistic model, admission, and durable node state."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import time
import zlib

MODEL_SHA = "9880293805ec22e1b9b990e37c0927a4a788e8be988d353af669ea0906342be6"
NODES = ("pocket4", "ai395")
FILES = ("sufficient.py", "stream_peer.py", "ssh_runner.py")


def encode(value):
    return json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encode(value))


def sources():
    root = Path(__file__).parent
    return {name: sha((root / name).read_bytes()) for name in FILES}


def load_model(path):
    if sha(Path(path).read_bytes()) != MODEL_SHA:
        raise ValueError("Frozen model source identity mismatch")
    spec = importlib.util.spec_from_file_location("pft_frozen_model", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def durable(path, raw):
    start = time.perf_counter()
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    written = time.perf_counter() - start
    start = time.perf_counter()
    if path.read_bytes() != raw:
        raise ValueError("Durable artifact readback mismatch")
    return written, time.perf_counter() - start


def synthetic(model, node, size, seed):
    parent, truth = model.model(size, seed)
    index = NODES.index(node)
    rng = random.Random(seed * 65537 + size * 17 + index)
    batches, feature_seconds, gb_seconds = [], 0.0, 0.0
    for batch in range(4):
        tick = time.perf_counter()
        count = max(6, size // 4) + batch * 2
        x = [[rng.gauss(0, 2.0 if j % 2 == index else 0.15) for j in range(size)] for _ in range(count)]
        y = [sum(a * b for a, b in zip(row, truth)) + rng.gauss(0, 0.05) for row in x]
        residual = [target - sum(a * b for a, b in zip(row, parent)) for row, target in zip(x, y)]
        data_hash = digest([x, y])
        feature_seconds += time.perf_counter() - tick
        tick = time.perf_counter()
        gram = [[sum(row[i] * row[j] for row in x) for j in range(size)] for i in range(size)]
        moment = [sum(row[i] * value for row, value in zip(x, residual)) for i in range(size)]
        gb_seconds += time.perf_counter() - tick
        batches.append({"batch": batch, "count": count, "data_hash": data_hash, "gram": gram, "moment": moment})
    return {"record_kind": "pft_local_sufficient_statistics", "schema_version": 1,
            "node": node, "dimension": size, "seed": seed, "parent": parent,
            "coordinates_sha256": digest(["identity", size]),
            "objective": {"ridge": 0.01, "loss": "half_sum_squared_residual"},
            "feature_provider_sha256": MODEL_SHA, "shared_capsule_sha256": digest([parent, "synthetic"]),
            "batches": batches, "timings": {"data_feature_seconds": feature_seconds, "gb_seconds": gb_seconds},
            "evidence": {"kind": "controlled_non_iid_linear_system", "local_generation": True}}


def message_id(message, header):
    return digest([header, message["node"], message["batch"], message["data_hash"]])


def signed_message(body):
    value = dict(body)
    value["payload_hash"] = digest(value)
    return value


class State:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.model = load_model(args.model)
        self.folder = Path(args.root) / args.round_id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.ledger = self.folder / "ledger.json"
        self.source = sources()
        self.restored = 0
        self.previous_pid = None
        self.frozen = False
        self.metrics = {key: 0.0 for key in ("data_feature_seconds", "gb_seconds", "admission_seconds",
                        "checkpoint_write_seconds", "checkpoint_readback_seconds", "restore_read_seconds",
                        "solve_seconds", "encode_seconds", "decode_seconds", "pipe_write_seconds",
                        "pipe_read_wait_seconds", "fault_wait_seconds", "ssh_start_seconds")}
        self.metrics.update({"tx_bytes": 0, "rx_bytes": 0, "packets": [], "statuses": {}})
        if args.resume:
            tick = time.perf_counter()
            raw = self.ledger.read_bytes()
            value = json.loads(raw)
            body = value["body"]
            if digest(body) != value["sha256"] or body["sources"] != self.source:
                raise ValueError("Checkpoint identity or integrity mismatch")
            if body["node"] != args.node or body["round_id"] != args.round_id:
                raise ValueError("Checkpoint belongs to another node or round")
            if body.get("frozen"):
                raise ValueError("Published or solved rounds cannot resume as mutable state")
            self.header, self.artifact, self.messages = body["header"], body["artifact"], body["messages"]
            self.validate_artifact(self.artifact)
            if self.header != self.expected_header(self.artifact):
                raise ValueError("Checkpoint boundary must match the actual fixed artifact")
            restored_messages = self.messages
            self.messages = {}
            for message in restored_messages.values():
                if self._admit(message) != "accepted":
                    raise ValueError("Invalid contribution in checkpoint")
            self.metrics = body["metrics"]
            self.metrics["restore_read_seconds"] += time.perf_counter() - tick
            self.restored, self.restore_sha, self.previous_pid = len(self.messages), sha(raw), body["pid"]
        else:
            if self.ledger.exists():
                raise ValueError("Fresh round must not overwrite an existing ledger")
            artifact = json.loads(Path(args.external).read_text()) if args.external else synthetic(self.model, args.node, args.size, args.seed)
            self.artifact = {k: v for k, v in artifact.items() if k != "batches"}
            self.validate_artifact(artifact)
            self.header = self.expected_header(artifact)
            self.messages = {}
            for key in ("data_feature_seconds", "gb_seconds"):
                value = artifact["timings"][key]
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Invalid local stage timing")
                self.metrics[key] = value
            for batch in artifact["batches"]:
                body = {**self.header, **batch, "node": args.node}
                body["id"] = message_id(body, self.header)
                status = self.accept(signed_message(body), persist=False)
                if status != "accepted":
                    raise ValueError("Local artifact rejected: " + status)
            if len(self.messages) != 4:
                raise ValueError("This experiment requires four local batches")
            self.persist()
        self.own = sorted((m for m in self.messages.values() if m["node"] == args.node), key=lambda m: m["batch"])

    def validate_artifact(self, artifact):
        if artifact.get("record_kind") != "pft_local_sufficient_statistics" or artifact.get("schema_version") != 1:
            raise ValueError("Unsupported local artifact schema")
        if artifact["node"] != self.args.node or type(artifact["dimension"]) is not int or artifact["dimension"] != self.args.size or type(artifact["seed"]) is not int or artifact["seed"] != self.args.seed:
            raise ValueError("Local artifact identity mismatch")
        parent = artifact["parent"]
        if not isinstance(parent, list) or len(parent) != self.args.size or any(type(x) not in (int, float) or not math.isfinite(x) for x in parent):
            raise ValueError("Invalid fixed parent")
        ridge = artifact["objective"]["ridge"]
        if artifact["objective"]["loss"] != "half_sum_squared_residual" or type(ridge) not in (int, float) or not math.isfinite(ridge) or ridge <= 0:
            raise ValueError("Unsupported objective")

    def expected_header(self, artifact):
        return {"parent": digest(artifact["parent"]), "coordinates": artifact["coordinates_sha256"],
                "objective": digest([artifact["objective"], artifact["feature_provider_sha256"], artifact["shared_capsule_sha256"]]),
                "protocol": "pft2-ssh-stream-v2", "sources": digest(self.source), "round_id": self.args.round_id}

    def persist(self):
        body = {"sources": self.source, "node": self.args.node, "round_id": self.args.round_id, "pid": os.getpid(),
                "header": self.header, "artifact": self.artifact, "messages": self.messages, "metrics": self.metrics,
                "frozen": self.frozen, "solution": getattr(self, "solution", None)}
        raw = encode({"body": body, "sha256": digest(body)}) + b"\n"
        write, read = durable(self.ledger, raw)
        self.metrics["checkpoint_write_seconds"] += write
        self.metrics["checkpoint_readback_seconds"] += read
        return sha(raw)

    def accept(self, message, persist=True):
        if self.frozen:
            return "rejected_finalized"
        tick = time.perf_counter()
        status = self._admit(message)
        self.metrics["admission_seconds"] += time.perf_counter() - tick
        self.metrics["statuses"][status] = self.metrics["statuses"].get(status, 0) + 1
        if status == "accepted" and persist:
            self.persist()
        return status

    def _admit(self, m):
        if any(m.get(k) != v for k, v in self.header.items()) or m.get("node") not in NODES:
            return "rejected_version"
        if type(m.get("batch")) is not int or not 0 <= m["batch"] < 4 or type(m.get("count")) is not int or m["count"] < 1:
            return "rejected_schema"
        if m.get("id") != message_id(m, self.header) or m.get("payload_hash") != digest({k: v for k, v in m.items() if k != "payload_hash"}):
            return "rejected_integrity"
        if m["id"] in self.messages:
            return "duplicate" if self.messages[m["id"]]["payload_hash"] == m["payload_hash"] else "rejected_conflict"
        if any(old["node"] == m["node"] and old["batch"] == m["batch"] for old in self.messages.values()):
            return "rejected_batch_conflict"
        if any(old["data_hash"] == m["data_hash"] for old in self.messages.values()):
            return "rejected_duplicate_data"
        n, g, b = self.args.size, m.get("gram"), m.get("moment")
        if not isinstance(g, list) or len(g) != n or any(not isinstance(row, list) or len(row) != n for row in g) or not isinstance(b, list) or len(b) != n:
            return "rejected_dimension"
        if any(type(v) not in (int, float) or not math.isfinite(v) for row in g for v in row) or any(type(v) not in (int, float) or not math.isfinite(v) for v in b):
            return "rejected_nonfinite"
        scale = max(1.0, max(abs(v) for row in g for v in row))
        if max(abs(g[i][j] - g[j][i]) for i in range(n) for j in range(n)) > 1e-12 * scale:
            return "rejected_asymmetry"
        try:
            self.model.solve(g, [0.0] * n, ridge=1e-10 * scale)
        except (ValueError, ZeroDivisionError):
            return "rejected_non_psd"
        self.messages[m["id"]] = m
        return "accepted"

    def solve(self):
        if self.frozen:
            raise ValueError("A frozen candidate cannot be solved again")
        if len(self.messages) != 8:
            raise ValueError("Cannot solve an incomplete contribution set")
        tick = time.perf_counter()
        gram, moment = self.model.totals(list(self.messages.values()), self.args.size)
        ridge = self.artifact["objective"]["ridge"]
        action = self.model.solve(gram, moment, ridge=ridge)
        candidate = [p + a for p, a in zip(self.artifact["parent"], action)]
        residual = [sum(row[j] * action[j] for j in range(len(action))) + ridge * action[i] - moment[i] for i, row in enumerate(gram)]
        self.solution = {"action": action, "candidate": candidate, "candidate_sha256": digest(candidate),
                         "candidate_grid_sha256": digest([round(v * 1e10) for v in candidate]), "quantization_step": 1e-10,
                         "aggregate_sha256": digest([gram, moment]), "normal_residual_l2": math.sqrt(sum(v * v for v in residual)),
                         "relative_normal_residual": math.sqrt(sum(v * v for v in residual)) / max(1.0, math.sqrt(sum(v * v for v in moment)))}
        self.metrics["solve_seconds"] += time.perf_counter() - tick
        self.frozen = True
        self.frozen_messages_sha = digest(self.messages)
        return json.loads(encode(self.solution))

    def finish(self, extra):
        if not self.frozen or digest(self.messages) != self.frozen_messages_sha:
            raise ValueError("Finalization requires the unchanged frozen contribution set")
        self.persist()
        stats = encode({"header": self.header, "artifact": self.artifact, "messages": list(self.messages.values())})
        stats_raw = zlib.compress(stats, 9)
        write, read = durable(self.folder / "stats.json.zlib", stats_raw)
        self.metrics["checkpoint_write_seconds"] += write
        self.metrics["checkpoint_readback_seconds"] += read
        result = {"node": self.args.node, "pid": os.getpid(), "round_id": self.args.round_id,
                  "size": self.args.size, "seed": self.args.seed, "sources": self.source, "model_source_sha256": MODEL_SHA,
                  "header": self.header, "solution": self.solution, "restored_contributions": self.restored,
                  "previous_pid": self.previous_pid, "restore_ledger_sha256": getattr(self, "restore_sha", None),
                  "metrics": self.metrics, "own_data_hashes": [m["data_hash"] for m in self.own],
                  "stats_sha256": sha(stats_raw), "stats_bytes": len(stats_raw), "accepted_ids": sorted(self.messages),
                  "process_wall_seconds": time.monotonic() - self.started, **extra}
        raw = encode(result) + b"\n"
        final_write, final_read = durable(self.folder / "result.json", raw)
        durable(self.folder / "terminal_receipt.json", encode({"node": self.args.node, "pid": os.getpid(),
                "round_id": self.args.round_id, "result_sha256": sha(raw), "result_bytes": len(raw),
                "result_write_seconds": final_write, "result_readback_seconds": final_read,
                "process_wall_to_result_readback_seconds": time.monotonic() - self.started}) + b"\n")
        return result
