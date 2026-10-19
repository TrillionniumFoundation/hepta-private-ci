use super::*;

#[test]
fn pipeline_diagnostics_redact_dynamic_owner_and_adapter_details() {
    let marker = "PRIVATE-PROMPT-AND-OWNER-PATH";
    let errors = [
        AgentdPromptPipelineError::RegistryOpen(marker.into()),
        AgentdPromptPipelineError::CandidateSource(marker.into()),
        AgentdPromptPipelineError::Compilation(marker.into()),
        AgentdPromptPipelineError::RuntimeOpen(AgentdPromptRuntimeError::Adapter(marker.into())),
        AgentdPromptPipelineError::Stage(AgentdPromptRuntimeError::Adapter(marker.into())),
        AgentdPromptPipelineError::ExactOpen(
            ExactContextDeliveryError::Domain(marker.into()).into(),
        ),
        AgentdPromptPipelineError::from(ExactContextDeliveryError::Domain(marker.into())),
    ];
    for error in errors {
        assert_eq!(format!("{error}"), error.reason_code());
        assert_eq!(format!("{error:?}"), error.reason_code());
        assert_eq!(format!("{error:#?}"), error.reason_code());
        assert!(!format!("{error:#?}").contains(marker));
        assert!(std::error::Error::source(&error).is_none());
    }
    let runtime = AgentdPromptRuntimeError::Adapter(marker.into());
    assert_eq!(format!("{runtime:?}"), runtime.reason_code());
    assert_eq!(format!("{runtime}"), runtime.reason_code());
}

#[test]
fn public_exact_diagnostic_preserves_recovery_action_without_exposing_internal_error() {
    for internal in [
        ExactContextDeliveryError::ReopenRequired,
        ExactContextDeliveryError::RecoveryRequired,
        ExactContextDeliveryError::Expired,
        ExactContextDeliveryError::Domain("PRIVATE-CONTEXT".into()),
    ] {
        let expected = internal.reason_code();
        let public = AgentdExactContextDeliveryError::from(internal.clone());
        assert_eq!(public.reason_code(), expected);
        assert_eq!(format!("{public:#?}"), expected);
        assert_eq!(format!("{public}"), expected);
        assert_eq!(
            AgentdPromptPipelineError::from(internal).reason_code(),
            expected
        );
    }
}
