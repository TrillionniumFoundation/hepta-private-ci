use super::*;
use serde_json::json;

// Legacy field arbitration is a fixture helper. The sealed Desktop launch uses
// AgentdCalculatorRecoverySelector's strict typed deserializer directly.
fn fixture_from_fields(
    operation_id: Option<&str>,
    selector: Option<&AgentdCalculatorRecoverySelector>,
) -> Result<AgentdCalculatorRecoverySelector, AgentdError> {
    use AgentdCalculatorRecoverySelector as Selector;

    match (operation_id, selector) {
        (Some(operation_id), None) => Selector::checked_exact(operation_id.into()),
        (None, Some(Selector::ExactOperation { operation_id })) => Selector::checked_exact(operation_id.clone()),
        (None, Some(Selector::LatestRecordedOriginalCalculator)) => Ok(Selector::LatestRecordedOriginalCalculator),
        _ => Err(AgentdError::Invalid("previous Calculator recovery requires exactly one typed selector or legacy operation_id".into())),
    }
}

#[test]
fn startup_selector_and_legacy_exact_are_exclusive_and_strict() {
    for value in [
        json!({"kind":"exact_operation","operation_id":"original-op"}),
        json!({"kind":"latest_recorded_original_calculator"}),
    ] {
        let selected: AgentdCalculatorRecoverySelector = serde_json::from_value(value).unwrap();
        assert!(fixture_from_fields(None, Some(&selected)).is_ok());
        assert!(fixture_from_fields(Some("original-op"), Some(&selected)).is_err());
    }
    assert!(fixture_from_fields(Some("original-op"), None).is_ok());
    assert!(fixture_from_fields(None, None).is_err());
    for value in [
        json!({"kind":"latest_recorded_original_calculator","target":"forged"}),
        json!({"kind":"latest_recorded_original_calculator","operation_id":"hidden"}),
        json!({"kind":"latest_recorded_original_calculator","operation_id":null}),
        json!({"kind":"exact_operation"}),
        json!({"kind":"exact_operation","operation_id":"ok","thread_id":"forged"}),
    ] {
        assert!(serde_json::from_value::<AgentdCalculatorRecoverySelector>(value).is_err());
    }
}
