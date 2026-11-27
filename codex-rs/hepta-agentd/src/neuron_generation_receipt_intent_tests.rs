//! Owner-local encoding of the exact original generation intent projection.
use pretty_assertions::assert_eq;

use super::*;

#[test]
fn original_intent_namespace_covers_every_lookup_field_and_presence() -> anyhow::Result<()> {
    let original = CellGenerationIntentV2 {
        operation_id: "use-fixture".into(),
        task_digest: [1; 32],
        source_frontier: [2; 32],
        predecessor_digest: [3; 32],
        input_digest: [4; 32],
        deadline_micros: 9,
    };
    let expected = intent_binding(Some(&original))?;
    assert_eq!(
        expected.to_string(),
        "25c32b4e85d1089ba33fd3fb938af762df82cbca00de6c46b5d2eeae93ca96b1"
    );
    assert_ne!(expected, intent_binding(/*intent*/ None)?);
    for field in 0..6 {
        let mut changed = original.clone();
        match field {
            0 => changed.operation_id.push_str("-other"),
            1 => changed.task_digest[0] ^= 1,
            2 => changed.source_frontier[0] ^= 1,
            3 => changed.predecessor_digest[0] ^= 1,
            4 => changed.input_digest[0] ^= 1,
            5 => changed.deadline_micros += 1,
            _ => unreachable!(),
        }
        assert_ne!(intent_binding(Some(&changed))?, expected);
    }
    let mut invalid = original;
    invalid.operation_id.clear();
    assert!(intent_binding(Some(&invalid)).is_err());
    Ok(())
}
