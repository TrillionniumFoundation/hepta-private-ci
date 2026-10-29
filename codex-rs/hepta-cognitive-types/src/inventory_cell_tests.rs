use super::*;
use serde_json::json;

#[test]
fn inventory_profile_does_not_accept_legacy_values_or_unknown_fields() {
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Semantic, &json!({"factor": 3, "label": "x"})).is_err());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Skill, &json!({"opcode": 1, "bias": 2, "limit": 3})).is_err());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Semantic, &json!({"reserve": 3, "pack": 2, "limit": 15})).is_ok());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Semantic, &json!({"reserve": 16, "pack": 2, "limit": 15})).is_err());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Semantic, &json!({"reserve": 3, "pack": 2, "limit": 15, "gold": true})).is_err());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Skill, &json!({"program": [1, 2, 3, 6]})).is_ok());
    assert!(validate_inventory_cell_value_v1(InventoryCellKindV1::Skill, &json!({"program": [1, 2, 7, 6]})).is_err());
}

#[test]
fn inventory_program_preserves_four_step_floor_stop_and_checked_arithmetic() {
    let policy = InventoryPolicyV1 { reserve: 5, pack: 3, limit: 14 };
    assert_eq!(execute_inventory_program_v1(1, &policy, &InventoryProgramV1 { program: [1, 2, 3, 6] }, 4).unwrap(), 12);
    assert_eq!(execute_inventory_program_v1(-3, &policy, &InventoryProgramV1 { program: [5, 6, 0, 0] }, 4).unwrap(), -2);
    assert!(execute_inventory_program_v1(1, &policy, &InventoryProgramV1 { program: [1, 2, 3, 6] }, 3).is_err());
    assert!(execute_inventory_program_v1(1, &policy, &InventoryProgramV1 { program: [0, 1, 2, 3] }, 4).is_err());
    assert!(execute_inventory_program_v1(i64::MAX, &policy, &InventoryProgramV1 { program: [2, 6, 0, 0] }, 4).is_err());
    assert!(execute_inventory_program_v1(i64::MIN, &policy, &InventoryProgramV1 { program: [1, 6, 0, 0] }, 4).is_err());
}

#[test]
fn inventory_apply_requires_independent_entity_and_workflow() {
    let mut route = InventoryCellRouteV1 {
        operation: MemoryOperationV1::Apply,
        entity: Some(ContractIdV1::new("inventory:entity:cedar-harbor").unwrap()),
        workflow: Some(ContractIdV1::new("inventory:workflow:jade-method").unwrap()),
    };
    assert!(route.validate().is_ok());
    route.workflow = None;
    assert!(route.validate().is_err());
    route.operation = MemoryOperationV1::Semantic;
    assert!(route.validate().is_ok());
    route.operation = MemoryOperationV1::Procedure;
    assert!(route.validate().is_err());
}
