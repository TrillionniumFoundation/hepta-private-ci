use super::*;
use std::collections::BTreeSet;

#[test]
fn every_cognitive_port_has_a_nonempty_exact_schema_set() {
    assert_eq!(MODULE_PORT_SCHEMA_BINDINGS.len(), 4);
    let mut ports = BTreeSet::new();
    for binding in MODULE_PORT_SCHEMA_BINDINGS {
        assert!(ports.insert(binding.port_id));
        assert!(!binding.schemas.is_empty());
        let schemas = binding.schemas.iter().copied().collect::<BTreeSet<_>>();
        assert_eq!(schemas.len(), binding.schemas.len());
    }
}

#[test]
fn critical_owner_routes_are_explicit() {
    assert_eq!(
        schemas_for_port("ModulePort::cognitive.types::cognitive.store"),
        Some(COGNITIVE_STORE_SCHEMAS)
    );
    assert!(
        COGNITIVE_STORE_SCHEMAS.contains(&"MemoryEventV1")
            && COGNITIVE_STORE_SCHEMAS.contains(&"ForgetPropagationReceiptV1")
    );
    assert!(
        LEARNING_LEDGER_SCHEMAS.contains(&"PlasticityBatchV1")
            && LEARNING_LEDGER_SCHEMAS.contains(&"MemoryTopologyProposalV1")
    );
}
