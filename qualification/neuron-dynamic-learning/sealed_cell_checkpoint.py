"""Immutable, exact-float64 shadow Cell Head snapshot and read-only replay.

This serializes the *complete* Cell-local trainable state, not a seed, sampled
prediction, or rounded Q24 digest. A SHA256-bound canonical JSON payload and
independently reconstructed Rust Q24 candidate identity must both match.
It is not an origin signature, CAS ownership grant, model approval or FinalUse.
No pickle, NumPy np.load, external reference resolution or code execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

import numpy as np

SCHEMA = "hepta.stem.sealed-local-cell-pair.shadow.v1"
MAX_BYTES = 180_000
MAX_PARAMETERS = 16_384
ARRAY_FIELDS = ("down", "up", "gate_bias", "cell_state", "drive_weights",
                "prediction_weights")
SCALAR_FIELDS = ("drive_bias", "prediction_bias")
HEAD_FIELDS = frozenset(("cell_id", "encoder_digest", "width", "groups", "rank",
                         "parameter_count", "q24_candidate_digest", "arrays", "scalars"))
PAYLOAD_FIELDS = frozenset(("schema", "source_panel_digest", "model_revision",
                            "pipeline_digest", "scope_id", "purpose_id",
                            "generation", "authority_epoch", "seed", "steps",
                            "frozen", "trained", "selected_artifact_mutation",
                            "production_promotion", "independent_origin_attested"))


class CheckpointError(ValueError):
    """Malformed or unbound immutable shadow Head snapshot."""


def _hex_digest(value: object, length: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{%d}" % length, value))


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_id(value: object) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 128 and
            bool(re.fullmatch(r"[A-Za-z0-9._:-]+", value)))


def _dimensions(width: int, groups: int, rank: int) -> dict[str, tuple[int, ...]]:
    if (type(width) is not int or width != 256 or type(groups) is not int or
            not 1 <= groups <= 64 or type(rank) is not int or not 1 <= rank <= 32):
        raise CheckpointError("only registered 256d bounded Cell Head profile allowed")
    return {"down": (rank, width), "up": (groups, rank),
            "gate_bias": (groups,), "cell_state": (groups,),
            "drive_weights": (width,), "prediction_weights": (width,)}


def _float_hex(value: float) -> str:
    x = float(value)
    if not math.isfinite(x) or abs(x) > 8:
        raise CheckpointError("nonfinite or out-of-bounds Cell scalar")
    return x.hex()


def _from_float_hex(value: object) -> float:
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(
        r"-?0x[0-9a-f]+(?:\.[0-9a-f]+)?p[+-][0-9]+", value):
        raise CheckpointError("invalid exact float64 hexadecimal representation")
    try:
        x = float.fromhex(value)
    except (ValueError, OverflowError) as exc:
        raise CheckpointError("unparseable Cell float64") from exc
    if not math.isfinite(x) or abs(x) > 8 or x.hex() != value:
        raise CheckpointError("nonnormal/corrupt Cell float64")
    return x


def _serialized_head(cell) -> dict:
    from cell_learning import rust_candidate_digest
    dimensions = _dimensions(cell.width, cell.groups, cell.rank)
    if (not _safe_id(cell.cell_id) or not _hex_digest(cell.encoder_digest, 64) or
            cell.encoder_digest == "0" * 64):
        raise CheckpointError("unbound source/Cell identity")
    count = cell.parameter_count()
    expected_count = sum(math.prod(dims) for dims in dimensions.values()) + 2
    if (type(count) is not int or count != expected_count or
            count > MAX_PARAMETERS):
        raise CheckpointError("Cell parameter count mismatch")
    arrays = {}
    for name, shape in dimensions.items():
        raw = np.asarray(getattr(cell, name), dtype=np.float64)
        if raw.shape != shape or not np.isfinite(raw).all() or np.any(np.abs(raw) > 8):
            raise CheckpointError("Cell tensor shape or finite bound mismatch")
        arrays[name] = [_float_hex(x) for x in raw.reshape(-1)]
    scalars = {name: _float_hex(getattr(cell, name)) for name in SCALAR_FIELDS}
    digest = rust_candidate_digest(cell.export_q24())
    if not _hex_digest(digest, 64):
        raise CheckpointError("invalid Rust Q24 candidate identity")
    return {"cell_id": cell.cell_id, "encoder_digest": cell.encoder_digest,
            "width": cell.width, "groups": cell.groups, "rank": cell.rank,
            "parameter_count": count, "q24_candidate_digest": digest,
            "arrays": arrays, "scalars": scalars}


def _validate_head(head: object) -> dict:
    if not isinstance(head, dict) or set(head) != HEAD_FIELDS:
        raise CheckpointError("missing or extra Head tensor fields")
    dims = _dimensions(head["width"], head["groups"], head["rank"])
    if (not _safe_id(head["cell_id"]) or not _hex_digest(head["encoder_digest"], 64)
            or head["encoder_digest"] == "0" * 64 or
            not _hex_digest(head["q24_candidate_digest"], 64)):
        raise CheckpointError("Head identity not bound")
    if (type(head["parameter_count"]) is not int or
            head["parameter_count"] != sum(math.prod(s) for s in dims.values()) + 2 or
            head["parameter_count"] > MAX_PARAMETERS):
        raise CheckpointError("Head capacity exceeded")
    if (not isinstance(head["arrays"], dict) or set(head["arrays"]) != set(ARRAY_FIELDS)
            or not isinstance(head["scalars"], dict) or
            set(head["scalars"]) != set(SCALAR_FIELDS)):
        raise CheckpointError("missing expected Cell tensor or bias")
    restored = {}
    for name, shape in dims.items():
        flattened = head["arrays"][name]
        if not isinstance(flattened, list) or len(flattened) != math.prod(shape):
            raise CheckpointError("tensor element count mismatch")
        restored[name] = np.asarray([_from_float_hex(x) for x in flattened],
                                    dtype=np.float64).reshape(shape)
    restored.update({name: _from_float_hex(head["scalars"][name])
                     for name in SCALAR_FIELDS})
    return restored


def _validate_payload(payload: object, *, source_panel_digest: str,
                      model_revision: str, pipeline_digest: str,
                      scope_id: str, purpose_id: str, generation: int,
                      authority_epoch: int) -> None:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        raise CheckpointError("wrong version or incomplete Head bundle")
    if (payload["schema"] != SCHEMA or payload["source_panel_digest"] != source_panel_digest
            or payload["model_revision"] != model_revision or
            payload["pipeline_digest"] != pipeline_digest or
            payload["scope_id"] != scope_id or payload["purpose_id"] != purpose_id
            or payload["generation"] != generation
            or payload["authority_epoch"] != authority_epoch
            or any(not _hex_digest(payload[x], y) for x, y in (
                ("source_panel_digest", 64), ("model_revision", 40),
                ("pipeline_digest", 64))) or
            not _safe_id(scope_id) or not _safe_id(purpose_id) or
            type(payload["generation"]) is not int or payload["generation"] < 1 or
            type(payload["authority_epoch"]) is not int or payload["authority_epoch"] < 1 or
            type(payload["steps"]) is not int or not 1 <= payload["steps"] <= 1000 or
            type(payload["seed"]) is not int or not 0 <= payload["seed"] < 2**32 or
            payload["selected_artifact_mutation"] is not False or
            payload["production_promotion"] != "DENY_ALL" or
            payload["independent_origin_attested"] is not False):
        raise CheckpointError("Head snapshot identity or permission mismatch")
    f, t = payload["frozen"], payload["trained"]
    _validate_head(f)
    _validate_head(t)
    if (f["cell_id"] != t["cell_id"] or
            f["encoder_digest"] != pipeline_digest or
            t["encoder_digest"] != pipeline_digest or
            any(f[x] != t[x] for x in ("width", "groups", "rank", "parameter_count")) or
            f["q24_candidate_digest"] == t["q24_candidate_digest"]):
        raise CheckpointError("frozen/trained candidates share no valid lineage")


def _restore_head(item: dict):
    from cell_learning import DynamicCell, rust_candidate_digest
    values = _validate_head(item)
    obj = DynamicCell(
        cell_id=item["cell_id"], encoder_digest=item["encoder_digest"],
        width=item["width"], groups=item["groups"], rank=item["rank"],
        **values,
    )
    if obj.parameter_count() != item["parameter_count"] or (
            rust_candidate_digest(obj.export_q24()) != item["q24_candidate_digest"]):
        raise CheckpointError("restored exact float64 weights disagree with Q24 digest")
    # An evaluation-only view blocks the public SGD interface, not just
    # accidentally writable tensor buffers. This is still shadow Python code.
    for name in ARRAY_FIELDS:
        getattr(obj, name).setflags(write=False)
    return _EvalOnlyCell(obj)


class _EvalOnlyCell:
    def __init__(self, cell):
        self._cell = cell

    def predict(self, features):
        return self._cell.predict(features)

    def export_q24(self):
        return self._cell.export_q24()

    def parameter_count(self):
        return self._cell.parameter_count()

    def learn(self, *args, **kwargs):
        raise CheckpointError("replayed snapshot is immutable; learning forbidden")


def seal_checkpoint(path: Path, frozen, trained, *, source_panel_digest: str,
                    model_revision: str, pipeline_digest: str,
                    scope_id: str, purpose_id: str, generation: int,
                    authority_epoch: int, steps: int, seed: int) -> dict:
    """Create one immutable snapshot file with O_EXCL, then re-read it before use."""
    payload = {
        "schema": SCHEMA, "source_panel_digest": source_panel_digest,
        "model_revision": model_revision, "pipeline_digest": pipeline_digest,
        "scope_id": scope_id, "purpose_id": purpose_id,
        "generation": generation, "authority_epoch": authority_epoch,
        "steps": steps, "seed": seed,
        "frozen": _serialized_head(frozen), "trained": _serialized_head(trained),
        "selected_artifact_mutation": False, "production_promotion": "DENY_ALL",
        "independent_origin_attested": False,
    }
    _validate_payload(payload, source_panel_digest=source_panel_digest,
                      model_revision=model_revision, pipeline_digest=pipeline_digest,
                      scope_id=scope_id, purpose_id=purpose_id,
                      generation=generation, authority_epoch=authority_epoch)
    body = {"payload": payload, "payload_sha256": _sha(_canonical(payload))}
    data = _canonical(body)
    if len(data) > MAX_BYTES:
        raise CheckpointError("snapshot exceeds admitted bytes")
    path = Path(path)
    if (path.suffix != ".json" or not path.parent.is_dir() or
            path.parent.is_symlink() or path.exists() or path.is_symlink()):
        raise CheckpointError("checkpoint requires fresh local .json destination")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    restored = load_checkpoint(path, source_panel_digest=source_panel_digest,
                               model_revision=model_revision, pipeline_digest=pipeline_digest,
                               scope_id=scope_id, purpose_id=purpose_id,
                      generation=generation, authority_epoch=authority_epoch)
    if _serialized_head(restored["frozen"]._cell) != payload["frozen"] or (
            _serialized_head(restored["trained"]._cell) != payload["trained"]):
        raise CheckpointError("exact float64 tensor roundtrip mismatch")
    return restored["receipt"]


def load_checkpoint(path: Path, *, source_panel_digest: str,
                    model_revision: str, pipeline_digest: str,
                    scope_id: str, purpose_id: str, generation: int,
                    authority_epoch: int) -> dict:
    """Read only an exact source/scope/epoch-bound shadow Head snapshot."""
    path = Path(path)
    if (not path.is_file() or path.is_symlink() or
            not 0 < path.stat().st_size <= MAX_BYTES):
        raise CheckpointError("missing, linked or oversized snapshot")
    raw = path.read_bytes()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CheckpointError("unparseable checkpoint JSON") from exc
    if (not isinstance(body, dict) or set(body) != {"payload", "payload_sha256"}
            or raw != _canonical(body) or
            not _hex_digest(body["payload_sha256"], 64) or
            body["payload_sha256"] != _sha(_canonical(body["payload"]))):
        raise CheckpointError("noncanonical or changed checkpoint bytes")
    payload = body["payload"]
    _validate_payload(payload, source_panel_digest=source_panel_digest,
                      model_revision=model_revision, pipeline_digest=pipeline_digest,
                      scope_id=scope_id, purpose_id=purpose_id,
                      generation=generation, authority_epoch=authority_epoch)
    frozen = _restore_head(payload["frozen"])
    trained = _restore_head(payload["trained"])
    return {"frozen": frozen, "trained": trained, "receipt": {
        "schema": "hepta.stem.sealed-local-cell-replay-receipt.shadow.v1",
        "snapshot_file_sha256": _sha(raw),
        "snapshot_payload_sha256": body["payload_sha256"],
        "training_source_panel_digest": source_panel_digest,
        "revision": model_revision,
        "encoder_digest": pipeline_digest,
        "frozen_head_digest": payload["frozen"]["q24_candidate_digest"],
        "trained_head_digest": payload["trained"]["q24_candidate_digest"],
        "trainable_parameters": payload["trained"]["parameter_count"],
        "training_steps": payload["steps"],
        "frozen_weights_exact_float64_reloaded": True,
        "trained_weights_exact_float64_reloaded": True,
        "independent_origin_authenticated": False,
        "historical_20261014_head_byte_identity_claimed": False,
        "production_promotion": "DENY_ALL",
    }}
