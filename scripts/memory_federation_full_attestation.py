#!/usr/bin/env python3
"""Extend the V2 qualification receipt with the authenticated wire candidate."""

from __future__ import annotations

import memory_federation_attestation as base

base.QUALIFIED_PATHS = (
    *base.QUALIFIED_PATHS,
    "codex-rs/hepta-memory-federation-wire",
    "scripts/memory_federation_full_attestation.py",
    "scripts/run_memory_federation_qualification.sh",
)

base.COMMANDS = (
    *base.COMMANDS,
    "cargo fmt --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml -- --check",
    "cargo metadata --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --format-version 1 --no-deps",
    "cargo test --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --lib",
    "cargo clippy --manifest-path codex-rs/hepta-memory-federation-wire/Cargo.toml --all-targets -- -D warnings",
)


if __name__ == "__main__":
    raise SystemExit(base.main())
