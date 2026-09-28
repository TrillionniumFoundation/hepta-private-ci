#!/usr/bin/env python3
"""Verify and generate the closed-world public AuthBus API inventory."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/modules/auth.authbus/PUBLIC_API_INVENTORY.json"
AUTHBUS = ROOT / "codex-rs/hepta-authbus/src"

HOST_OPERATIONS = {
    "open",
    "bootstrap",
    "sync_checkpoint",
    "enroll_issuer",
    "rotate_issuer",
    "revoke_issuer",
    "retire_issuer_epoch",
    "observe_trusted_time_attestation",
    "message_issuer",
    "settlement_issuer",
    "create_policy",
    "replace_policy",
    "revoke_policy",
    "retire_policy",
    "authorize",
    "create_quota",
    "replace_quota",
    "reserve",
    "mark_dispatch_attempted",
    "mark_indeterminate",
    "cancel_reservation",
    "reconcile_expired_reservation",
    "sweep_expired_reservations",
    "settle",
    "compact_terminal_reservations",
    "quota_snapshot",
    "reservation",
    "operational_snapshot",
    "maintenance_tick",
}

STORE_OPERATIONS = {
    "open",
    "observe_time",
    "last_trusted_time",
    "create_policy",
    "replace_policy",
    "revoke_policy",
    "retire_policy",
    "authorize",
    "create_quota",
    "replace_quota",
    "reserve",
    "quota_snapshot",
    "reservation",
    "compact_terminal_reservations",
    "authority_frontier_digest",
    "authority_checkpoint",
    "initialize_authority_checkpoint",
    "reconcile_authority_checkpoint",
    "advance_authority_checkpoint",
    "recovery_required",
    "reconcile_after_restart",
    "mark_dispatch_attempted",
    "mark_indeterminate",
    "cancel_reservation",
    "reconcile_expired_reservation",
    "sweep_expired_reservations",
    "settle",
    "enroll_issuer",
    "rotate_issuer",
    "revoke_issuer",
    "retire_issuer_epoch",
    "issuer_record",
    "message_issuer",
    "settlement_issuer",
    "observe_trusted_time_attestation",
    "operational_snapshot",
}

STORE_FILES = [
    "authority_store.rs",
    "quota_store.rs",
    "recovery.rs",
    "settlement_store.rs",
    "trust_store.rs",
    "operations.rs",
]


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def contains_registration_literal(text: str, type_name: str) -> bool:
    for match in re.finditer(rf"\b{re.escape(type_name)}\s*\{{", text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start : match.start()]
        if re.search(r"(?:->|\bstruct)\s*$", prefix):
            continue
        return True
    return False


def verify_boundaries() -> list[str]:
    errors: list[str] = []
    allowed_message_literal = AUTHBUS / "signed.rs"
    allowed_settlement_literal = AUTHBUS / "settlement.rs"
    for path in sorted((ROOT / "codex-rs").rglob("*.rs")):
        text = source(path)
        if path != allowed_message_literal and contains_registration_literal(
            text, "IssuerRegistration"
        ):
            errors.append(f"constructible message registration: {path.relative_to(ROOT)}")
        if path != allowed_settlement_literal and contains_registration_literal(
            text, "SettlementIssuerRegistration"
        ):
            errors.append(
                f"constructible settlement registration: {path.relative_to(ROOT)}"
            )
        if "use codex_hepta_authbus::AuthBusAuthorityStore" in text:
            errors.append(f"external raw authority writer: {path.relative_to(ROOT)}")

    lib = source(AUTHBUS / "lib.rs")
    if "pub(crate) use authority_store::AuthBusAuthorityStore;" not in lib:
        errors.append("raw authority writer is not crate-private")
    store_root = source(AUTHBUS / "authority_store.rs")
    if not re.search(r"(?m)^pub\(crate\) struct AuthBusAuthorityStore\s*\{", store_root):
        errors.append("raw authority writer type is not crate-private")
    store_sources = "\n".join(source(AUTHBUS / name) for name in STORE_FILES)
    crate_private_store = set(
        re.findall(r"(?m)^\s*pub\(crate\) async fn ([a-z][a-z0-9_]*)\s*\(", store_sources)
    )
    missing_store = sorted(STORE_OPERATIONS - crate_private_store)
    if missing_store:
        errors.append("store operations are not crate-private: " + ", ".join(missing_store))
    for name in STORE_FILES[:-1]:
        source_text = source(AUTHBUS / name)
        public_store = sorted(
            STORE_OPERATIONS
            & set(re.findall(r"(?m)^\s*pub async fn ([a-z][a-z0-9_]*)\s*\(", source_text))
        )
        if public_store:
            errors.append(f"public raw writer methods in {name}: " + ", ".join(public_store))
    operations_source = source(AUTHBUS / "operations.rs")
    if "impl AuthBusAuthorityStore {\n    pub(crate) async fn operational_snapshot" not in operations_source:
        errors.append("operational snapshot raw writer method is not crate-private")
    if re.search(r"(?m)^pub use authority_store::AuthBusAuthorityStore;", lib):
        errors.append("raw authority writer is publicly re-exported")

    for type_name, path in [
        ("IssuerRegistration", AUTHBUS / "signed.rs"),
        ("SettlementIssuerRegistration", AUTHBUS / "settlement.rs"),
    ]:
        match = re.search(
            rf"pub struct {type_name}\s*\{{(?P<body>.*?)\n\}}",
            source(path),
            flags=re.DOTALL,
        )
        if match is None:
            errors.append(f"missing sealed type {type_name}")
        elif re.search(r"(?m)^\s*pub(?:\([^)]*\))?\s+\w+\s*:", match.group("body")):
            errors.append(f"trusted fields are externally writable on {type_name}")

    discovered: set[str] = set()
    for path in [AUTHBUS / "host.rs", AUTHBUS / "operations.rs"]:
        discovered.update(
            re.findall(r"(?m)^\s*pub async fn ([a-z][a-z0-9_]*)\s*\(", source(path))
        )
    missing = sorted(HOST_OPERATIONS - discovered)
    unexpected = sorted(discovered - HOST_OPERATIONS)
    if missing:
        errors.append("missing host operations: " + ", ".join(missing))
    if unexpected:
        errors.append("unexpected host operations: " + ", ".join(unexpected))
    return errors


def inventory() -> dict[str, object]:
    return {
        "schema": "hepta.authbus.public-api-inventory.v1",
        "module": "auth.authbus",
        "writer": {
            "type": "AuthBusAuthorityStore",
            "visibility": "crate_private",
            "publicMutationHost": "AuthBusAuthorityHost",
        },
        "sealedRegistrations": [
            {
                "type": "IssuerRegistration",
                "source": "codex-rs/hepta-authbus/src/signed.rs",
                "trustedFieldsPublic": False,
                "construction": ["durable_registry", "private_persisted_registry"],
            },
            {
                "type": "SettlementIssuerRegistration",
                "source": "codex-rs/hepta-authbus/src/settlement.rs",
                "trustedFieldsPublic": False,
                "construction": ["durable_registry"],
            },
        ],
        "hostOperations": sorted(HOST_OPERATIONS),
        "periodicOwner": "AuthBusAuthorityWorker",
        "activation": False,
    }


def encoded_inventory() -> str:
    return json.dumps(inventory(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()

    errors = verify_boundaries()
    if errors:
        raise SystemExit("closed-world inventory failed:\n" + "\n".join(errors))
    expected = encoded_inventory()
    if args.write:
        INVENTORY.write_text(expected, encoding="utf-8")
        return
    if not INVENTORY.exists() or INVENTORY.read_text(encoding="utf-8") != expected:
        raise SystemExit(
            "PUBLIC_API_INVENTORY.json is stale; run scripts/check-authbus-closed-world.py --write"
        )


if __name__ == "__main__":
    main()
