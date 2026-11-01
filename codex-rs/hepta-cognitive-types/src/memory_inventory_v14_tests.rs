use serde_json::json;

use super::*;
use crate::execute_memory_inventory_program_v1;

fn readout(operation: MemoryOperationV1, value: Value) -> MemoryInventoryReadoutV1 {
    MemoryInventoryReadoutV1 {
        schema: "hepta.memory.inventory-readout.v14".to_string(),
        query_id: ContractIdV1::new("query:fallback").expect("query ID"),
        operation: Some(operation),
        status: MemoryReadStatusV1::Ok,
        value,
        source_ids: vec![ContractDigestV1::parse(&"11".repeat(32)).expect("source")],
        generation: ContractGenerationV1::new(1).expect("generation"),
        snapshot_digest: ContractDigestV1::parse(&"22".repeat(32)).expect("snapshot"),
        prediction_kind: MemoryPredictionKindV1::SourceEvidence,
        cell_digests: Vec::new(),
        hops: 1,
        elapsed_seconds: 0.0,
        reason: None,
    }
}

#[test]
fn inventory_v14_exact_fallback_roundtrips_without_relaxing_v1() {
    let policy = json!({"reserve":11,"pack":3,"limit":14});
    let program = json!({"opcodes":[1,2,3,6]});
    let execution = execute_memory_inventory_program_v1(
        &serde_json::from_value(program.clone()).expect("typed procedure"),
        /*event*/ 4,
        &serde_json::from_value(policy.clone()).expect("typed policy"),
        /*max_steps*/ 4,
    )
    .expect("actual bounded interpreter");
    for (operation, value) in [
        (MemoryOperationV1::Semantic, policy),
        (MemoryOperationV1::Procedure, program),
        (
            MemoryOperationV1::Apply,
            serde_json::to_value(execution).expect("completed execution"),
        ),
    ] {
        let candidate = readout(operation, value);
        let bytes = serde_json::to_vec(&candidate).expect("wire");
        assert_eq!(
            decode_memory_inventory_readout_v1(&bytes).expect("explicit V14 fallback"),
            candidate
        );
        let mut old = candidate.clone();
        old.schema = "hepta.memory.inventory-readout.v1".to_string();
        assert!(old.validate().is_err(), "V1 still requires parameter artifacts");
        let mut forged = candidate.clone();
        forged.prediction_kind = MemoryPredictionKindV1::ModelPrediction;
        assert!(forged.validate().is_err(), "no invented model without an artifact");
        let mut forged = candidate;
        forged.cell_digests.push(ContractDigestV1::parse(&"33".repeat(32)).expect("artifact"));
        assert!(forged.validate().is_err(), "source evidence cannot claim a model");
    }
}

#[test]
fn inventory_v14_preserves_empty_failure_and_typed_value_constraints() {
    let mut candidate = readout(MemoryOperationV1::Semantic, json!({"reserve":11,"pack":16,"limit":14}));
    assert!(candidate.validate().is_err(), "invalid policy cannot enter through fallback");
    candidate.status = MemoryReadStatusV1::Abstain;
    candidate.reason = Some("current source withdrawn".to_string());
    assert!(candidate.validate().is_err(), "failed reads cannot expose partial evidence");
    candidate.value = Value::Null;
    candidate.source_ids.clear();
    candidate.prediction_kind = MemoryPredictionKindV1::None;
    let bytes = serde_json::to_vec(&candidate).expect("failure wire");
    assert_eq!(decode_memory_inventory_readout_v1(&bytes).expect("empty failure"), candidate);
}
