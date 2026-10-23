"""Verify externally governed production evidence without activating the module.

This command reopens the durable owner, reconstructs the exact persisted envelope
and lease, invokes the existing typed distributed-fence/audit-anchor/key-custody
verifier, and only then composes separately signed deployment and operator facts.
It never changes production_implementation or grants authority.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time

from .control_plane import (
    EngineeringError,
    EngineeringStore,
    LeaseReceipt,
    WorkEnvelope,
)
from .external_controls import (
    AuditAnchorAttestation,
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    KeyCustodyReceipt,
    verify_production_controls,
)
from .production_adapters import (
    OpenSslPublicKeyTrustStore,
    PublicKeyBinding,
    load_external_receipts,
    verify_external_production_bundle,
)

_SCHEMA = "hepta.control-engineering-production-acceptance-verification.v2"


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs
    )


def _load_bindings(path: Path) -> dict[tuple[str, str], PublicKeyBinding]:
    value = _load_json(path)
    if not isinstance(value, list) or not value:
        raise ValueError("public key manifest must be a nonempty array")
    result: dict[tuple[str, str], PublicKeyBinding] = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid public key manifest row")
        issuer = row.get("issuer")
        identity = row.get("signingIdentity")
        public_key_path = row.get("publicKeyPath")
        algorithm = row.get("algorithm")
        if not all(
            isinstance(item, str) and item
            for item in (issuer, identity, public_key_path, algorithm)
        ):
            raise ValueError("invalid public key manifest row")
        key = (issuer, identity)
        if key in result:
            raise ValueError("duplicate public key identity")
        result[key] = PublicKeyBinding(public_key_path, algorithm)
    return result


def _string_tuple(value: object, code: str) -> tuple[str, ...]:
    try:
        raw = value if isinstance(value, str) else bytes(value).decode("utf-8")
        parsed = json.loads(raw)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise EngineeringError(code) from None
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise EngineeringError(code)
    return tuple(parsed)


def _load_owner_state(
    store: EngineeringStore,
    *,
    envelope_id: str,
    lease_id: str,
) -> tuple[WorkEnvelope, LeaseReceipt]:
    envelope_row = store.connection.execute(
        "SELECT * FROM work_envelopes WHERE envelope_id=?", (envelope_id,)
    ).fetchone()
    if envelope_row is None:
        raise EngineeringError("production_acceptance_envelope_unknown")
    envelope = WorkEnvelope(
        str(envelope_row["envelope_id"]),
        str(envelope_row["source_commit"]),
        str(envelope_row["source_tree"]),
        str(envelope_row["objective_digest"]),
        str(envelope_row["contract_digest"]),
        str(envelope_row["owner"]),
        _string_tuple(
            envelope_row["allowed_paths_json"],
            "production_acceptance_envelope_invalid",
        ),
        _string_tuple(
            envelope_row["denied_authorities_json"],
            "production_acceptance_envelope_invalid",
        ),
        int(envelope_row["maximum_assignments"]),
        int(envelope_row["expires_unix_ns"]),
        int(envelope_row["revision"]),
    )
    lease_row = store.connection.execute(
        "SELECT * FROM path_leases WHERE lease_id=?", (lease_id,)
    ).fetchone()
    if lease_row is None:
        raise EngineeringError("production_acceptance_lease_unknown")
    lease = LeaseReceipt(
        str(lease_row["lease_id"]),
        str(lease_row["envelope_id"]),
        str(lease_row["holder"]),
        _string_tuple(
            lease_row["paths_json"], "production_acceptance_lease_invalid"
        ),
        str(lease_row["state"]),
        int(lease_row["authority_epoch"]),
        int(lease_row["fencing_token"]),
        int(lease_row["revision"]),
        int(lease_row["issued_unix_ns"]),
        int(lease_row["expires_unix_ns"]),
    )
    if lease.envelope_id != envelope.envelope_id:
        raise EngineeringError("production_acceptance_owner_binding")
    return envelope, lease


def _custody_receipt(value: object) -> KeyCustodyReceipt:
    if not isinstance(value, dict):
        raise ValueError("typed key custody bundle")
    row = dict(value)
    roles = row.get("roles")
    if not isinstance(roles, list) or any(
        not isinstance(role, str) for role in roles
    ):
        raise ValueError("typed key custody roles")
    row["roles"] = tuple(roles)
    try:
        return KeyCustodyReceipt(**row)
    except TypeError:
        raise ValueError("typed key custody bundle") from None


def _load_typed_controls(
    path: Path,
) -> tuple[
    DistributedFenceReceipt,
    DistributedRevocationFrontierReceipt,
    AuditAnchorAttestation,
    tuple[KeyCustodyReceipt, ...],
]:
    value = _load_json(path)
    if not isinstance(value, dict) or set(value) != {
        "distributedFence",
        "revocationFrontier",
        "auditAnchor",
        "keyCustody",
    }:
        raise ValueError("typed production control bundle shape")
    custody = value["keyCustody"]
    if not isinstance(custody, list) or not custody:
        raise ValueError("typed key custody bundle")
    distributed = value["distributedFence"]
    frontier = value["revocationFrontier"]
    audit = value["auditAnchor"]
    if not all(isinstance(row, dict) for row in (distributed, frontier, audit)):
        raise ValueError("typed production control bundle shape")
    try:
        return (
            DistributedFenceReceipt(**distributed),
            DistributedRevocationFrontierReceipt(**frontier),
            AuditAnchorAttestation(**audit),
            tuple(_custody_receipt(row) for row in custody),
        )
    except TypeError:
        raise ValueError("typed production control bundle shape") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--envelope-id", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--typed-controls", required=True, type=Path)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--public-keys", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--target-digest", required=True)
    parser.add_argument("--now-ns", type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        now = time.time_ns() if args.now_ns is None else args.now_ns
        trust = OpenSslPublicKeyTrustStore(_load_bindings(args.public_keys))
        distributed, frontier, audit, custody = _load_typed_controls(
            args.typed_controls
        )
        with EngineeringStore(args.database) as store:
            envelope, lease = _load_owner_state(
                store,
                envelope_id=args.envelope_id,
                lease_id=args.lease_id,
            )
            if (
                envelope.source_commit != args.source_commit
                or envelope.source_tree != args.source_tree
            ):
                raise EngineeringError(
                    "production_acceptance_source_binding"
                )
            controls = verify_production_controls(
                lease,
                envelope,
                distributed,
                frontier,
                store,
                audit,
                custody,
                trust,
                now_ns=now,
            )
            observations = load_external_receipts(args.receipts)
            decision = verify_external_production_bundle(
                observations,
                trust,
                production_controls=controls,
                expected_source_commit=args.source_commit,
                expected_source_tree=args.source_tree,
                expected_target_digest=args.target_digest,
                now_ns=now,
            )
        value = {
            "schema": _SCHEMA,
            "decision": asdict(decision),
            "productionImplementationChanged": False,
            "activationPerformed": False,
            "releasePerformed": False,
            "externalEffectPerformed": False,
        }
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"schema": _SCHEMA, "status": "rejected", "error": str(error)}
            )
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
