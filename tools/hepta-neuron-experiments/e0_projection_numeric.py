"""Independent scalar E0 shadow oracle for frozen f32 Stem -> low-rank Q24.

Recomputes the established stem_projection.py v1 arithmetic. Does not load an
Encoder, invoke a Worker, issue authority or attest source authenticity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import struct
import sys
from pathlib import Path

Q = 1 << 24
LIMIT = 8 * Q
MAX_F32 = 8192
MAX_WIDTH = 512
MAX_RANK = 64
MAX_COEFF = 600_000
P_SCHEMA = "hepta.stem.low-rank-projection.q24.v1"
C_SCHEMA = "hepta.neuron.e0-projection-numeric-trial.v1"
R_SCHEMA = "hepta.neuron.e0-projection-numeric-result.v1"
P_DOMAIN = b"hepta.stem.low-rank-projection.q24.v1"
F_DOMAIN = b"hepta.stem.feature.f32.v1"
B_DOMAIN = b"hepta.stem.projected-feature-bound.v1"
P_FIELDS = {
    "schema", "shadow_only", "production_authorized", "training_lineage_digest",
    "projection_digest", "encoder_digest", "preprocessor_digest", "runtime_digest",
    "normalizer_digest", "representation", "input_width", "output_width", "rank",
    "a_q24", "b_q24", "bias_q24",
}
C_FIELDS = {
    "schema", "source_kind", "feature_file", "feature_file_sha256", "feature_digest",
    "token_count", "projection_manifest", "projection_file_sha256",
    "projection_digest", "source_input_digest", "scope_digest",
    "revocation_frontier_digest", "generation", "head_input_width",
    "expected_output_q24", "projected_input_digest",
}
HEX = frozenset("0123456789abcdef")


class NumericGateError(ValueError):
    pass


def need(test: bool, msg: str) -> None:
    if not test:
        raise NumericGateError(msg)


def sha(value: object, name: str) -> str:
    need(type(value) is str and len(value) == 64 and
         set(value) <= HEX and value != "0" * 64, f"invalid {name}")
    return value


def u64(x: int) -> bytes:
    need(type(x) is int and 0 <= x < 1 << 64, "invalid u64")
    return x.to_bytes(8, "big")


def i64(x: int) -> bytes:
    need(type(x) is int and -(1 << 63) <= x < (1 << 63), "invalid i64")
    return x.to_bytes(8, "big", signed=True)


def field(value: str) -> bytes:
    need(type(value) is str, "invalid identity")
    raw = value.encode("utf-8")
    return u64(len(raw)) + raw


def clean_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def load_obj(data: bytes, expected: set[str]) -> dict:
    try:
        value = json.loads(data, object_pairs_hook=clean_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(NumericGateError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NumericGateError("invalid JSON") from exc
    need(type(value) is dict and set(value) == expected, "unknown/missing JSON fields")
    return value


def read_regular(path: str, max_bytes: int) -> bytes:
    need(type(path) is str and Path(path).is_absolute(), "artifact path must be absolute")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    need(hasattr(os, "O_NOFOLLOW"), "no symlink-safe open on this host")
    flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise NumericGateError("unreadable or symlinked artifact") from exc
    try:
        a = os.fstat(fd)
        need(stat.S_ISREG(a.st_mode) and a.st_nlink == 1, "artifact not an exclusive regular file")
        need(0 < a.st_size <= max_bytes, "artifact exceeds byte bound")
        blocks = []
        remaining = a.st_size
        while remaining:
            block = os.read(fd, min(remaining, 1 << 20))
            need(bool(block), "artifact unexpectedly shortened")
            blocks.append(block)
            remaining -= len(block)
        b = os.fstat(fd)
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        need(all(getattr(a, k) == getattr(b, k) for k in keys), "artifact changed during read")
        return b"".join(blocks)
    finally:
        os.close(fd)


def verified_bytes(path: str, claimed: str, maximum: int) -> bytes:
    sha(claimed, "file SHA256")
    raw = read_regular(path, maximum)
    need(hashlib.sha256(raw).hexdigest() == claimed, "physical artifact SHA256 mismatch")
    return raw


def q24_scalar(x: float) -> int:
    need(math.isfinite(x) and -8.0 <= x <= 8.0, "nonfinite/out-of-range source f32")
    return int(round(x * Q))


def round_q48(acc: int) -> int:
    quotient, remainder = divmod(acc, Q)
    if remainder * 2 > Q or (remainder * 2 == Q and quotient % 2):
        quotient += 1
    need(-LIMIT <= quotient <= LIMIT, "unrepresentable Q24 projected value")
    return quotient


def load_projector(raw: bytes) -> dict:
    obj = load_obj(raw, P_FIELDS)
    need(obj["schema"] == P_SCHEMA and obj["shadow_only"] is True and
         obj["production_authorized"] is False, "invalid shadow projection schema/authority")
    for k in ("encoder_digest", "preprocessor_digest", "runtime_digest",
              "normalizer_digest", "training_lineage_digest", "projection_digest"):
        sha(obj[k], k)
    need(obj["representation"] in ("mean", "landmark8"), "unsupported feature representation")
    iw, ow, rank = (obj[k] for k in ("input_width", "output_width", "rank"))
    need(all(type(x) is int for x in (iw, ow, rank)) and
         1 <= iw <= MAX_F32 and 1 <= ow <= MAX_WIDTH and 1 <= rank <= MAX_RANK,
         "projection width/rank outside registered envelope")
    tensors = (obj["a_q24"], obj["b_q24"], obj["bias_q24"])
    need(all(type(t) is list for t in tensors) and
         [len(t) for t in tensors] == [iw * rank, ow * rank, ow] and
         sum(map(len, tensors)) <= MAX_COEFF, "projection tensor inventory mismatch")
    for t in tensors:
        need(all(type(v) is int and -LIMIT <= v <= LIMIT for v in t),
             "unsafe Q24 projection coefficient")
    h = hashlib.sha256(P_DOMAIN)
    for k in ("encoder_digest", "preprocessor_digest", "runtime_digest",
              "normalizer_digest", "representation"):
        h.update(field(obj[k]))
    for number in (iw, ow, rank):
        h.update(u64(number))
    for tensor in tensors:
        h.update(u64(len(tensor)))
        for value in tensor:
            h.update(i64(value))
    need(h.hexdigest() == obj["projection_digest"], "projection tensor semantic digest mismatch")
    return obj


def calculate(contract_path: Path) -> dict:
    # This consumes real physical bytes; it cannot attest they originated from a model.
    con = load_obj(read_regular(str(contract_path.absolute()), 200_000), C_FIELDS)
    need(con["schema"] == C_SCHEMA and con["source_kind"] == "local_f32_capture_untrusted",
         "invalid numeric trial schema/source posture")
    for k in ("feature_file_sha256", "feature_digest", "projection_file_sha256",
              "projection_digest", "source_input_digest", "scope_digest",
              "revocation_frontier_digest", "projected_input_digest"):
        sha(con[k], k)
    token_count = con["token_count"]
    generation = con["generation"]
    need(type(token_count) is int and 1 <= token_count <= 1_000_000, "invalid source token count")
    need(type(generation) is int and 1 <= generation < (1 << 64), "invalid generation")
    projector_raw = verified_bytes(
        con["projection_manifest"], con["projection_file_sha256"], 22_000_000)
    projector = load_projector(projector_raw)
    need(projector["projection_digest"] == con["projection_digest"], "projection revision mismatch")
    need(type(con["head_input_width"]) is int and
         con["head_input_width"] == projector["output_width"], "Head width mismatch")
    feature_raw = verified_bytes(
        con["feature_file"], con["feature_file_sha256"], MAX_F32 * 4)
    width = projector["input_width"]
    # A 768-D claim implemented by zero-padding a copied 256-D prefix is
    # indistinguishable from clipping on shape checks alone. Require at least
    # one nonzero rank path from a tail source coordinate to a live output
    # coordinate. This is only structural sensitivity, not proof of quality.
    tail_paths = 0
    if width > projector["output_width"]:
        for k in range(projector["rank"]):
            a = projector["a_q24"]
            b = projector["b_q24"]
            active_tail = any(a[k * width + j] != 0
                              for j in range(projector["output_width"], width))
            active_output = any(b[i * projector["rank"] + k] != 0
                                for i in range(projector["output_width"]))
            tail_paths += int(active_tail and active_output)
        need(tail_paths > 0, "projection ignores entire source tail (implicit slice)")
    need(len(feature_raw) == width * 4, "source f32 width mismatch (no truncation)")
    feats = struct.unpack(f">{width}f", feature_raw)
    original = [q24_scalar(v) for v in feats]
    hf = hashlib.sha256(F_DOMAIN)
    hf.update(u64(width))
    hf.update(feature_raw)
    hf.update(u64(token_count))
    hf.update(projector["representation"].encode("ascii"))
    need(hf.hexdigest() == con["feature_digest"], "source feature semantic digest mismatch")
    hidden = []
    for k in range(projector["rank"]):
        off = k * width
        hidden.append(round_q48(sum(
            original[j] * projector["a_q24"][off + j] for j in range(width))))
    computed = []
    for k in range(projector["output_width"]):
        off = k * projector["rank"]
        acc = projector["bias_q24"][k] * Q
        acc += sum(hidden[j] * projector["b_q24"][off + j]
                   for j in range(projector["rank"]))
        computed.append(round_q48(acc))
    claimed = con["expected_output_q24"]
    need(type(claimed) is list and len(claimed) == projector["output_width"] and
         all(type(v) is int and -LIMIT <= v <= LIMIT for v in claimed),
         "invalid projected Q24 vector envelope")
    need(claimed == computed, "projected Q24 numerical mismatch (possible implicit slice)")
    bound = hashlib.sha256(B_DOMAIN)
    for value in (con["scope_digest"], con["revocation_frontier_digest"],
                  projector["encoder_digest"], projector["preprocessor_digest"],
                  projector["runtime_digest"], con["source_input_digest"],
                  con["feature_digest"], con["projection_digest"]):
        bound.update(field(value))
    bound.update(u64(generation))
    bound.update(u64(len(computed)))
    for value in computed:
        bound.update(i64(value))
    need(bound.hexdigest() == con["projected_input_digest"], "scoped projected-input binding mismatch")
    # Catch persistent source/manifest changes while the computation was in flight.
    need(verified_bytes(con["feature_file"], con["feature_file_sha256"], MAX_F32*4) == feature_raw,
         "source changed after numeric calculation")
    need(verified_bytes(con["projection_manifest"], con["projection_file_sha256"], 22_000_000) == projector_raw,
         "projection manifest changed after numeric calculation")
    return {
        "schema": R_SCHEMA, "source_feature_sha256": con["feature_file_sha256"],
        "source_feature_digest": con["feature_digest"],
        "projection_sha256": con["projection_file_sha256"],
        "projection_digest": con["projection_digest"],
        "projected_input_digest": con["projected_input_digest"],
        "input_width": width, "output_width": len(computed),
        "rank": projector["rank"], "active_source_tail_rank_paths": tail_paths,
        "reference_multiply_add_terms": projector["rank"] * (
            width + projector["output_width"]),
        "computed_q24_sha256": hashlib.sha256(
            b"".join(i64(v) for v in computed)).hexdigest(),
        "numeric_oracle_agrees": True, "non_authorizing": True,
        "encoder_actually_invoked": False, "stem_projection_operator_executed": False,
        "neuron_worker_invoked": False, "neuron_checkpoint_committed": False,
        "independent_outcome_proven": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trial", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    try:
        report = calculate(args.trial)
        with args.out.open("x", encoding="utf-8") as f:
            json.dump(report, f, sort_keys=True, indent=2)
            f.write("\n")
        return 0
    except (NumericGateError, OSError, ValueError) as exc:
        print(f"FAIL_HEPTA_E0_NUMERIC_PROJECTION: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
