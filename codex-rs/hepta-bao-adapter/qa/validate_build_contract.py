#!/usr/bin/env python3
'''Validate the single complete build surface and read-only qualification split.'''
from __future__ import annotations

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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> int:
    manifest = tomllib.loads(
        (
            ROOT / "codex-rs/hepta-bao-adapter/Cargo.toml"
        ).read_text(encoding="utf-8")
    )
    features = manifest.get("features", {})
    require(
        not features,
        "hepta-bao-adapter must remain one complete build surface",
    )

    qualifiers = [
        ROOT
        / ".github/workflows/secrets-heptabao-five-closure-qualified.yml",
        ROOT
        / ".github/workflows/secrets-heptabao-candidate-attestation.yml",
    ]
    for path in qualifiers:
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
            "--features",
            "FEATURES:",
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

    materializer_path = (
        ROOT
        / ".github/workflows/secrets-heptabao-development-materialize.yml"
    )
    materializer = materializer_path.read_text(encoding="utf-8")
    require(
        "permissions:\n  contents: write" in materializer,
        "materializer needs bounded write permission",
    )
    require(
        "close_secrets_heptabao_candidate.py" in materializer,
        "materializer must invoke the development script",
    )
    for forbidden in (
        "cargo test",
        "cargo clippy",
        "build_readiness_manifest.py",
    ):
        require(
            forbidden not in materializer,
            f"materializer must not qualify: {forbidden!r}",
        )

    print(
        "validated single complete Cargo surface and read-only "
        "qualification split"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
