use super::*;
use serde_json::json;

#[test]
fn every_registered_program_combines_the_three_typed_values()
-> Result<(), Box<dyn std::error::Error>> {
    let semantic = json!({"factor": 3, "label": "校准"});
    let mut observed = Vec::new();
    for opcode in ["identity", "add_bias", "multiply", "affine", "clamp"] {
        observed.push(execute_memory_cell_program_v1(
            &json!({"opcode": opcode, "bias": 2, "limit": 30}),
            11,
            &semantic,
        )?);
    }
    assert_eq!(observed, vec![11, 13, 33, 35, 30]);
    assert_eq!(
        execute_memory_cell_program_v1(
            &json!({"opcode": "clamp", "bias": -2, "limit": 30}),
            -11,
            &semantic
        )?,
        -30
    );
    Ok(())
}

#[test]
fn malformed_and_out_of_domain_values_do_not_enter_the_interpreter() {
    for (kind, value) in [
        (MemoryCellKindV1::Event, json!(true)),
        (MemoryCellKindV1::Event, json!(1_000_001)),
        (
            MemoryCellKindV1::Semantic,
            json!({"factor": 2.5, "label": "x"}),
        ),
        (
            MemoryCellKindV1::Semantic,
            json!({"factor": 2, "label": "x", "extra": 1}),
        ),
        (
            MemoryCellKindV1::Semantic,
            json!({"factor": 2, "label": "\u{0}"}),
        ),
        (
            MemoryCellKindV1::Procedure,
            json!({"opcode": "log", "bias": 1, "limit": 3}),
        ),
        (
            MemoryCellKindV1::Procedure,
            json!({"opcode": "affine", "bias": 1, "limit": -1}),
        ),
    ] {
        assert!(validate_memory_cell_value_v1(kind, &value).is_err());
    }
    assert!(
        execute_memory_cell_program_v1(
            &json!({"opcode": "affine", "bias": 2, "limit": 30}),
            1_000_001,
            &json!({"factor": 3, "label": "x"}),
        )
        .is_err()
    );
}
