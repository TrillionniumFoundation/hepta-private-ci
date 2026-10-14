"""Stable bounded IO and data schemas shared by producer and independent evaluator.

This file does not import or execute the training fit stage.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from multimodal_bridge import ContractError, ModalityFeature

SCHEMA = "hepta.stem-alignment.v1"
MAX_ROWS = 2048
MAX_FILE_BYTES = 64 * 1024 * 1024

def canonical(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ContractError("duplicate JSON key")
        out[key] = value
    return out


def load_pinned_jsonl(path: Path, expected_sha: str) -> tuple[list[dict], str]:
    if (type(expected_sha) is not str or len(expected_sha) != 64 or
            any(c not in "0123456789abcdef" for c in expected_sha)):
        raise ContractError("canonical source file SHA-256 required")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ContractError("unsafe, missing or oversized source file")
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES or not raw or sha(raw) != expected_sha:
        raise ContractError("unpinned or changed source")
    lines = raw.splitlines()
    if not 1 <= len(lines) <= MAX_ROWS:
        raise ContractError("out-of-range example count")
    records = []
    for line in lines:
        if not line or len(line) > 262144:
            raise ContractError("empty or oversized example")
        try:
            item = json.loads(line, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ContractError("nonfinite JSON")))
            canonical(item)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ContractError("malformed source row") from exc
        if type(item) is not dict:
            raise ContractError("source row must be an object")
        records.append(item)
    return records, expected_sha


def write_new(path: Path, item: object) -> str:
    raw = canonical(item)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)



def _text(value, name, maximum=128) -> str:
    if type(value) is not str or not 1 <= len(value.encode()) <= maximum:
        raise ContractError("missing or invalid " + name)
    return value


def parse_feature(raw: dict) -> ModalityFeature:
    if type(raw) is not dict or set(raw) != {"modality", "input_sha256", "encoder_sha256", "values"}:
        raise ContractError("feature fields inconsistent")
    if type(raw["values"]) is not list:
        raise ContractError("feature vector list required")
    return ModalityFeature.from_vector(raw["modality"], raw["input_sha256"],
                                       raw["encoder_sha256"], tuple(raw["values"]))


@dataclass(frozen=True)
class SourceRow:
    case_id: str
    group_id: str
    scope: str
    observed_at: int
    source: ModalityFeature


def parse_source(raw: dict, *, paired: bool) -> tuple[SourceRow, ModalityFeature | None]:
    exact = {"case_id", "group_id", "scope", "observed_at", "source", "split"}
    if paired:
        exact.add("target")
    if set(raw) != exact or raw["split"] != ("train" if paired else "future"):
        raise ContractError("wrong data phase: train is paired; inference has source only")
    for key in ("case_id", "group_id", "scope"):
        _text(raw[key], key)
    t = raw["observed_at"]
    if type(t) is not int or not 0 <= t < 2**63:
        raise ContractError("bounded observed_at required")
    source = parse_feature(raw["source"])
    target = parse_feature(raw["target"]) if paired else None
    if source.modality == "text":
        raise ContractError("cross-modal source must not be text")
    if target is not None and target.modality != "text":
        raise ContractError("target must be text stem feature")
    return SourceRow(raw["case_id"], raw["group_id"], raw["scope"], t, source), target


def _metadata(rows: list[SourceRow]) -> dict:
    if not rows or len(rows) > MAX_ROWS:
        raise ContractError("no bounded rows")
    keys = [r.case_id for r in rows]
    if len(keys) != len(set(keys)):
        raise ContractError("duplicate case id")
    return {"group_hashes": sorted({sha(r.group_id.encode()) for r in rows}),
            "source_input_sha256s": sorted({r.source.input_sha256 for r in rows}),
            "max_observed_at": max(r.observed_at for r in rows),
            "scope": rows[0].scope,
            "source_encoder_sha256": rows[0].source.encoder_sha256,
            "modality": rows[0].source.modality}



def load_pinned_document(path: Path, expected_sha: str) -> dict:
    # Bound only one canonical JSON document (not JSONL), pin bytes before parsing.
    if (type(expected_sha) is not str or len(expected_sha) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha)
            or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES):
        raise ContractError("invalid artifact identity or path")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_FILE_BYTES or sha(raw) != expected_sha:
        raise ContractError("unpinned artifact bytes")
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ContractError("nonfinite JSON")))
        if type(parsed) is not dict or canonical(parsed) != raw:
            raise ContractError("noncanonical document bytes")
        return parsed
    except (ValueError, TypeError, OverflowError) as exc:
        raise ContractError("malformed document") from exc

