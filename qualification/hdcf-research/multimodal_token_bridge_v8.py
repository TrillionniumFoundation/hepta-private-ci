"""Bounded multimodal token feature -> existing HDCF frozen-feature-bank V1.

RESEARCH_ONLY / SHADOW_ONLY / DENY_ALL.  Accepts *externally calculated*
384-wide frozen tokens. Does NOT execute or validate real pretrained encoders,
learn a cross-modal representation, generate media, issue inference grants or
certify that two modalities are semantically aligned.

The bridge intentionally keeps the V1 vector request unchanged: the derived
single Q24 feature vector is a LOSING/COMPRESSED research baseline, and the
original token, region and timeline evidence stays in the source bundle.
"""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import math
import struct
from typing import Any, Callable

SCHEMA = "hepta.hdcf.multimodal-token-bank.v8"
OUTPUT_SCHEMA = "hepta.hdcf.frozen-feature-bank.v1"
MODALITIES = ("text", "image", "audio", "video")
WIDTH = 384
Q24 = 1 << 24
MAX_BYTES = 4_000_000
MAX_TOKENS = 8
MAX_FIT = 512
MAX_HELD = 256
MAX_FANOUT = 4096


class Denied(ValueError):
    """Fail-closed input or scope admission; never an authorization signal."""


def require(predicate: bool, reason: str) -> None:
    if not predicate:
        raise Denied(reason)


def exact(value: Any, names: set[str]) -> None:
    require(type(value) is dict and set(value) == names, "unknown/missing fields")


def name(value: Any) -> None:
    require(type(value) is str and 1 <= len(value) <= 128 and
            value.isascii() and not any(c.isspace() for c in value), "invalid name")


def sha(value: Any) -> None:
    require(type(value) is str and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value), "invalid SHA256")


def integer(value: Any, low: int, high: int) -> None:
    require(type(value) is int and low <= value <= high, "invalid integer")


def canonical(value: Any) -> bytes:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("ascii")
    except (ValueError, TypeError, UnicodeError) as error:
        raise Denied("noncanonical document") from error
    require(len(raw) <= MAX_BYTES, "document too large")
    return raw


def identity(value: Any, domain: bytes) -> str:
    return hashlib.sha256(domain + b"\0" + canonical(value)).hexdigest()


def token_bytes_sha256(vectors: Any) -> str:
    """Bind canonical little-endian FP32 values, NOT an attested model producer.

    Input numbers are serialized to IEEE binary32 first, then replayed in that
    precision for deterministic Q24 conversion. NaNs/infs and overflow fail.
    """
    require(type(vectors) is list and 1 <= len(vectors) <= MAX_TOKENS,
            "invalid token count")
    payload = bytearray(struct.pack("<II", len(vectors), WIDTH))
    for row in vectors:
        require(type(row) is list and len(row) == WIDTH, "invalid token width")
        for n in row:
            require(type(n) in (float, int) and math.isfinite(n) and abs(n) <= 8,
                    "nonfinite/out-of-range token")
            try:
                b = struct.pack("<f", n)
            except (OverflowError, struct.error) as error:
                raise Denied("non-f32 token") from error
            require(math.isfinite(struct.unpack("<f", b)[0]), "invalid f32 value")
            payload.extend(b)
    return hashlib.sha256(b"hepta.hdcf.tokens.fp32.v8\0" + payload).hexdigest()


def _read_tokens(span: dict[str, Any]) -> tuple[tuple[float, ...], ...]:
    token_bytes_sha256(span["vectors"])
    return tuple(tuple(struct.unpack("<f", struct.pack("<f", v))[0]
                       for v in vector) for vector in span["vectors"])


def _validate_span(span: Any, modality_encoders: dict[str, str],
                   modality_preprocessors: dict[str, str]) -> None:
    exact(span, {"kind", "asset_sha256", "encoder_sha256", "preprocess_sha256",
                 "tokens_sha256", "time_ms", "vectors"})
    kind = span["kind"]
    require(type(kind) is str and kind in MODALITIES, "unknown modality")
    for field in ("asset_sha256", "encoder_sha256", "preprocess_sha256", "tokens_sha256"):
        sha(span[field])
    require(span["encoder_sha256"] == modality_encoders[kind] and
            span["preprocess_sha256"] == modality_preprocessors[kind],
            "wrong modality model/preprocess identity")
    require(span["tokens_sha256"] == token_bytes_sha256(span["vectors"]),
            "features differ from bound FP32 bytes")
    times = span["time_ms"]
    require(type(times) is list, "missing chronology")
    if kind in ("audio", "video"):
        require(len(span["vectors"]) >= 2 and len(times) == len(span["vectors"]),
                "temporal token census mismatch")
        for time in times:
            integer(time, 0, 3_600_000)
        require(all(a < b for a, b in zip(times, times[1:])),
                "nonmonotonic temporal sampling")
    else:
        require(times == [], "non-temporal span has a timeline")


def validate_bank(bank: Any) -> None:
    """Validate the *entire* bundle before writing any derived data.

    Enforces disjoint event/asset IDs and source family splits; this cannot
    authenticate an original publisher or prevent semantic duplicates.
    """
    exact(bank, {"schema", "producer", "dimension", "types", "fit", "held"})
    require(bank["schema"] == SCHEMA, "wrong multimodal schema")
    integer(bank["dimension"], WIDTH, WIDTH)
    types = bank["types"]
    require(type(types) is list and len(types) == 2 and types[0] != types[1],
            "requires exactly two cell categories")
    for typ in types:
        name(typ)
    producer = bank["producer"]
    exact(producer, {"principal", "purpose", "generation", "epoch", "source_sha256",
                     "encoders", "preprocessors", "topology"})
    for field in ("principal", "purpose"):
        name(producer[field])
    for field in ("generation", "epoch"):
        integer(producer[field], 1, 2**63 - 1)
    sha(producer["source_sha256"])
    require(producer["topology"] in ("separate_frozen_frontends", "shared_transformer"),
            "unknown topology")
    for field in ("encoders", "preprocessors"):
        table = producer[field]
        exact(table, set(MODALITIES))
        for mod in MODALITIES:
            sha(table[mod])
    ids: set[str] = set()
    events: set[str] = set()
    assets: set[str] = set()
    groups: dict[str, set[str]] = {"fit": set(), "held": set()}
    classes = {(typ, t): 0 for typ in types for t in (0, 1)}
    for split, low, high in (("fit", 8, MAX_FIT), ("held", 4, MAX_HELD)):
        rows = bank[split]
        require(type(rows) is list and low <= len(rows) <= high, "invalid split size")
        observed_types = set()
        for row in rows:
            fields = {"id", "family", "type", "event_sha256", "modalities"}
            exact(row, fields | ({"target"} if split == "fit" else set()))
            name(row["id"])
            name(row["family"])
            require(type(row["type"]) is str and row["type"] in types,
                    "unregistered cell type")
            sha(row["event_sha256"])
            require(row["id"] not in ids and row["event_sha256"] not in events,
                    "duplicate case/event across partitions")
            ids.add(row["id"])
            events.add(row["event_sha256"])
            observed_types.add(row["type"])
            groups[split].add(row["family"])
            if split == "fit":
                integer(row["target"], 0, 1)
                classes[(row["type"], row["target"])] += 1
            spans = row["modalities"]
            require(type(spans) is list and 1 <= len(spans) <= len(MODALITIES),
                    "invalid modality census")
            for span in spans:
                _validate_span(span, producer["encoders"], producer["preprocessors"])
            kinds = [span["kind"] for span in spans]
            require(kinds == sorted(kinds) and len(set(kinds)) == len(spans),
                    "duplicate or noncanonical modalities")
            for span in spans:
                require(span["asset_sha256"] not in assets, "reused asset across cases")
                assets.add(span["asset_sha256"])
        require(observed_types == set(types), "missing cell type in partition")
    require(not (groups["fit"] & groups["held"]), "source-family leakage")
    require(all(count > 0 for count in classes.values()),
            "each cell type needs both fit classes")
    # Include every FP32 token and source identity in the bounded canonical frame.
    canonical(bank)


def _pool(span: dict[str, Any]) -> tuple[float, ...]:
    vectors = _read_tokens(span)
    n = len(vectors)
    out: list[float] = []
    temporal = span["kind"] in ("audio", "video")
    for j in range(WIDTH):
        mean = sum(v[j] for v in vectors) / n
        # Signed endpoint contrast preserves elementary direction information.
        # This is NOT full video understanding or a trained temporal network.
        contrast = (vectors[-1][j] - vectors[0][j]) * 0.5 if temporal else 0.0
        value = 0.75 * mean + 0.25 * contrast if temporal else mean
        out.append(value)
    return tuple(out)


def pool_row(row: dict[str, Any], *, ablate_kind: str | None = None) -> tuple[float, ...]:
    if ablate_kind is not None:
        require(ablate_kind in MODALITIES, "unknown ablation")
    require(type(row) is dict and type(row.get("modalities")) is list,
            "invalid row for pooling")
    admitted = [span for span in row["modalities"] if span["kind"] != ablate_kind]
    require(admitted, "ablation eliminates all observations")
    for span in admitted:
        require(type(span) is dict and span.get("tokens_sha256") ==
                token_bytes_sha256(span["vectors"]), "unbound pooled token bytes")
    pooled = [_pool(span) for span in admitted]
    out = []
    for j in range(WIDTH):
        value = sum(features[j] for features in pooled) / len(pooled)
        q = round(value * Q24)  # nearest, ties-to-even in Python
        require(-8 * Q24 <= q <= 8 * Q24, "Q24 output range")
        out.append(q / Q24)
    return tuple(out)


def to_physical_bank(bank: dict[str, Any], *, ablate_kind: str | None = None) -> dict:
    """Emit V1 training input, intentionally no held labels or original raw media.

    The output is suitable for physical_bank.validate_bundle/train, not for
    independently attested provenance or source-authorized production use.
    """
    validate_bank(bank)
    prod = bank["producer"]
    producer = {
        "encoder_sha256": identity(prod["encoders"], b"hepta.hdcf.encoder-tuple.v8"),
        "preprocess_sha256": identity(prod["preprocessors"], b"hepta.hdcf.preprocess-tuple.v8"),
        "source_sha256": prod["source_sha256"],
        "generation": prod["generation"],
        "principal": prod["principal"],
    }
    result: dict[str, Any] = {"schema": OUTPUT_SCHEMA, "producer": producer,
                               "dimension": WIDTH, "types": list(bank["types"]),
                               "fit": [], "held": []}
    for split in ("fit", "held"):
        for row in bank[split]:
            case = {"id": row["id"], "family": row["family"], "type": row["type"],
                    "vector": list(pool_row(row, ablate_kind=ablate_kind))}
            if split == "fit":
                case["target"] = row["target"]
            result[split].append(case)
    canonical(result)
    return result


@dataclass(frozen=True)
class Scope:
    principal: str
    purpose: str
    generation: int
    epoch: int
    bundle_digest: str


class SharedFeatureFanout:
    """Immutable borrowed features, re-authorized on every access.

    This is a Python research simulation of fan-out, NOT a production cache,
    a worker zero-copy proof, a grant or a secure cross-principal boundary.
    """
    def __init__(self, bank: dict[str, Any], *, ablate_kind: str | None = None):
        validate_bank(bank)
        producer = bank["producer"]
        self.scope = Scope(producer["principal"], producer["purpose"],
                           producer["generation"], producer["epoch"],
                           identity(bank, b"hepta.hdcf.multimodal-bank.v8"))
        self._features: dict[str, tuple[float, ...]] = {}
        # Snapshot source bytes; externally mutating a supplied dict must not
        # mutate future borrowed features or bypass source digest admission.
        self._rows = {r["id"]: copy.deepcopy(r) for split in ("fit", "held")
                      for r in bank[split]}
        self.ablate_kind = ablate_kind
        self.borrow_count = 0
        self.pool_count = 0
        self.seen: dict[str, set[str]] = {}

    def borrow(self, case_id: str, cell_id: str, *, scope: Scope,
               admit: Callable[[Scope, str, str], bool]) -> tuple[float, ...]:
        name(case_id)
        name(cell_id)
        require(scope == self.scope and type(scope) is Scope,
                "cross-scope or stale generation")
        require(case_id in self._rows, "unknown source case")
        require(callable(admit) and admit(scope, case_id, cell_id) is True,
                "current use not admitted")
        cells = self.seen.setdefault(case_id, set())
        require(cell_id in cells or len(cells) < MAX_FANOUT,
                "too many logical borrowers")
        if case_id not in self._features:
            self._features[case_id] = pool_row(self._rows[case_id],
                                               ablate_kind=self.ablate_kind)
            self.pool_count += 1  # feature pooling, NOT pretrained model forwards
        cells.add(cell_id)
        self.borrow_count += 1
        return self._features[case_id]


def main(argv: list[str] | None = None) -> int:
    """Convert to the *existing* physically trained HDCF CellBank V1 interface.

    Conversion is not a forward pass, alignment proof, or trusted provenance.
    The parent physical_cli owner supplies bounded file handling and create-only
    writes. Keep raw feature banks private; never upload them in workflow logs.
    """
    import argparse
    from physical_cli import read_document, write_once

    parser = argparse.ArgumentParser(description="RESEARCH_ONLY multimodal Q24 bridge")
    parser.add_argument("--features", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ablate", choices=MODALITIES)
    args = parser.parse_args(argv)
    try:
        converted = to_physical_bank(read_document(args.features), ablate_kind=args.ablate)
        write_once(args.out, converted)
    except (Denied, OSError) as error:
        parser.exit(2, f"DENY_ALL: {type(error).__name__}: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
