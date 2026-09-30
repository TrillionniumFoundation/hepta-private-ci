#!/usr/bin/env python3
'''Validate exact-source closure, the single Cargo surface and CI role split.'''
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FAKE_FEATURES = {
    "bao-https-client",
    "authbus-admission",
    "durable-leases",
    "durable-operations",
    "final-use-consumer",
    "registered-final-use-host",
    "sqlite-owner",
    "sqlite-product-runtime",
}
QUALIFIERS = (
    ROOT / ".github/workflows/secrets-heptabao-five-closure-qualified.yml",
    ROOT / ".github/workflows/secrets-heptabao-candidate-attestation.yml",
)
NATIVE_QUALIFIER = ROOT / "codex-rs/hepta-bao-adapter/qa/qualify.py"
MATERIALIZER = (
    ROOT / ".github/workflows/secrets-heptabao-development-materialize.yml"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_cargo_surface() -> None:
    manifest = tomllib.loads(
        (ROOT / "codex-rs/hepta-bao-adapter/Cargo.toml").read_text(
            encoding="utf-8"
        )
    )
    features = manifest.get("features", {})
    require(
        not features,
        "hepta-bao-adapter must remain one complete build surface",
    )


def validate_materialized_source() -> None:
    host = (
        ROOT / "codex-rs/hepta-bao-adapter/src/final_use_host.rs"
    ).read_text(encoding="utf-8")
    runtime = (
        ROOT / "codex-rs/hepta-bao-adapter/src/sqlite_product_runtime.rs"
    ).read_text(encoding="utf-8")
    combined = host + "\n" + runtime
    for declaration in (
        "OutcomePending(Box<BaoConsumptionOperationV1>)",
        "TerminalFailure(Box<BaoConsumptionOperationV1>)",
    ):
        require(
            declaration in host,
            f"materialized error declaration missing: {declaration}",
        )
    require(
        "OutcomePending(BaoConsumptionOperationV1)" not in host,
        "unboxed OutcomePending declaration remains",
    )
    require(
        "TerminalFailure(BaoConsumptionOperationV1)" not in host,
        "unboxed TerminalFailure declaration remains",
    )
    unboxed = re.search(
        r"BaoProductHostError::(?:OutcomePending|TerminalFailure)"
        r"\((?!Box::new\()",
        combined,
    )
    require(unboxed is None, "unboxed product-error constructor remains")


def validate_qualifiers() -> None:
    for path in QUALIFIERS:
        text = path.read_text(encoding="utf-8")
        require(
            "permissions:\n  contents: read" in text,
            f"{path.name}: contents must be read-only",
        )
        require(
            "persist-credentials: false" in text,
            f"{path.name}: credentials must not persist",
        )
        for forbidden in (
            "git push",
            "git commit",
            "close_secrets_heptabao_candidate.py",
            "close_secrets_heptabao_clippy.py",
            "--features",
            "FEATURES:",
            "contents: write",
        ):
            require(
                forbidden not in text,
                f"{path.name}: forbidden qualifier token {forbidden!r}",
            )
        for feature in FAKE_FEATURES:
            require(
                feature not in text,
                f"{path.name}: undeclared feature {feature!r}",
            )

    source_workflow = QUALIFIERS[0].read_text(encoding="utf-8")
    for required in (
        "git diff --exit-code",
        "git diff --cached --exit-code",
        "git status --porcelain=v1 --untracked-files=all",
        "build_readiness_manifest.py",
    ):
        require(
            required in source_workflow,
            f"read-only source workflow is missing {required!r}",
        )

    native = NATIVE_QUALIFIER.read_text(encoding="utf-8")
    for required in (
        '"cargo",\n            "metadata"',
        '"--locked"',
        '"--no-deps"',
        '"cargo",\n            "fmt"',
        '"cargo",\n            "test"',
        '"cargo",\n            "clippy"',
        '"-D",\n            "warnings"',
    ):
        require(
            required in native,
            f"native qualifier is missing command fragment {required!r}",
        )
    for feature in FAKE_FEATURES:
        require(
            feature not in native,
            f"native qualifier uses undeclared feature {feature!r}",
        )


def validate_materializer_role() -> None:
    text = MATERIALIZER.read_text(encoding="utf-8")
    require(
        "permissions:\n  contents: write" in text,
        "development materializer needs bounded write permission",
    )
    require(
        ".hepta-staging/secrets-heptabao-review-materialize.trigger" in text,
        "materializer must use an explicit isolated trigger",
    )
    for required in (
        "close_secrets_heptabao_candidate.py",
        "close_secrets_heptabao_clippy.py",
        "generate_secrets_heptabao_module.py --write",
        "git push origin HEAD:codex/secrets-heptabao-production-qualified-20260930",
    ):
        require(required in text, f"materializer is missing {required!r}")
    for forbidden in (
        "cargo test",
        "cargo clippy",
        "build_readiness_manifest.py",
        "productionQualified=true",
    ):
        require(
            forbidden not in text,
            f"materializer must not qualify: {forbidden!r}",
        )


def main() -> int:
    validate_cargo_surface()
    validate_materialized_source()
    validate_qualifiers()
    validate_materializer_role()
    print(
        "validated materialized exact source, single complete Cargo surface, "
        "and independent read-only qualification"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
