use super::*;
use serde_json::json;

#[test]
fn startup_selector_and_legacy_exact_are_exclusive_and_strict() {
    for value in [
        json!({"kind":"exact_operation","operation_id":"original-op"}),
        json!({"kind":"latest_recorded_original_notes"}),
    ] {
        let selected: AgentdNotesRecoverySelector = serde_json::from_value(value).unwrap();
        assert!(AgentdNotesRecoverySelector::from_fields(None, Some(&selected)).is_ok());
        assert!(
            AgentdNotesRecoverySelector::from_fields(Some("original-op"), Some(&selected)).is_err()
        );
    }
    assert!(AgentdNotesRecoverySelector::from_fields(Some("original-op"), None).is_ok());
    assert!(AgentdNotesRecoverySelector::from_fields(None, None).is_err());
    for value in [
        json!({"kind":"latest_recorded_original_notes","target":"forged"}),
        json!({"kind":"latest_recorded_original_notes","operation_id":"hidden"}),
        json!({"kind":"latest_recorded_original_notes","operation_id":null}),
        json!({"kind":"exact_operation"}),
        json!({"kind":"exact_operation","operation_id":"ok","thread_id":"forged"}),
    ] {
        assert!(serde_json::from_value::<AgentdNotesRecoverySelector>(value).is_err());
    }
}
