#!/usr/bin/env python3
"""Deterministic postprocessing for the one-shot memory.federation closure patch."""

from pathlib import Path


def require_once(text: str, needle: str, label: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"expected exactly one {label}, found {count}")


def main() -> None:
    legacy = Path("codex-rs/hepta-memory-federation/src/legacy_v1.rs")
    legacy_text = legacy.read_text(encoding="utf-8")
    if "#![allow(deprecated)]" not in legacy_text:
        head, tail = legacy_text.split("\n\n", 1)
        legacy.write_text(
            head + "\n\n#![allow(deprecated)]\n\n" + tail,
            encoding="utf-8",
        )

    runtime = Path("codex-rs/hepta-memory/src/cognitive_runtime.rs")
    runtime_text = runtime.read_text(encoding="utf-8")
    unconditional = (
        "    aggregate.partial_peers = aggregate\n"
        "        .partial_peers\n"
        "        .saturating_add(attempt.partial_peers);\n"
    )
    valid_branch = (
        "    if validity == FederatedValidityV2::Valid {\n"
        "        aggregate.completed_peers = aggregate\n"
    )
    valid_replacement = (
        "    if validity == FederatedValidityV2::Valid {\n"
        "        aggregate.partial_peers = aggregate\n"
        "            .partial_peers\n"
        "            .saturating_add(attempt.partial_peers);\n"
        "        aggregate.completed_peers = aggregate\n"
    )
    require_once(runtime_text, unconditional, "unconditional partial-peer merge")
    require_once(runtime_text, valid_branch, "valid coverage branch")
    runtime_text = runtime_text.replace(unconditional, "", 1)
    runtime_text = runtime_text.replace(valid_branch, valid_replacement, 1)
    runtime.write_text(runtime_text, encoding="utf-8")

    tests = Path("codex-rs/hepta-memory/src/cognitive_runtime_identity_tests.rs")
    tests_text = tests.read_text(encoding="utf-8")
    marker = "fn federation_host_profile_rejects_zero_and_architecture_widening()"
    if marker not in tests_text:
        tests_text += r'''

#[test]
fn federation_host_profile_rejects_zero_and_architecture_widening() {
    use std::time::Duration;

    assert!(MemoryFederationHostProfile::try_new(Duration::ZERO, 1, 1, 1, 1, 1).is_err());
    assert!(MemoryFederationHostProfile::try_new(
        crate::MAX_PRODUCT_FEDERATION_TOTAL_BUDGET + Duration::from_millis(1),
        1,
        1,
        1,
        1,
        1,
    )
    .is_err());
    assert!(MemoryFederationHostProfile::try_new(
        Duration::from_millis(1),
        crate::MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS + 1,
        1,
        1,
        1,
        1,
    )
    .is_err());
    assert!(MemoryFederationHostProfile::try_new(
        Duration::from_millis(1),
        1,
        1,
        2,
        1,
        1,
    )
    .is_err());

    let constrained = MemoryFederationHostProfile::try_new(
        Duration::from_millis(250),
        4,
        2,
        2,
        2,
        2,
    )
    .expect("bounded profile");
    assert_eq!(constrained.total_budget(), Duration::from_millis(250));
    assert_eq!(constrained.max_owner_candidates(), 4);
    assert_eq!(constrained.max_admitted_peers(), 2);
}
'''
        tests.write_text(tests_text, encoding="utf-8")


if __name__ == "__main__":
    main()
