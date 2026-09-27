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


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def verify_boundaries() -> list[str]:
    errors: list[str] = []
    allowed_message_literal = AUTHBUS / "signed.rs"
    allowed_settlement_literal = AUTHBUS / "settlement.rs"
    for path in sorted((ROOT / "codex-rs").rglob("*.rs")):
        text = source(path)
        if path != allowed_message_literal and re.search(
            r"\bIssuerRegistration\s*\{", text
        ):
            errors.append(f"constructible message registration: {path.relative_to(ROOT)}")
        if path != allowed_settlement_literal and re.search(
            r"\bSettlementIssuerRegistration\s*\{", text
        ):
            errors.append(
                f"constructible settlement registration: {path.relative_to(ROOT)}"
            )
        if "use codex_hepta_authbus::AuthBusAuthorityStore" in text:
            errors.append(f"external raw authority writer: {path.relative_to(ROOT)}")

    lib = source(AUTHBUS / "lib.rs")
    if "pub(crate) use authority_store::AuthBusAuthorityStore;" not in lib:
        errors.append("raw authority writer is not crate-private")
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
