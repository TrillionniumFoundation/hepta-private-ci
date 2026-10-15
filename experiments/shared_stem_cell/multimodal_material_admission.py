"""V6 offline operator material admission; NEVER publisher or production attestation.

Verifies an independently pinned operator trust store, an Ed25519 signature
binding a V4 plan to a V2 profile, and physically inspects an exact, bounded
safetensors snapshot. The caller MUST supply the store SHA from outside the
candidate/artifact. Neither a local signature nor model tensor shape proves
publisher origin, pretraining, task quality, authorization or NDU benefit.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from safetensors import safe_open

from multimodal_alignment_contract import canonical, load_pinned_document, sha, write_new
from multimodal_bridge import ContractError, _digest
from multimodal_candidate_gate import validate_plan
from multimodal_real_encoder import validated_profile

TRUST_SCHEMA = "hepta.stem-offline-operator-trust.v6"
CLAIM_SCHEMA = "hepta.stem-offline-operator-claim.v6"
REPORT_SCHEMA = "hepta.stem-offline-material-admission.v6"
DOMAIN = b"HEPTA/STEM/OFFLINE-OPERATOR-CLAIM/V6\0"
MAX_SHARDS = 32
MAX_TENSORS = 4096
MAX_TENSOR_ELEMENTS = 1_000_000_000
MAX_TOTAL_ELEMENTS = 2_000_000_000
MAX_LIFETIME_SECONDS = 30 * 24 * 3600
FLOAT_DTYPES = {"F16", "BF16", "F32", "F64"}


def _hex(value: object, count: int, what: str) -> str:
    if type(value) is not str or len(value) != count or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(f"invalid canonical {what}")
    return value


def _keys(value: object, keys: set[str], description: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise ContractError(f"invalid {description} fields")
    return value


def _positive_int(value: object, upper: int, description: str, low: int = 1) -> int:
    if type(value) is not int or not low <= value <= upper:
        raise ContractError(f"invalid {description}")
    return value


def _model_policy(trust: dict, candidate: str) -> dict:
    records = trust["allowed_models"]
    if type(records) is not list or not 1 <= len(records) <= 8:
        raise ContractError("bounded trusted model inventory required")
    names = []
    selected = None
    for item in records:
        _keys(item, {"candidate", "upstream_repo", "expected_width", "kind",
                     "minimum_floating_elements", "maximum_floating_elements"}, "model policy")
        name = item["candidate"]
        if type(name) is not str or not name or len(name) > 96:
            raise ContractError("invalid model candidate label")
        names.append(name)
        repo = item["upstream_repo"]
        if (type(repo) is not str or not 3 <= len(repo) <= 180 or repo.count("/") != 1
                or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_. /".replace(" ", "") for c in repo)):
            raise ContractError("invalid upstream model repository id")
        _positive_int(item["expected_width"], 512, "model width")
        if item["kind"] not in ("encoder", "masked_lm"):
            raise ContractError("invalid frozen model kind")
        lower = _positive_int(item["minimum_floating_elements"], MAX_TOTAL_ELEMENTS, "minimum tensor elements")
        upper = _positive_int(item["maximum_floating_elements"], MAX_TOTAL_ELEMENTS, "maximum tensor elements")
        if lower > upper:
            raise ContractError("invalid tensor range")
        if name == candidate:
            selected = item
    if names != sorted(set(names)) or selected is None:
        raise ContractError("untrusted or noncanonical candidate inventory")
    return selected


def verify_trust_store(trust: dict, expected_sha256: str, candidate: str) -> dict:
    if sha(canonical(trust)) != _digest(expected_sha256):
        raise ContractError("operator-installed trust anchor is not SHA-pinned")
    _keys(trust, {"schema", "issuer", "public_key_ed25519_hex", "allowed_models",
                  "revoked_snapshot_sha256s", "revoked_key_sha256s"}, "trust store")
    if trust["schema"] != TRUST_SCHEMA:
        raise ContractError("unrecognized operator trust schema")
    if type(trust["issuer"]) is not str or not 1 <= len(trust["issuer"]) <= 128:
        raise ContractError("invalid issuer")
    key = bytes.fromhex(_hex(trust["public_key_ed25519_hex"], 64, "Ed25519 public key"))
    key_id = sha(key)
    for name in ("revoked_snapshot_sha256s", "revoked_key_sha256s"):
        values = trust[name]
        if type(values) is not list or len(values) > 1024 or values != sorted(set(values)):
            raise ContractError("invalid trust revocation set")
        for val in values:
            _digest(val)
    if key_id in trust["revoked_key_sha256s"]:
        raise ContractError("operator signing key has been revoked")
    policy = _model_policy(trust, candidate)
    return {"key": key, "key_sha256": key_id, "policy": policy}


def _verify_snapshot_files(root: Path, snapshot: dict) -> str:
    """Self-contained bounded SHA inventory, no model import/network dependency."""
    _keys(snapshot, {"revision", "kind", "files"}, "model snapshot")
    if (type(snapshot["revision"]) is not str or len(snapshot["revision"]) != 40
            or any(c not in "0123456789abcdef" for c in snapshot["revision"])):
        raise ContractError("unbound immutable model revision")
    if snapshot["kind"] not in {"encoder", "masked_lm"}:
        raise ContractError("unknown model kind")
    inventory = snapshot["files"]
    if type(inventory) is not dict or not 1 <= len(inventory) <= 256:
        raise ContractError("bounded file inventory required")
    if root.is_symlink() or not root.is_dir() or any(parent.is_symlink() for parent in root.parents):
        raise ContractError("symlinked or missing model root")
    total = 0
    for name, digest in sorted(inventory.items()):
        if type(name) is not str or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ContractError("unsafe snapshot path")
        _digest(digest)
        path = root / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent) or not path.is_file():
            raise ContractError("snapshot member missing or symlinked")
        total += path.stat().st_size
        if total > 4 * 1024**3:
            raise ContractError("snapshot exceeds 4 GiB")
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for part in iter(lambda: handle.read(1024**2), b""):
                h.update(part)
        if h.hexdigest() != digest:
            raise ContractError("model snapshot bytes changed")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(inventory):
        raise ContractError("extra or missing model snapshot files")
    return sha(canonical(snapshot))


def inspect_weight_material(snapshot_root: Path, snapshot: dict) -> dict:
    """Actually hashes declared files and reads bounded safetensors headers.

    Floating tensor element count is NOT model trainable parameter count: tied
    tensors, task heads and buffers may make the two differ.
    """
    snapshot_digest = _verify_snapshot_files(snapshot_root, snapshot)
    names = sorted(x for x in snapshot["files"] if x.endswith(".safetensors"))
    if not 1 <= len(names) <= MAX_SHARDS:
        raise ContractError("bounded real safetensors shards required")
    visited: set[str] = set()
    all_elements = 0
    float_elements = 0
    for name in names:
        try:
            with safe_open(str(snapshot_root / name), framework="pt", device="cpu") as store:
                tensor_names = sorted(store.keys())
                if not tensor_names or len(tensor_names) + len(visited) > MAX_TENSORS:
                    raise ContractError("empty or oversized tensor inventory")
                for tensor_name in tensor_names:
                    if tensor_name in visited:
                        raise ContractError("duplicated tensor across safetensors shards")
                    visited.add(tensor_name)
                    sl = store.get_slice(tensor_name)
                    shape = sl.get_shape()
                    if not 1 <= len(shape) <= 8:
                        raise ContractError("invalid saved tensor rank")
                    numel = 1
                    for side in shape:
                        numel *= _positive_int(side, MAX_TENSOR_ELEMENTS, "tensor dimension")
                        if numel > MAX_TENSOR_ELEMENTS:
                            raise ContractError("saved tensor too large")
                    dtype = sl.get_dtype()
                    if dtype not in FLOAT_DTYPES and dtype not in {"I64", "I32"}:
                        raise ContractError("unexpected saved tensor dtype")
                    all_elements += numel
                    if dtype in FLOAT_DTYPES:
                        float_elements += numel
                    if all_elements > MAX_TOTAL_ELEMENTS:
                        raise ContractError("oversized saved parameter inventory")
        except ContractError:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            raise ContractError("unreadable or malformed saved model tensors") from exc
    if float_elements == 0:
        raise ContractError("no floating model weights")
    # Re-read full inventory after inspection: reject mutation during preflight.
    if _verify_snapshot_files(snapshot_root, snapshot) != snapshot_digest:
        raise ContractError("model material changed during inspection")
    return {"snapshot_sha256": snapshot_digest,
            "saved_floating_tensor_elements": float_elements,
            "saved_all_tensor_elements": all_elements,
            "saved_tensor_count": len(visited), "safetensors_shards": len(names)}


def admission(plan: dict, plan_sha256: str, profile: dict, profile_sha256: str,
              snapshot_root: Path, trust: dict, trust_sha256: str,
              assertion: dict, assertion_sha256: str, *, now_seconds: int) -> dict:
    validate_plan(plan)
    if sha(canonical(plan)) != _digest(plan_sha256):
        raise ContractError("frozen V4 plan hash differs")
    parsed = validated_profile(profile, profile_sha256)
    declarations = [x for x in plan["candidates"] if x["name"] == parsed.candidate]
    if (len(declarations) != 1 or parsed.candidate == "no_change"
            or declarations[0]["profile_sha256"] != profile_sha256
            or declarations[0]["snapshot_sha256"] != parsed.snapshot_digest):
        raise ContractError("profile not in frozen matched candidate plan")
    anchor = verify_trust_store(trust, trust_sha256, parsed.candidate)
    policy = anchor["policy"]
    if parsed.expected_width != policy["expected_width"] or parsed.snapshot["kind"] != policy["kind"]:
        raise ContractError("physical model architecture contradicts trusted policy")
    if sha(canonical(assertion)) != _digest(assertion_sha256):
        raise ContractError("operator assertion bytes differ from declared hash")
    _keys(assertion, {"schema", "issuer", "signed", "signature_ed25519_hex"}, "signed assertion")
    if assertion["schema"] != CLAIM_SCHEMA or assertion["issuer"] != trust["issuer"]:
        raise ContractError("assertion issuer/schema mismatch")
    content = _keys(assertion["signed"], {
        "candidate", "plan_sha256", "profile_sha256", "snapshot_sha256", "upstream_repo",
        "upstream_revision", "saved_floating_tensor_elements", "issued_at", "expires_at",
    }, "signed claim")
    if any(content[k] != expected for k, expected in (
            ("candidate", parsed.candidate), ("plan_sha256", plan_sha256),
            ("profile_sha256", profile_sha256), ("snapshot_sha256", parsed.snapshot_digest),
            ("upstream_repo", policy["upstream_repo"]),
            ("upstream_revision", parsed.snapshot["revision"]))):
        raise ContractError("signed claim is not exact candidate/plan/model revision")
    _positive_int(now_seconds, 2**63 - 1, "current time")
    issued = _positive_int(content["issued_at"], 2**63 - 1, "issued time")
    expires = _positive_int(content["expires_at"], 2**63 - 1, "expiry time")
    if not issued <= now_seconds <= expires or not 0 < expires-issued <= MAX_LIFETIME_SECONDS:
        raise ContractError("operator assertion expired, future-issued or too long-lived")
    declared_elements = _positive_int(content["saved_floating_tensor_elements"], MAX_TOTAL_ELEMENTS,
                                      "claimed floating model tensor elements")
    if not policy["minimum_floating_elements"] <= declared_elements <= policy["maximum_floating_elements"]:
        raise ContractError("claimed model weight size outside trusted model policy")
    signature = bytes.fromhex(_hex(assertion["signature_ed25519_hex"], 128, "Ed25519 signature"))
    signed_bytes = DOMAIN + canonical({k: assertion[k] for k in ("schema", "issuer", "signed")})
    try:
        Ed25519PublicKey.from_public_bytes(anchor["key"]).verify(signature, signed_bytes)
    except (ValueError, InvalidSignature) as exc:
        raise ContractError("unverified operator review signature") from exc
    if parsed.snapshot_digest in trust["revoked_snapshot_sha256s"]:
        raise ContractError("candidate model snapshot has been revoked")
    physical = inspect_weight_material(snapshot_root, parsed.snapshot)
    if physical["snapshot_sha256"] != parsed.snapshot_digest or physical["saved_floating_tensor_elements"] != declared_elements:
        raise ContractError("signed model weight inventory differs from physical material")
    return {"schema": REPORT_SCHEMA, "candidate": parsed.candidate,
            "plan_sha256": plan_sha256, "profile_sha256": profile_sha256,
            "snapshot_sha256": parsed.snapshot_digest, "operator_trust_store_sha256": trust_sha256,
            "operator_key_sha256": anchor["key_sha256"], "operator_assertion_sha256": assertion_sha256,
            **physical, "operator_review_signature_verified": True,
            "local_snapshot_bytes_verified": True,
            "model_publisher_authenticated": False, "actual_pretraining_proven": False,
            "task_efficacy_proven": False, "independent_ndu_verified": False,
            "worker_final_use_authorized": False, "production_accepted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="V6 offline operator-reviewed material preflight; no model loading or promotion")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--model-snapshot", type=Path, required=True)
    parser.add_argument("--operator-trust", type=Path, required=True)
    parser.add_argument("--operator-trust-sha256", required=True)
    parser.add_argument("--signed-claim", type=Path, required=True)
    parser.add_argument("--signed-claim-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = admission(load_pinned_document(args.plan, args.plan_sha256), args.plan_sha256,
                       load_pinned_document(args.profile, args.profile_sha256), args.profile_sha256,
                       args.model_snapshot,
                       load_pinned_document(args.operator_trust, args.operator_trust_sha256), args.operator_trust_sha256,
                       load_pinned_document(args.signed_claim, args.signed_claim_sha256), args.signed_claim_sha256,
                       now_seconds=int(time.time()))
    write_new(args.output, result)


if __name__ == "__main__":
    main()
