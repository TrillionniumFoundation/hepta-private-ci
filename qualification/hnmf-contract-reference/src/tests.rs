use super::*;

#[test]
fn production_crate_is_the_only_canonical_contract_owner() {
    verify_canonical_contract_owner()
        .unwrap_or_else(|error| panic!("canonical contract owner must be closed: {error}"));
}

#[test]
fn every_hnmf_protocol_is_bound_in_both_registries() {
    for protocol in REQUIRED_PROTOCOLS {
        let marker = format!("\"id\": \"{protocol}\"");
        assert!(HNMF_REGISTRY.contains(&marker));
        assert!(PROTOCOL_REGISTRY.contains(&marker));
    }
}

#[test]
fn ctype_qualification_cases_live_with_the_production_types() {
    for case in CTYPE_CASES {
        assert!(HNMF_TEST_SOURCE.contains(case) || WIRE_TEST_SOURCE.contains(case));
    }
}

#[test]
fn memory_and_learning_topology_protocols_are_distinct() {
    assert!(PROTOCOL_REGISTRY.contains("\"id\": \"TopologyProposalV1\""));
    assert!(PROTOCOL_REGISTRY.contains("\"id\": \"MemoryTopologyProposalV1\""));
    assert!(!CANONICAL_HNMF_SOURCE.contains("pub struct TopologyProposalV1"));
}
