"""P6 Codex/native fail-closed fallback and signed offline parity reference.

The return values are *advisory*. There is intentionally no tool-dispatch API.
Real FinalUse consumption, tool execution, readback and effect-owner fencing
remain with the existing Hepta owner. Signatures authenticate provenance only;
they do not prove host truth or operator acceptance.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"hepta.p6.codex-native.evidence.v1\x00"
HEX32 = re.compile(r"[0-9a-f]{64}\Z")
ROLES = frozenset({"final_use_issuer", "independent_observer", "native_owner", "codex_owner", "independent_evaluator"})
BACKENDS = frozenset({"native", "codex"})
OP_FIELDS = frozenset({"operation_id", "scope_id", "generation", "intent_digest", "payload_digest", "tool_id", "host_scope", "idempotency_key", "owner_epoch"})
RECORD_FIELDS = frozenset({"case_id", "task_digest", "source_tree_digest", "model_digest", "policy_digest", "budget_digest", "hardware_digest", "tool_digest", "scope_id", "generation", "sandbox_id", "status", "dispatch_count", "normalized_result_digest", "state_before_digest", "state_after_digest", "effect_receipt_digest", "failure_class"})
SHARED_FIELDS = frozenset({"case_id", "task_digest", "source_tree_digest", "model_digest", "policy_digest", "budget_digest", "hardware_digest", "tool_digest", "scope_id", "generation", "state_before_digest"})


class EvidenceRejected(ValueError):
    """Malformed, untrusted, stale or inconsistent source evidence."""


class Decision(str, Enum):
    ADVISORY_FALLBACK = "advisory_fallback_requires_fresh_final_use"
    RECONCILE_ONLY = "reconcile_only"
    NO_FALLBACK_TERMINAL = "no_fallback_terminal"


@dataclass(frozen=True)
class VerifiedEvidence:
    role: str
    key_id: str
    payload: dict[str, Any]
    envelope_digest: str
    public_key_hex: str


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(text: str) -> dict[str, Any]:
    # JSON numeric exponent overflow (1e999) is silently parsed as infinity by
    # CPython unless the parse_float hook rejects it. parse_constant covers
    # only literal NaN/Infinity tokens and is not sufficient.
    def finite_float(raw: str) -> float:
        value = float(raw)
        if not math.isfinite(value):
            raise EvidenceRejected("nonfinite JSON exponent")
        return value

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in pairs:
            if k in result:
                raise EvidenceRejected(f"duplicate JSON member: {k}")
            result[k] = v
        return result
    try:
        output = json.loads(
            text, object_pairs_hook=unique, parse_float=finite_float,
            parse_constant=lambda s: (_ for _ in ()).throw(EvidenceRejected(f"nonfinite JSON {s}")),
        )
    except (ValueError, TypeError) as exc:
        raise EvidenceRejected(f"invalid JSON: {exc}") from exc
    if not isinstance(output, dict):
        raise EvidenceRejected("JSON object required")
    return output


def _shape(value: Any, expected: frozenset[str] | set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise EvidenceRejected(f"{name} fields must match exact reviewed schema")
    return value


def _hex(value: Any, name: str) -> None:
    if not isinstance(value, str) or not HEX32.fullmatch(value) or value == "0" * 64:
        raise EvidenceRejected(f"{name} must be a nonzero canonical SHA256 digest")


def _positive_int(value: Any, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise EvidenceRejected(f"{name} must be a positive integer")


def _id(value: Any, name: str) -> None:
    if not isinstance(value, str) or not (1 <= len(value) <= 128) or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise EvidenceRejected(f"{name} must be a printable nonempty identifier")


def _ed25519_prime_order_public_key(encoded: bytes) -> bool:
    """Reject identity, torsion, mixed-order and noncanonical observer keys.

    A 32-byte Ed25519 key can decode to a small-order point even when the
    underlying signature library accepts its encoding. Verify that [L]P is
    the neutral point, and that P itself is not neutral, before trusting it.
    All arithmetic here handles public input, never a secret scalar.
    """
    prime = 2**255 - 19
    order = 2**252 + 27742317777372353535851937790883648493
    d = -121665 * pow(121666, -1, prime) % prime
    sqrt_minus_one = pow(2, (prime - 1) // 4, prime)
    if len(encoded) != 32:
        return False
    value = int.from_bytes(encoded, "little")
    y = value & ((1 << 255) - 1)
    sign = value >> 255
    if y >= prime:
        return False
    yy = y * y % prime
    denominator = (d * yy + 1) % prime
    if denominator == 0:
        return False
    xx = (yy - 1) * pow(denominator, -1, prime) % prime
    x = pow(xx, (prime + 3) // 8, prime)
    if x * x % prime != xx:
        x = x * sqrt_minus_one % prime
    if x * x % prime != xx or (x == 0 and sign):
        return False
    if (x & 1) != sign:
        x = -x % prime
    if x == 0 and y == 1:
        return False

    def add(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = a
        x2, y2, z2, t2 = b
        aa = (y1 - x1) * (y2 - x2) % prime
        bb = (y1 + x1) * (y2 + x2) % prime
        cc = 2 * d * t1 * t2 % prime
        dd = 2 * z1 * z2 % prime
        ee = (bb - aa) % prime
        ff = (dd - cc) % prime
        gg = (dd + cc) % prime
        hh = (bb + aa) % prime
        return ee * ff % prime, gg * hh % prime, ff * gg % prime, ee * hh % prime

    def double(a: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, yy, z, _ = a
        aa = x * x % prime
        bb = yy * yy % prime
        cc = 2 * z * z % prime
        dd = -aa % prime
        ee = ((x + yy) ** 2 - aa - bb) % prime
        gg = (dd + bb) % prime
        ff = (gg - cc) % prime
        hh = (dd - bb) % prime
        return ee * ff % prime, gg * hh % prime, ff * gg % prime, ee * hh % prime

    point = (x, y, 1, x * y % prime)
    result = (0, 1, 1, 0)
    for bit in range(order.bit_length() - 1, -1, -1):
        result = double(result)
        if (order >> bit) & 1:
            result = add(result, point)
    result_x, result_y, result_z, _ = result
    return result_z != 0 and result_x == 0 and (result_y - result_z) % prime == 0


def verify_envelope(envelope: Mapping[str, Any], trust: Mapping[str, Mapping[str, str]], expected_role: str) -> VerifiedEvidence:
    """Cryptographically verify one disjoint-role, explicitly configured public key."""
    e = _shape(dict(envelope), {"version", "role", "key_id", "payload", "signature"}, "envelope")
    # bool/float compare equal to integer 1 in Python. Signing the canonical
    # integer and then changing the visible version to True/1.0 must not pass.
    if type(e["version"]) is not int or e["version"] != 1 or e["role"] != expected_role or expected_role not in ROLES:
        raise EvidenceRejected("unsupported evidence version or signer role")
    key_id = e["key_id"]
    _id(key_id, "key_id")
    if not isinstance(e["payload"], dict):
        raise EvidenceRejected("signed payload must be a JSON object")
    try:
        key_hex = trust[expected_role][key_id]
        key_bytes = bytes.fromhex(key_hex)
        signature = base64.b64decode(e["signature"], validate=True)
        if len(key_bytes) != 32 or len(signature) != 64:
            raise ValueError("bad public key or signature length")
        # A 32-byte Ed25519 key is not automatically a safe verifier key.
        # Certain crypto providers accept zero signatures for torsion points.
        if not _ed25519_prime_order_public_key(key_bytes):
            raise EvidenceRejected("non-prime-order Ed25519 signer trust root")
        key = Ed25519PublicKey.from_public_bytes(key_bytes)
        signed = {"version": 1, "role": expected_role, "key_id": key_id, "payload": e["payload"]}
        key.verify(signature, DOMAIN + canonical_bytes(signed))
        digest = hashlib.sha256(DOMAIN + canonical_bytes(signed) + signature).hexdigest()
        return VerifiedEvidence(expected_role, key_id, e["payload"], digest, key_bytes.hex())
    except EvidenceRejected:
        raise
    except (KeyError, ValueError, TypeError, InvalidSignature) as exc:
        raise EvidenceRejected(f"untrusted or invalid {expected_role} signature") from exc


def _separate_signers(*evidence: VerifiedEvidence) -> None:
    if len({r.key_id for r in evidence}) != len(evidence) or len({r.public_key_hex for r in evidence}) != len(evidence):
        raise EvidenceRejected("independent signer/key-role separation violated")


def _op(p: dict[str, Any]) -> None:
    _shape({k: p[k] for k in OP_FIELDS if k in p}, OP_FIELDS, "operation binding")
    for k in ("operation_id", "scope_id", "tool_id", "host_scope", "idempotency_key"):
        _id(p[k], k)
    for k in ("intent_digest", "payload_digest"):
        _hex(p[k], k)
    _positive_int(p["generation"], "generation")
    _positive_int(p["owner_epoch"], "owner_epoch")


def assess_fallback(
    *, request: Mapping[str, Any], final_use: Mapping[str, Any],
    primary_observation: Mapping[str, Any], trust: Mapping[str, Mapping[str, str]], now_ms: int,
) -> Decision:
    """Check *eligibility to request* fallback, never issue an execution permit.

    A failed/unknown post-admission effect is NEVER automatically replayed on
    another backend. The existing durable effect owner must reconcile it first.
    """
    if type(now_ms) is not int or now_ms < 0:
        raise EvidenceRejected("trusted current timestamp is required")
    req = _shape(dict(request), OP_FIELDS | {"primary_backend", "fallback_backend"}, "fallback request")
    _op(req)
    if req["primary_backend"] not in BACKENDS or req["fallback_backend"] not in BACKENDS or req["primary_backend"] == req["fallback_backend"]:
        raise EvidenceRejected("invalid or identical backend pair")
    grant = verify_envelope(final_use, trust, "final_use_issuer")
    observation = verify_envelope(primary_observation, trust, "independent_observer")
    _separate_signers(grant, observation)
    gp = _shape(grant.payload, OP_FIELDS | {"expires_at_ms", "allowed_backends"}, "signed FinalUse")
    op = _shape(observation.payload, OP_FIELDS | {"primary_backend", "state", "dispatch_count", "observation_digest"}, "signed observation")
    _op(gp)
    _op(op)
    for k in OP_FIELDS:
        if gp[k] != req[k] or op[k] != req[k]:
            raise EvidenceRejected(f"signed {k} mismatch")
    if op["primary_backend"] != req["primary_backend"]:
        raise EvidenceRejected("primary backend mismatch")
    if type(gp["expires_at_ms"]) is not int or now_ms >= gp["expires_at_ms"]:
        raise EvidenceRejected("expired FinalUse evidence")
    backs = gp["allowed_backends"]
    if not isinstance(backs, list) or any(not isinstance(b, str) for b in backs) or len(backs) != len(set(backs)) or not set(backs).issubset(BACKENDS) or not {req["primary_backend"], req["fallback_backend"]}.issubset(backs):
        raise EvidenceRejected("fallback backend not in signed FinalUse scope")
    _hex(op["observation_digest"], "independent observation")
    count = op["dispatch_count"]
    if type(count) is not int or count < 0 or count > 1:
        raise EvidenceRejected("impossible or multiple primary dispatches")
    state = op["state"]
    if state == "rejected_before_admission":
        if count != 0:
            raise EvidenceRejected("rejected-before-admission with physical dispatch")
        return Decision.ADVISORY_FALLBACK
    if state in ("admitted", "indeterminate", "timeout", "cancel_pending", "failed_after_dispatch"):
        return Decision.RECONCILE_ONLY
    if state == "completed":
        if count != 1:
            raise EvidenceRejected("completed effect lacks observed dispatch")
        return Decision.NO_FALLBACK_TERMINAL
    raise EvidenceRejected("unknown primary state")


def _record(rec: dict[str, Any]) -> None:
    _shape(rec, RECORD_FIELDS, "paired execution record")
    for key in ("case_id", "scope_id", "sandbox_id", "failure_class"):
        _id(rec[key], key)
    for key in ("task_digest", "source_tree_digest", "model_digest", "policy_digest", "budget_digest", "hardware_digest", "tool_digest", "normalized_result_digest", "state_before_digest", "state_after_digest", "effect_receipt_digest"):
        _hex(rec[key], key)
    _positive_int(rec["generation"], "generation")
    if rec["status"] not in ("completed", "failed", "rejected"):
        raise EvidenceRejected("unresolved outcome is not a parity result")
    if type(rec["dispatch_count"]) is not int or rec["dispatch_count"] not in (0, 1):
        raise EvidenceRejected("unbounded or invalid dispatch count")
    if rec["status"] == "rejected" and (rec["dispatch_count"] != 0 or rec["state_before_digest"] != rec["state_after_digest"]):
        raise EvidenceRejected("rejected execution produced an effect")
    if rec["status"] in ("completed", "failed") and rec["dispatch_count"] != 1:
        raise EvidenceRejected("terminal execution has no observed dispatch")


def assess_signed_parity(
    *, native: Mapping[str, Any], codex: Mapping[str, Any],
    evaluation: Mapping[str, Any], trust: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """Validate signed *offline* evidence equality; not a production qualification."""
    n = verify_envelope(native, trust, "native_owner")
    c = verify_envelope(codex, trust, "codex_owner")
    v = verify_envelope(evaluation, trust, "independent_evaluator")
    _separate_signers(n, c, v)
    _record(n.payload)
    _record(c.payload)
    for field in SHARED_FIELDS:
        if n.payload[field] != c.payload[field]:
            raise EvidenceRejected(f"unmatched parity cohort: {field}")
    if n.payload["sandbox_id"] == c.payload["sandbox_id"]:
        raise EvidenceRejected("paired destructive effects must use distinct sandboxes")
    for field in ("status", "normalized_result_digest", "state_after_digest", "failure_class"):
        if n.payload[field] != c.payload[field]:
            raise EvidenceRejected(f"native/Codex result mismatch: {field}")
    vpay = _shape(v.payload, {"case_id", "native_envelope_digest", "codex_envelope_digest", "heldout_digest", "evaluator_policy_digest", "result"}, "independent evaluation")
    if vpay["case_id"] != n.payload["case_id"] or vpay["native_envelope_digest"] != n.envelope_digest or vpay["codex_envelope_digest"] != c.envelope_digest:
        raise EvidenceRejected("independent evaluation does not bind exact source envelopes")
    _hex(vpay["heldout_digest"], "heldout dataset")
    _hex(vpay["evaluator_policy_digest"], "evaluation policy")
    if vpay["result"] != "matched":
        raise EvidenceRejected("independent evaluator did not accept parity")
    return {
        "case_id": vpay["case_id"],
        "evidence_shape": "signed_matched_offline",
        "native_receipt": n.envelope_digest,
        "codex_receipt": c.envelope_digest,
        "evaluator_receipt": v.envelope_digest,
        "production_qualified": False,
        "remaining": "real host provenance, trusted external observer, full P6 scenarios, FinalUse consumption, failure injection, feature parity",
    }
