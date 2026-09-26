#!/usr/bin/env python3
"""Deterministic postprocessing for the one-shot memory.federation closure patch."""

from pathlib import Path
import re
import subprocess


def require_once(text: str, needle: str, label: str) -> None:
    count = text.count(needle)
    if count != 1:
        raise SystemExit(f"expected exactly one {label}, found {count}")


def main() -> None:
    # Agentd is shared by several independently converging modules. Keep this
    # closure inside the memory-owned contract and let Agentd compose the
    # validated default until a separate host-wiring change is reviewed.
    subprocess.run(
        ["git", "checkout", "--", "codex-rs/hepta-agentd/src/runtime.rs"],
        check=True,
    )

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
    require_once(runtime_text, "if total_budget.is_zero()", "zero budget check")
    runtime_text = runtime_text.replace(
        "if total_budget.is_zero()",
        "if total_budget < Duration::from_millis(1)",
        1,
    )
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
        Duration::from_nanos(1),
        1,
        1,
        1,
        1,
        1,
    )
    .is_err());
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

    profile_pattern = re.compile(
        r"Agentd resolves the profile before runtime composition and rejects invalid or\n"
        r"architecture-widening values\. The supported environment fields are:\n\n"
        r"- `HEPTA_MEMORY_FEDERATION_TOTAL_BUDGET_MS`;\n"
        r"- `HEPTA_MEMORY_FEDERATION_MAX_OWNER_CANDIDATES`;\n"
        r"- `HEPTA_MEMORY_FEDERATION_MAX_ADMITTED_PEERS`;\n"
        r"- `HEPTA_MEMORY_FEDERATION_DISCOVERY_CONCURRENCY`;\n"
        r"- `HEPTA_MEMORY_FEDERATION_ATTEMPT_CONCURRENCY`;\n"
        r"- `HEPTA_MEMORY_FEDERATION_REVALIDATION_CONCURRENCY`\."
    )
    replacement = (
        "The product caller can supply the validated profile explicitly through "
        "`with_federation_sources_profile`. Agentd currently composes the bounded "
        "default profile; external host configuration is not claimed until that "
        "separate host-wiring change is reviewed and qualified."
    )
    replaced = 0
    for name in [
        "docs/modules/memory.federation/TECHNICAL.md",
        "docs/modules/memory.federation/V2_HARDENING.md",
        "qualification/module-execution-dossiers/detail/memory.federation.md",
    ]:
        path = Path(name)
        text = path.read_text(encoding="utf-8")
        text, count = profile_pattern.subn(replacement, text)
        if count:
            path.write_text(text, encoding="utf-8")
            replaced += count
    if replaced == 0:
        raise SystemExit("generated documentation did not contain the Agentd host-profile claim")


if __name__ == "__main__":
    main()
