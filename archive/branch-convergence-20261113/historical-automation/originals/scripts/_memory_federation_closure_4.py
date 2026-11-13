#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    (ROOT / rel).write_text(value, encoding="utf-8")


def replace_exact(value: str, old: str, new: str, count: int = 1) -> str:
    actual = value.count(old)
    if actual != count:
        raise RuntimeError(f"expected {count} replacements, found {actual}: {old[:120]!r}")
    return value.replace(old, new, count)


identity_rel = "codex-rs/hepta-memory/src/cognitive_runtime_identity.rs"
identity = read(identity_rel)
identity = replace_exact(
    identity,
    """                    omitted_owner_candidates: left_omitted_owner_candidates,
                },
                Self::AvailableFederatedV2 {
                    store: right_store,
                    consumer_agent_id: right_consumer_agent_id,
                    owner_layouts: right_owner_layouts,
                    omitted_owner_candidates: right_omitted_owner_candidates,
                },
""",
    """                    omitted_owner_candidates: left_omitted_owner_candidates,
                    profile: left_profile,
                },
                Self::AvailableFederatedV2 {
                    store: right_store,
                    consumer_agent_id: right_consumer_agent_id,
                    owner_layouts: right_owner_layouts,
                    omitted_owner_candidates: right_omitted_owner_candidates,
                    profile: right_profile,
                },
""",
)
identity = replace_exact(
    identity,
    """                    && left_owner_layouts.as_slice() == right_owner_layouts.as_slice()
                    && left_omitted_owner_candidates == right_omitted_owner_candidates
""",
    """                    && left_owner_layouts.as_slice() == right_owner_layouts.as_slice()
                    && left_omitted_owner_candidates == right_omitted_owner_candidates
                    && left_profile == right_profile
""",
)
write(identity_rel, identity)

identity_tests_rel = "codex-rs/hepta-memory/src/cognitive_runtime_identity_tests.rs"
identity_tests = read(identity_tests_rel)
identity_tests = replace_exact(
    identity_tests,
    "use crate::CognitiveUnavailableReason;\n",
    "use crate::CognitiveUnavailableReason;\nuse crate::FederationRuntimeProfile;\n",
)
identity_tests = replace_exact(
    identity_tests,
    """        owner_layouts: Arc::new(owners),
        omitted_owner_candidates: 1,
    };
""",
    """        owner_layouts: Arc::new(owners),
        omitted_owner_candidates: 1,
        profile: FederationRuntimeProfile::default(),
    };
""",
)
write(identity_tests_rel, identity_tests)

runtime_tests_rel = "codex-rs/hepta-memory/src/cognitive_runtime_tests.rs"
runtime_tests = read(runtime_tests_rel)
runtime_tests = replace_exact(
    runtime_tests,
    "use std::sync::Arc;\n",
    "use std::sync::Arc;\nuse std::time::Duration;\n",
)
runtime_tests = replace_exact(
    runtime_tests,
    "use crate::FederationGrantScope;\n",
    "use crate::FederationGrantScope;\nuse crate::FederationRuntimeProfile;\n",
)
runtime_tests += r'''

#[test]
fn federation_runtime_profile_enforces_architecture_bounds() {
    assert!(
        FederationRuntimeProfile::new(Duration::ZERO, 1, 1, 1, 1, 1).is_err()
    );
    assert!(
        FederationRuntimeProfile::new(Duration::from_secs(2), 129, 1, 1, 1, 1).is_err()
    );
    assert!(
        FederationRuntimeProfile::new(Duration::from_secs(2), 1, 17, 1, 1, 1).is_err()
    );
    let profile = FederationRuntimeProfile::for_host_capacity(4, 1_024);
    assert_eq!(profile.total_budget(), Duration::from_secs(2));
    assert!((1..=16).contains(&profile.discovery_concurrency()));
    assert!((1..=16).contains(&profile.attempt_concurrency()));
    assert!((1..=16).contains(&profile.revalidation_concurrency()));
}
'''
write(runtime_tests_rel, runtime_tests)

v2_tests_rel = "codex-rs/hepta-memory-federation/src/v2_tests.rs"
v2_tests = read(v2_tests_rel)
v2_tests += r'''

#[test]
fn source_side_omission_is_digest_bound_and_propagated_as_partial_coverage() {
    let query = query();
    let mut response = terminal_response(&query);
    response.items.truncate(2);
    response.omitted_items = 3;
    response.completeness = FederatedCompletenessV2::Partial;
    response = response
        .seal()
        .unwrap_or_else(|error| panic!("valid partial response: {error}"));
    let original_digest = response.response_digest;
    let transport = FixtureTransport {
        result: Ok(FederationTransportResultV2::Terminal(response.clone())),
    };
    let result = execute(&transport, query.clone(), &lease(&query))
        .unwrap_or_else(|error| panic!("valid partial result: {error}"));
    assert_eq!(result.completeness, FederatedCompletenessV2::Partial);
    assert_eq!(result.coverage.truncated_items, 3);

    response.omitted_items = 4;
    assert_ne!(response.compute_response_digest(), original_digest);
}
'''
write(v2_tests_rel, v2_tests)

print("stage 4 applied")
