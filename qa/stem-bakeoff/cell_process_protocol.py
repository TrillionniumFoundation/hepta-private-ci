"""Bounded local-process messages; byte pins provide integrity, not authentication.

Only pooled float32 FeatureBundles cross this research transport. Pickle is not
used for requests/results. The spawning host and its worker code are trusted.
"""

import base64
from dataclasses import asdict, dataclass, fields
import json
import re

import numpy as np
import torch

from cell_evolution_snapshot import digest
from cell_head_training import _json_bytes
from feature_bundle import FeatureBundleV1, FeatureIdentityV1

MAX_WIRE_BYTES = 1024 * 1024
MAX_ROWS = 128
SCHEMA = "hepta.local-cell-message.v1"


class ProcessInferenceError(ValueError):
    pass


def exact_keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ProcessInferenceError("unexpected message fields")


def sha(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProcessInferenceError("invalid digest pin")
    return value


@dataclass(frozen=True)
class SnapshotPinsV1:
    snapshot_sha256: str
    graph_generation: int
    feature_identity: dict
    source_closure_sha256: str
    frontier_sha256: str
    frontier_epoch: int
    heads: list
    router_artifact_sha256: str | None

    def validate(self):
        for value in (self.snapshot_sha256, self.source_closure_sha256, self.frontier_sha256):
            sha(value)
        if self.router_artifact_sha256 is not None:
            sha(self.router_artifact_sha256)
        FeatureIdentityV1(**self.feature_identity)
        if (type(self.graph_generation) is not int or not 1 <= self.graph_generation < 2**63
                or type(self.frontier_epoch) is not int or not 0 <= self.frontier_epoch < 2**64
                or type(self.heads) is not list or not 1 <= len(self.heads) <= 2):
            raise ProcessInferenceError("unbounded snapshot pins")
        ids = []
        for head in self.heads:
            exact_keys(head, ("cell_id", "manifest_sha256", "tensor_sha256", "model_generation"))
            if (type(head["cell_id"]) is not str
                    or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", head["cell_id"]) is None
                    or type(head["model_generation"]) is not int
                    or not 1 <= head["model_generation"] < 2**63):
                raise ProcessInferenceError("invalid Head pin")
            sha(head["manifest_sha256"])
            sha(head["tensor_sha256"])
            ids.append(head["cell_id"])
        if ids != sorted(set(ids)):
            raise ProcessInferenceError("duplicate or unordered Head pins")


def snapshot_pins(snapshot, frontier):
    report = snapshot.report
    bindings = {b["cell_id"]: b for b in report["cell_bindings"]}
    return SnapshotPinsV1(snapshot.manifest_sha256, snapshot.generation,
        asdict(snapshot.identity), digest(report["source_closure"]), digest(asdict(frontier)),
        frontier.epoch, [{"cell_id": h["cell_id"], "manifest_sha256": h["manifest_sha256"],
            "tensor_sha256": bindings[h["cell_id"]]["head_tensor_sha256"],
            "model_generation": h["model_generation"]} for h in report["heads"]],
        report["router"]["manifest_sha256"] if report["router"] else None)


@dataclass(frozen=True)
class ProcessMessageV1:
    kind: str
    request_id: str
    sequence: int
    worker_index: int
    generation: int
    pins: SnapshotPinsV1
    payload: dict

    def encode(self):
        if (self.kind not in ("load", "ready", "infer", "result", "error")
                or type(self.request_id) is not str
                or re.fullmatch(r"[0-9a-f]{32}:[01]:[0-9]{1,19}", self.request_id) is None
                or type(self.sequence) is not int or not 0 <= self.sequence < 2**63
                or type(self.worker_index) is not int or not 0 <= self.worker_index <= 1
                or type(self.pins) is not SnapshotPinsV1
                or type(self.generation) is not int or self.generation != self.pins.graph_generation
                or type(self.payload) is not dict):
            raise ProcessInferenceError("invalid typed process message")
        if self.request_id.split(":")[1:] != [str(self.worker_index), str(self.sequence)]:
            raise ProcessInferenceError("request ID/sequence binding mismatch")
        self.pins.validate()
        data = _json_bytes({"schema": SCHEMA, **asdict(self)})
        if not 0 < len(data) <= MAX_WIRE_BYTES:
            raise ProcessInferenceError("message exceeds byte budget")
        return data

    @classmethod
    def decode(cls, data):
        if type(data) is not bytes or not 0 < len(data) <= MAX_WIRE_BYTES:
            raise ProcessInferenceError("message exceeds byte budget")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ProcessInferenceError("duplicate JSON field")
                result[key] = value
            return result
        try:
            value = json.loads(data, object_pairs_hook=unique)
            exact_keys(value, {f.name for f in fields(cls)} | {"schema"})
            if value.pop("schema") != SCHEMA:
                raise ProcessInferenceError("message schema mismatch")
            exact_keys(value["pins"], {f.name for f in fields(SnapshotPinsV1)})
            value["pins"] = SnapshotPinsV1(**value["pins"])
            message = cls(**value)
            message.encode()
            return message
        except (TypeError, ValueError, KeyError, UnicodeError, RecursionError) as exc:
            raise ProcessInferenceError("invalid bounded process message") from exc


def match_response(response, request, kind):
    if (response.kind != kind or response.request_id != request.request_id
            or response.sequence != request.sequence or response.worker_index != request.worker_index
            or response.generation != request.generation or response.pins != request.pins):
        raise ProcessInferenceError("worker response does not match owner-held request pins")


def _decode_array(value, dtype, shape):
    size = int(np.prod(shape)) * np.dtype(dtype).itemsize
    if type(value) is not str or len(value) != 4 * ((size + 2) // 3) or size > MAX_WIRE_BYTES:
        raise ProcessInferenceError("unbounded tensor message")
    raw = base64.b64decode(value, validate=True)
    if len(raw) != size:
        raise ProcessInferenceError("tensor payload length mismatch")
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


def feature_payload(bundle):
    bundle.verify_integrity()
    views = bundle.snapshot()
    features = views["global_features"]
    if (set(views) != {"global_features", "missing_mask"} or features.dtype != torch.float32
            or not 1 <= len(features) <= MAX_ROWS):
        raise ProcessInferenceError("transport requires bounded pooled float32 features")
    return {"bundle_sha256": bundle.bundle_digest, "source_record_digests": list(bundle.source_record_digests),
        "global_shape": list(features.shape),
        "global_f32": base64.b64encode(features.numpy().astype("<f4").tobytes()).decode(),
        "missing_bool": base64.b64encode(views["missing_mask"].numpy().tobytes()).decode()}


def read_features(payload, identity):
    exact_keys(payload, ("bundle_sha256", "source_record_digests", "global_shape", "global_f32", "missing_bool"))
    shape = payload["global_shape"]
    if (type(shape) is not list or len(shape) != 2 or any(type(v) is not int for v in shape)
            or not 1 <= shape[0] <= MAX_ROWS or not 1 <= shape[1] <= 4096
            or type(payload["source_record_digests"]) is not list):
        raise ProcessInferenceError("invalid feature message shape")
    values = _decode_array(payload["global_f32"], "<f4", shape)
    mask = _decode_array(payload["missing_bool"], "u1", (shape[0], 5))
    if (mask > 1).any():
        raise ProcessInferenceError("noncanonical boolean bytes")
    bundle = FeatureBundleV1.from_tensors(global_features=torch.from_numpy(values), identity=identity,
        source_record_digests=tuple(payload["source_record_digests"]), missing_mask=torch.from_numpy(mask.astype(bool)))
    if bundle.bundle_digest != sha(payload["bundle_sha256"]):
        raise ProcessInferenceError("feature bytes do not match the owner pin")
    return bundle


def probabilities_payload(probabilities):
    return base64.b64encode(probabilities.detach().double().numpy().astype("<f8").tobytes()).decode()


def read_probabilities(payload, rows, classes):
    result = torch.from_numpy(_decode_array(payload, "<f8", (rows, classes)))
    if (not torch.isfinite(result).all() or (result < 0).any()
            or not torch.allclose(result.sum(1), torch.ones(rows, dtype=torch.float64), atol=1e-5)):
        raise ProcessInferenceError("invalid worker probabilities")
    return result
