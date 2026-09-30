#!/usr/bin/env python3
"""Fail closed on AuthBus host leakage and product-entry bypass."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT / "codex-rs"
AUTHBUS = CODEX / "hepta-authbus"
QUALIFICATION = CODEX / "hepta-authbus-p1-3-qualification"
BAO = CODEX / "hepta-bao-adapter"
ALLOWED_FULL_HOST_ROOTS = (AUTHBUS, QUALIFICATION)
RAW_BAO_OPERATION_ENTRY = "consume_kv_v2_with_authbus("
RAW_BAO_ALLOWED = {
    BAO / "src/https_consumer.rs",
    BAO / "src/durable_authbus.rs",
}


def production_rust(path: Path) -> bool:
    relative = path.relative_to(CODEX)
    if "tests" in relative.parts or "benches" in relative.parts:
        return False
    return not path.name.endswith(("_tests.rs", "test_support.rs"))


def inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def main() -> None:
    errors: list[str] = []
    for path in sorted(CODEX.rglob("*.rs")):
        if not production_rust(path):
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)

        if not any(inside(path, root) for root in ALLOWED_FULL_HOST_ROOTS):
            if "AuthBusAuthorityHost" in text:
                errors.append(f"external production code holds full AuthBus host: {relative}")
            if "bootstrap_retryable" in text:
                errors.append(
                    f"external production code may not bootstrap AuthBus authority state: {relative}"
                )
            for forbidden in ("AuthBusAdminPort", "AuthBusMaintenancePort"):
                if forbidden in text:
                    errors.append(f"external production code holds {forbidden}: {relative}")
            for forbidden_call in (".admin()", ".maintenance()"):
                if forbidden_call in text:
                    errors.append(
                        f"external production code mints privileged AuthBus capability "
                        f"{forbidden_call}: {relative}"
                    )

        if RAW_BAO_OPERATION_ENTRY in text and path not in RAW_BAO_ALLOWED:
            errors.append(
                f"production code bypasses sealed durable Bao operation entry: {relative}"
            )
        if "BaoAuthBusAdmission" in text and not inside(path, BAO):
            errors.append(
                f"external production code depends on low-level Bao AuthBus admission: {relative}"
            )

    cargo = (AUTHBUS / "Cargo.toml").read_text(encoding="utf-8")
    if not re.search(
        r"(?ms)^\[features\]\s*.*?^default\s*=\s*\[\]\s*$.*?^legacy-preverified-replay\s*=\s*\[\]\s*$",
        cargo,
    ):
        errors.append("AuthBus legacy replay is not an explicit non-default feature")

    lib = (AUTHBUS / "src/lib.rs").read_text(encoding="utf-8")
    required = (
        '#[cfg(feature = "legacy-preverified-replay")]\nmod legacy_replay;',
        '#[cfg(feature = "legacy-preverified-replay")]\n#[allow(deprecated)]\npub use legacy_replay::PreverifiedAuthEnvelope;',
        '#[cfg(feature = "legacy-preverified-replay")]\n#[allow(deprecated)]\npub use legacy_replay::ReplayWindow;',
        '#[cfg(feature = "legacy-preverified-replay")]\n#[allow(deprecated)]\npub use legacy_replay::TrustedReplayContext;',
        "pub use bootstrap::bootstrap_retryable;",
    )
    for marker in required:
        if marker not in lib:
            errors.append(f"missing feature/facade marker: {marker!r}")

    signed = (AUTHBUS / "src/signed.rs").read_text(encoding="utf-8")
    for forbidden in ("PreverifiedAuthEnvelope", "ReplayWindow", "TrustedReplayContext"):
        if forbidden in signed:
            errors.append(f"signed admission still depends on structural legacy API: {forbidden}")
    if "verify_strict" not in signed:
        errors.append("signed admission no longer performs strict Ed25519 verification")

    legacy = (AUTHBUS / "src/legacy_replay.rs").read_text(encoding="utf-8")
    if legacy.count("#[deprecated(") < 3:
        errors.append("legacy replay public types are not all explicitly deprecated")

    host = (AUTHBUS / "src/host.rs").read_text(encoding="utf-8")
    if not re.search(r"(?m)^\s*pub\(crate\) async fn bootstrap\s*\(", host):
        errors.append("raw AuthBus bootstrap constructor is not crate-private")
    if re.search(r"(?m)^\s*pub async fn bootstrap\s*\(", host):
        errors.append("raw AuthBus bootstrap constructor remains public")

    bao_lib = (BAO / "src/lib.rs").read_text(encoding="utf-8")
    for marker in (
        "pub use durable_authbus::BaoDurableAuthBusAdmission;",
        "pub use durable_authbus::BaoDurableAuthBusReceipt;",
        "pub use durable_authbus::BaoDurableAuthBusError;",
    ):
        if marker not in bao_lib:
            errors.append(f"Bao durable operation entry is not exported: {marker!r}")
    durable_bao = (BAO / "src/durable_authbus.rs").read_text(encoding="utf-8")
    for marker in (
        "EnteredAuthBusOperationHandle",
        "validate_entered_authbus_operation",
        "consume_kv_v2_with_durable_authbus_operation",
        "reconciliation_required: true",
    ):
        if marker not in durable_bao:
            errors.append(f"Bao durable operation entry lost marker: {marker!r}")

    if errors:
        raise SystemExit("AuthBus composition-root contract failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    main()
