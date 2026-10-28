use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use serde_json::json;

use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdMethod;
use crate::AgentdRequest;

#[test]
fn cell_request_roundtrips_without_an_operation_or_authority_input() {
    let request = AgentdRequest {
        schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 7,
        spawn_generation: 3,
        method: AgentdMethod::MemoryCellRead {
            request: MemoryRequestV1 {
                schema: "hepta.memory.request.v1".to_string(),
                query_id: ContractIdV1::new("query:cell-wire").unwrap(),
                scope: ContractIdV1::new("scope:cell-wire").unwrap(),
                entity: ContractIdV1::new("entity:cell-wire").unwrap(),
                text: "Apply the saved procedure to the newest event".to_string(),
                at: 20,
                since: 10,
                max_cells: 3,
                max_hops: 3,
            },
        },
    };
    let wire = serde_json::to_vec(&request).unwrap();
    assert_eq!(
        serde_json::from_slice::<AgentdRequest>(&wire).unwrap(),
        request
    );
    for field in ["operation", "gold", "registry", "source_cut"] {
        let mut forged = serde_json::to_value(&request).unwrap();
        forged["method"]["request"][field] = json!("caller-selected");
        assert!(serde_json::from_value::<AgentdRequest>(forged).is_err());
    }
    let mut altered_method = serde_json::to_value(&request).unwrap();
    altered_method["method"]["operation"] = json!("apply");
    assert!(serde_json::from_value::<AgentdRequest>(altered_method).is_err());
}

#[test]
fn snapshot_cursor_is_a_strict_digest_and_cannot_import_a_claimed_snapshot() {
    let method = json!({"type": "memory_cell_snapshot", "after": null,
        "expected_owner_cut": "1".repeat(64), "limit": 2});
    assert!(serde_json::from_value::<AgentdMethod>(method.clone()).is_ok());
    for field in ["after", "expected_owner_cut"] {
        let mut forged = method.clone();
        forged[field] = json!("0".repeat(64));
        assert!(serde_json::from_value::<AgentdMethod>(forged).is_err());
    }
    let mut claimed = method;
    claimed["snapshot"] = json!({"sources": ["claimed"]});
    assert!(serde_json::from_value::<AgentdMethod>(claimed).is_err());
}
