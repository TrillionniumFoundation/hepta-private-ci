use pretty_assertions::assert_eq;

use super::*;

#[test]
fn negative_floor_division_and_zero_pack_preserve_the_declared_program() {
    let policy = MemoryInventoryPolicyV1 { reserve: 3, pack: 0, limit: 9 };
    let program = MemoryInventoryProgramV1 { opcodes: [5, 4, 2, 6] };
    assert_eq!(execute_memory_inventory_program_v1(&program, -3, &policy, 4).unwrap(),
        MemoryInventoryExecutionV1 {
            status: MemoryInventoryExecutionStatusV1::Completed,
            value: Some(0),
            trace: vec![
                MemoryInventoryStepV1 { op: MemoryInventoryOpcodeV1::Halve, before: -3, after: -2 },
                MemoryInventoryStepV1 { op: MemoryInventoryOpcodeV1::AddReserve, before: -2, after: 1 },
                MemoryInventoryStepV1 { op: MemoryInventoryOpcodeV1::Pack, before: 1, after: 0 },
                MemoryInventoryStepV1 { op: MemoryInventoryOpcodeV1::Stop, before: 0, after: 0 },
            ],
        });
}

#[test]
fn stop_requires_a_budgeted_step_and_never_exposes_an_unfinished_value() {
    let policy = MemoryInventoryPolicyV1 { reserve: 7, pack: 2, limit: 10 };
    let program = MemoryInventoryProgramV1 { opcodes: [1, 2, 3, 6] };
    let complete = execute_memory_inventory_program_v1(&program, 2, &policy, 4).unwrap();
    let stopped = execute_memory_inventory_program_v1(&program, 2, &policy, 3).unwrap();
    assert_eq!(stopped, MemoryInventoryExecutionV1 {
        status: MemoryInventoryExecutionStatusV1::BudgetStop,
        value: None,
        trace: complete.trace[..3].to_vec(),
    });
    let missing = execute_memory_inventory_program_v1(
        &MemoryInventoryProgramV1 { opcodes: [0, 0, 0, 0] }, 2, &policy, 4).unwrap();
    assert_eq!(missing, MemoryInventoryExecutionV1 {
        status: MemoryInventoryExecutionStatusV1::MissingStop,
        value: None,
        trace: vec![MemoryInventoryStepV1 { op: MemoryInventoryOpcodeV1::Keep, before: 2, after: 2 }; 4],
    });
    assert!(execute_memory_inventory_program_v1(
        &MemoryInventoryProgramV1 { opcodes: [7, 0, 0, 6] }, 2, &policy, 4).is_err());
}

#[test]
fn typed_owner_values_reject_old_profiles_and_extra_fields() {
    assert!(validate_memory_inventory_value_v1(MemoryInventoryKindV1::Semantic,
        &serde_json::json!({"factor": 3, "label": "old"})).is_err());
    assert!(validate_memory_inventory_value_v1(MemoryInventoryKindV1::Semantic,
        &serde_json::json!({"reserve": 3, "pack": 1, "limit": 4, "source": "claimed"})).is_err());
    assert!(validate_memory_inventory_value_v1(MemoryInventoryKindV1::Procedure,
        &serde_json::json!({"opcodes": [0, 6]})).is_err());
    assert!(validate_memory_inventory_value_v1(MemoryInventoryKindV1::Hold, &Value::from(0)).is_err());
}
