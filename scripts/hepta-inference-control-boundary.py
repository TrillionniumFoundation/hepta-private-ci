#!/usr/bin/env python3
"""Fail-closed source guard for the Hepta inference provider choke point."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE_ROOT = ROOT / "codex-rs"
ALLOWED_TURN_START = pathlib.PurePosixPath(
    "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
)
TURN_START_NEEDLE = "ClientRequest::TurnStart"

REQUIRED_ORDER = (
    "policy.claim_turn(",
    "control.dispatch_native(",
    "ClientRequest::TurnStart",
)


def production_rust_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for package in CODE_ROOT.glob("hepta-*"):
        if not package.is_dir():
            continue
        for path in package.rglob("*.rs"):
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in rel or rel.endswith("_tests.rs"):
                continue
            files.append(path)
    return files


def direct_turn_start_paths(files: list[pathlib.Path]) -> list[str]:
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if TURN_START_NEEDLE in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    return sorted(offenders)


def verify() -> None:
    files = production_rust_files()
    actual = direct_turn_start_paths(files)
    expected = [str(ALLOWED_TURN_START)]
    if actual != expected:
        raise SystemExit(
            "provider turn/start escaped inference.control choke point: "
            f"expected={expected!r} actual={actual!r}"
        )

    boundary = (ROOT / ALLOWED_TURN_START).read_text(encoding="utf-8")
    positions = [boundary.find(needle) for needle in REQUIRED_ORDER]
    if any(position < 0 for position in positions):
        raise SystemExit(
            "native provider boundary is missing required authority/durability steps: "
            f"{dict(zip(REQUIRED_ORDER, positions, strict=True))}"
        )
    if positions != sorted(positions):
        raise SystemExit(
            "native provider boundary order must be final-use claim -> durable dispatch -> turn/start"
        )

    worker = (
        ROOT / "codex-rs/hepta-infer-worker-host/src/native_run_control.rs"
    ).read_text(encoding="utf-8")
    for needle in (
        "admission.policy.admission_binding(",
        "control.reserve_native(",
        "admission.maximum_budget_units",
        "self.reconcile_existing(&record)",
    ):
        if needle not in worker:
            raise SystemExit(f"native inference worker missing required control step: {needle}")

    core = (ROOT / "codex-rs/hepta-infer-core/src/native_control.rs").read_text(
        encoding="utf-8"
    )
    for needle in (
        "enforce_quota(&self.records, &request)?",
        "validate_dispatch_authority(record, &dispatch)?",
        "held_budget_units(",
        "budget_units > binding.quota.reserved_day_budget",
        "compact_native_journal(",
    ):
        if needle not in core:
            raise SystemExit(f"durable inference owner missing required invariant: {needle}")


    policy = (
        ROOT / "codex-rs/hepta-infer-worker-host/src/native_policy.rs"
    ).read_text(encoding="utf-8")
    for needle in (
        "self.resource.subject.as_ref() != Some(&self.quota.subject)",
        "self.resource.quota_sha256 != quota_digest",
        "self.quota.reserved_day_budget < maximum_budget_units",
        "authority.claim(&signed, &binding)?",
        "authority.with_verified_use(",
    ):
        if needle not in policy:
            raise SystemExit(f"native inference policy missing required invariant: {needle}")

    # The App Server turn gate is not the physical network boundary. Hepta
    # product hosts must also install enforce-mode provider governance, and
    # Core must reject a Hepta-governed send when a host forgets that
    # contributor instead of silently falling back to NoPolicy.
    for host_path in (
        "codex-rs/app-server/src/extensions.rs",
        "codex-rs/mcp-server/src/message_processor.rs",
    ):
        host = (ROOT / host_path).read_text(encoding="utf-8")
        if "codex_hepta_governance::install_enforced(" not in host:
            raise SystemExit(
                f"Hepta product host is not using enforce-mode provider governance: {host_path}"
            )

    lifecycle = (
        ROOT / "codex-rs/core/src/model_provider_policy/lifecycle.rs"
    ).read_text(encoding="utf-8")
    for needle in (
        "pub(crate) fn needs_gate(&self) -> bool",
        "self.required || !self.contributors.is_empty()",
        '"model_provider_policy_required_missing"',
    ):
        if needle not in lifecycle:
            raise SystemExit(f"physical provider-policy fail-closed gate missing: {needle}")

    physical_client = (ROOT / "codex-rs/core/src/client.rs").read_text(encoding="utf-8")
    for needle in (
        "context.require_active_policy",
        "active.needs_gate()",
        "provider_policy_context.require_active_policy",
    ):
        if needle not in physical_client:
            raise SystemExit(f"physical provider send missing required-policy gate: {needle}")


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        allowed = root / "native_app_server.rs"
        escaped = root / "escaped.rs"
        allowed.write_text("ClientRequest::TurnStart", encoding="utf-8")
        escaped.write_text("", encoding="utf-8")
        found = [
            path.name
            for path in (allowed, escaped)
            if TURN_START_NEEDLE in path.read_text(encoding="utf-8")
        ]
        if found != ["native_app_server.rs"]:
            raise SystemExit("source guard self-test failed to find allowed boundary")
        escaped.write_text("ClientRequest::TurnStart", encoding="utf-8")
        found = [
            path.name
            for path in (allowed, escaped)
            if TURN_START_NEEDLE in path.read_text(encoding="utf-8")
        ]
        if found != ["native_app_server.rs", "escaped.rs"]:
            raise SystemExit("source guard self-test failed to detect escape")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if command == "verify":
        verify()
    elif command == "self-test":
        self_test()
    else:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
