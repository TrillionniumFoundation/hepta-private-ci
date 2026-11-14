#!/usr/bin/env python3
"""Cross-language shadow receipt envelope and golden-vector exporter.

This module is deliberately independent of provider/model clients.  It turns
the deterministic Python System-2 shadow event into a versioned envelope that
can be consumed by a Rust control plane or another implementation.  The
envelope is a qualification artifact, not an authorization to dispatch a
model call.

The digest uses ``canonical-json-v1``:

* UTF-8 JSON with sorted object keys and compact separators;
* arrays retain their order;
* finite floats are rendered as fixed-point decimal strings with 12 places for
  digest input (the wire payload still carries JSON numbers);
* the ``integrity`` member is omitted while calculating ``event_digest``.

Normalizing floats for the digest avoids a byte-level dependency on the
number printer of a particular language while keeping the readable payload
numeric.  Implementations should reject non-finite numbers before hashing.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ndu_system2_orchestrator import CANDIDATES, run as orchestrator_run


SCHEMA_ID = "urn:hepta:ndu:shadow-event:1"
SCHEMA_VERSION = 1
EVENT_TYPE = "ndu.system2.shadow_event"
CANONICALIZATION = "canonical-json-v1"
DIGEST_ALGORITHM = "sha256"
MODE = "SHADOW_ONLY"
AUTHORITY = "DENY_ALL"
HEX_DIGEST_LENGTH = 64


class ReceiptSchemaError(ValueError):
    """The envelope is malformed, unsupported, or has a bad digest."""


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_string(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != HEX_DIGEST_LENGTH:
        raise ReceiptSchemaError(f"{label} must be a 64-character SHA-256 digest")
    if any(char not in "0123456789abcdef" for char in value):
        raise ReceiptSchemaError(f"{label} must be lowercase hexadecimal")
    return value


def _normalize_for_digest(value: Any) -> Any:
    """Project a JSON value to a language-neutral digest representation."""

    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReceiptSchemaError("non-finite numbers cannot be hashed")
        # Avoid two spellings for negative zero.
        return "0.000000000000" if value == 0.0 else f"{value:.12f}"
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_for_digest(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_for_digest(item) for item in value]
    raise ReceiptSchemaError(f"unsupported value in digest input: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return canonical-json-v1 text for digest input."""

    normalized = _normalize_for_digest(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_digest(envelope_without_integrity: Mapping[str, Any]) -> str:
    """Hash an envelope after ensuring the integrity member is absent."""

    body = copy.deepcopy(dict(envelope_without_integrity))
    body.pop("integrity", None)
    return _digest(canonical_json(body).encode("utf-8"))


def _protocol() -> Dict[str, Any]:
    return {
        "mode": MODE,
        "authority": AUTHORITY,
        "provider_dispatch": False,
        "real_model_call": False,
        "artifact_selection": False,
        "learned_fbsde": False,
    }


def _payload_from_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    required = (
        "prompt_state",
        "portfolio",
        "tree",
        "cell",
        "receipts",
        "delayed_outcome",
        "outcome",
        "ope",
        "budget",
        "candidate_snapshot_digest",
    )
    missing = [key for key in required if key not in event]
    if missing:
        raise ReceiptSchemaError(f"orchestrator event missing fields: {', '.join(missing)}")
    return {key: copy.deepcopy(event[key]) for key in required}


def build_event(seed: int = 17, source_event: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build one versioned cross-language shadow event."""

    event = dict(source_event) if source_event is not None else orchestrator_run(int(seed))
    actual_seed = int(event.get("seed", seed))
    payload = _payload_from_event(event)
    candidate_digest = _digest_string(payload["candidate_snapshot_digest"], "candidate_snapshot_digest")
    event_id = "shadow-event-" + _digest(
        f"ndu-shadow-event-id-v1|{actual_seed}|{candidate_digest}".encode("utf-8")
    )[:24]
    body: Dict[str, Any] = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "event_type": EVENT_TYPE,
        "event_id": event_id,
        "seed": actual_seed,
        "status": "shadow_qualification",
        "protocol": _protocol(),
        "payload": payload,
    }
    digest = event_digest(body)
    body["integrity"] = {
        "digest_algorithm": DIGEST_ALGORITHM,
        "canonicalization": CANONICALIZATION,
        "event_digest": digest,
        "source": "ndu_system2_orchestrator.run",
    }
    validate_event(body)
    return body


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReceiptSchemaError(f"{label} must be an object")
    return value


def _require_bool(mapping: Mapping[str, Any], key: str, label: str) -> None:
    if not isinstance(mapping.get(key), bool):
        raise ReceiptSchemaError(f"{label}.{key} must be boolean")


def validate_event(envelope: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate wire-level and semantic invariants, returning the envelope."""

    if not isinstance(envelope, Mapping):
        raise ReceiptSchemaError("event must be an object")
    for key in ("schema_id", "schema_version", "event_type", "event_id", "seed", "status", "protocol", "payload", "integrity"):
        if key not in envelope:
            raise ReceiptSchemaError(f"event missing required field: {key}")
    if envelope["schema_id"] != SCHEMA_ID or envelope["schema_version"] != SCHEMA_VERSION:
        raise ReceiptSchemaError("unsupported schema id or version")
    if envelope["event_type"] != EVENT_TYPE or envelope["status"] != "shadow_qualification":
        raise ReceiptSchemaError("unsupported event type or status")
    if not isinstance(envelope["event_id"], str) or not envelope["event_id"].startswith("shadow-event-"):
        raise ReceiptSchemaError("event_id must be a shadow-event identifier")
    if not isinstance(envelope["seed"], int) or isinstance(envelope["seed"], bool):
        raise ReceiptSchemaError("seed must be an integer")

    protocol = _require_mapping(envelope["protocol"], "protocol")
    if protocol.get("mode") != MODE or protocol.get("authority") != AUTHORITY:
        raise ReceiptSchemaError("protocol is not fail-closed")
    for key in ("provider_dispatch", "real_model_call", "artifact_selection", "learned_fbsde"):
        _require_bool(protocol, key, "protocol")
        if protocol[key]:
            raise ReceiptSchemaError(f"protocol.{key} must remain false in shadow mode")

    payload = _require_mapping(envelope["payload"], "payload")
    for key in ("prompt_state", "portfolio", "tree", "cell", "receipts", "delayed_outcome", "outcome", "ope", "budget", "candidate_snapshot_digest"):
        if key not in payload:
            raise ReceiptSchemaError(f"payload missing required field: {key}")
    candidate_digest = _digest_string(payload["candidate_snapshot_digest"], "payload.candidate_snapshot_digest")

    portfolio = _require_mapping(payload["portfolio"], "payload.portfolio")
    candidates = tuple(portfolio.get("support", ()))
    if tuple(portfolio.get("propensity", {}).keys()) != CANDIDATES:
        # The Python event preserves candidate insertion order.  Set equality
        # is accepted for Rust/Go decoders that re-order map keys.
        if set(portfolio.get("propensity", {})) != set(CANDIDATES):
            raise ReceiptSchemaError("portfolio propensity must contain the complete candidate set")
    propensity = _require_mapping(portfolio.get("propensity"), "portfolio.propensity")
    if abs(sum(float(value) for value in propensity.values()) - 1.0) > 1e-8:
        raise ReceiptSchemaError("portfolio propensity must sum to one")
    if set(candidates) != {name for name, value in propensity.items() if float(value) > 0.0}:
        raise ReceiptSchemaError("portfolio support does not match positive propensity")
    if portfolio.get("selected_action") not in candidates:
        raise ReceiptSchemaError("portfolio selected_action is outside support")

    cell = _require_mapping(payload["cell"], "payload.cell")
    lineage = _require_mapping(cell.get("lineage"), "payload.cell.lineage")
    if lineage.get("candidate_snapshot_digest") != candidate_digest:
        raise ReceiptSchemaError("candidate snapshot digest drift")
    if not lineage.get("candidate_predecessor_matches_initial"):
        raise ReceiptSchemaError("candidate predecessor lineage is not verified")

    receipts = _require_mapping(payload["receipts"], "payload.receipts")
    decision = _require_mapping(receipts.get("decision"), "payload.receipts.decision")
    pending = _require_mapping(receipts.get("pending_outcome"), "payload.receipts.pending_outcome")
    observed = _require_mapping(receipts.get("observed_outcome"), "payload.receipts.observed_outcome")
    decision_id = decision.get("decision_id")
    if not decision_id or pending.get("decision_id") != decision_id or observed.get("decision_id") != decision_id:
        raise ReceiptSchemaError("receipt decision ids do not agree")
    if pending.get("outcome") is not None or not observed.get("observed"):
        raise ReceiptSchemaError("pending/observed outcome contract is invalid")
    if not isinstance(pending.get("watermark"), int) or not isinstance(observed.get("watermark"), int):
        raise ReceiptSchemaError("receipt watermarks must be integers")
    if observed["watermark"] < pending["watermark"]:
        raise ReceiptSchemaError("observed watermark cannot precede pending watermark")

    integrity = _require_mapping(envelope["integrity"], "integrity")
    if integrity.get("digest_algorithm") != DIGEST_ALGORITHM or integrity.get("canonicalization") != CANONICALIZATION:
        raise ReceiptSchemaError("unsupported integrity encoding")
    expected = event_digest(envelope)
    if integrity.get("event_digest") != expected:
        raise ReceiptSchemaError("event digest mismatch")
    _digest_string(integrity.get("event_digest"), "integrity.event_digest")
    return dict(envelope)


def write_event(path: str | Path, seed: int = 17) -> Dict[str, Any]:
    """Write a pretty golden vector and return the validated event."""

    event = build_event(seed)
    target = Path(path)
    target.write_text(json.dumps(event, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return event


def schema_file_digest(path: str | Path) -> str:
    return _digest(Path(path).read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Export an NDU shadow receipt golden vector")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    event = build_event(args.seed)
    if args.output:
        args.output.write_text(json.dumps(event, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(event, indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
