use std::error::Error as _;

use super::AgentdNeuronControlErrorV2;
use super::AgentdNeuronControlStateErrorV2;
use super::AgentdNeuronRetryClassV2;

#[test]
fn owner_contention_is_bounded_backoff_not_terminal() {
    let error = AgentdNeuronControlErrorV2::OwnerBusy;
    assert_eq!(error.stable_code(), "owner_busy");
    assert_eq!(
        error.retry_class(),
        AgentdNeuronRetryClassV2::BoundedBackoff
    );
    assert_eq!(
        error.operator_action(),
        "retry_control_observation_with_bounded_backoff"
    );
    assert!(!error.is_terminal());
    assert!(!error.is_reconstruction_required());
    let rendered = error.to_string();
    assert!(rendered.contains("owner_busy"));
    assert!(rendered.contains("bounded_backoff"));
}

#[test]
fn poisoned_owners_require_reconstruction() {
    let owner = AgentdNeuronControlErrorV2::OwnerPoisoned;
    assert_eq!(
        owner.retry_class(),
        AgentdNeuronRetryClassV2::ReconstructOwner
    );
    assert!(owner.is_reconstruction_required());
    assert_eq!(
        owner.operator_action(),
        "stop_serving_and_reconstruct_owner"
    );

    let controller = AgentdNeuronControlErrorV2::ControllerPoisoned;
    assert_eq!(
        controller.retry_class(),
        AgentdNeuronRetryClassV2::ReconstructController
    );
    assert!(controller.is_reconstruction_required());
    assert_eq!(
        controller.operator_action(),
        "stop_serving_and_reconstruct_controller"
    );
}

#[test]
fn lifecycle_and_generation_mistakes_are_not_business_retries() {
    for error in [
        AgentdNeuronControlErrorV2::NotServing,
        AgentdNeuronControlErrorV2::InvalidTransition,
        AgentdNeuronControlErrorV2::GenerationConflict,
        AgentdNeuronControlErrorV2::UnknownGeneration,
    ] {
        assert_eq!(
            error.retry_class(),
            AgentdNeuronRetryClassV2::NeverBusinessRetry
        );
        assert!(error.is_terminal());
        assert!(!error.is_reconstruction_required());
    }
}

#[test]
fn pending_recovery_requires_the_exact_operation_identity() {
    let error = AgentdNeuronControlErrorV2::PendingRecovery;
    assert_eq!(
        error.retry_class(),
        AgentdNeuronRetryClassV2::ExactIdentityRecovery
    );
    assert_eq!(
        error.operator_action(),
        "reconcile_exact_provider_or_witness_identity"
    );
    assert!(!error.is_terminal());
}

#[test]
fn control_state_failures_preserve_the_nested_source() {
    let invalid = AgentdNeuronControlErrorV2::ControlState(
        AgentdNeuronControlStateErrorV2::Invalid,
    );
    assert_eq!(
        invalid.retry_class(),
        AgentdNeuronRetryClassV2::RepairControlState
    );
    assert_eq!(invalid.operator_action(), "repair_control_state_namespace");
    assert!(invalid.source().is_some());
    assert!(invalid.to_string().contains("control_state_invalid"));

    let io = AgentdNeuronControlErrorV2::ControlState(
        AgentdNeuronControlStateErrorV2::Io(std::io::ErrorKind::Other),
    );
    assert_eq!(io.retry_class(), AgentdNeuronRetryClassV2::BoundedBackoff);
    assert_eq!(
        io.operator_action(),
        "restore_control_state_storage_and_retry"
    );
    assert!(io.source().is_some());
}
