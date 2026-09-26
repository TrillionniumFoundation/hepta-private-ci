#!/usr/bin/env python3
"""Fail-closed post-migration verifier for cognitive.read Agentd hardening."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def require(path: str, *needles: str) -> None:
    body = text(path)
    missing = [needle for needle in needles if needle not in body]
    if missing:
        formatted = "\n".join(f"  - {needle!r}" for needle in missing)
        raise SystemExit(f"{path}: missing required hardening markers:\n{formatted}")


def forbid(path: str, *needles: str) -> None:
    body = text(path)
    present = [needle for needle in needles if needle in body]
    if present:
        formatted = "\n".join(f"  - {needle!r}" for needle in present)
        raise SystemExit(f"{path}: stale or forbidden hardening markers remain:\n{formatted}")


def main() -> None:
    cargo = "codex-rs/hepta-agentd/Cargo.toml"
    require(
        cargo,
        "default = []",
        "qualification-cognitive-write = []",
        'codex-hepta-learning-ledger = { path = "../hepta-learning-ledger" }',
        "tracing = { workspace = true }",
    )
    forbid(
        cargo,
        "production-cognitive-write",
        "qualification-legacy-learning-write",
        'features = ["qualification-legacy-write"]',
    )

    app_runtime = "codex-rs/hepta-agentd/src/app_runtime.rs"
    require(
        app_runtime,
        'cfg!(feature = "qualification-cognitive-write")',
        "Cargo features never grant production mutation authority",
    )
    forbid(app_runtime, "production-cognitive-write")

    for path in (
        "codex-rs/hepta-agentd/src/runtime.rs",
        "codex-rs/hepta-agentd/src/runtime_tests.rs",
        "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
    ):
        require(path, "qualification-cognitive-write")
        forbid(path, "production-cognitive-write")

    require(
        "codex-rs/hepta-agentd/src/lib.rs",
        "mod cognitive_context;",
        "mod cognitive_context_metrics;",
    )
    require(
        "codex-rs/hepta-agentd/src/cognitive_context.rs",
        "type AdmissionKey = (String, u64, String);",
        "fn admitted_record_index(",
        "fn planned_context_encoded_len(",
        "let admission_index = admitted_record_index(admission_read.records());",
        "record_revalidation_failure",
        "record_budget_rejection",
        "record_stale_cut_rejection",
        "record_selected",
        "record_latency",
        "planned_budget_accounts_for_the_complete_envelope",
    )
    forbid(
        "codex-rs/hepta-agentd/src/cognitive_context.rs",
        "MAX_CONTEXT_JSON_BYTES - 1024",
        "admission_read.records().iter().any",
    )

    require(
        "codex-rs/hepta-agentd/src/cognitive_context_metrics.rs",
        "record_request",
        "record_read",
        "record_budget_rejection",
        "record_revalidation_failure",
        "record_stale_cut_rejection",
        "snapshot",
    )

    print("cognitive.read Agentd hardening verification passed")


if __name__ == "__main__":
    main()
