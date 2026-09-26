use super::*;

#[test]
fn transient_observation_does_not_mask_identity_or_storage_failure() {
    assert!(
        observe_recovery_result(Err(AgentdError::AutomationObservationUnavailable(
            "timeout".into()
        )))
        .is_ok()
    );
    assert!(matches!(
        observe_recovery_result(Err(AgentdError::GenerationFenced("stale".into()))),
        Err(AgentdError::GenerationFenced(_))
    ));
    assert!(matches!(
        observe_recovery_result(Err(AgentdError::Protocol("mismatched receipt".into()))),
        Err(AgentdError::Protocol(_))
    ));
    assert!(matches!(
        observe_recovery_result(Err(codex_hepta_automation::AutomationError::Corrupt.into())),
        Err(AgentdError::Automation(
            codex_hepta_automation::AutomationError::Corrupt
        ))
    ));
}
