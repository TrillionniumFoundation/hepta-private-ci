//! Actual native reserve/dispatch/Failed/settle/reopen; Root facts are explicit
//! independent provider fixtures, never a live provider or protected file claim.
use super::*;
use crate::self_iteration_model::validate_root_native_failure_facts_v1;
use codex_hepta_infer_core::SelfIterationModelFailureFactsV1;
use codex_hepta_infer_core::SelfIterationModelFailureKindV1;
use codex_hepta_supervisor::RootModelFailureV1;
use codex_hepta_supervisor::RootModelOutcomeReceiptV1;

fn facts() -> SelfIterationModelFailureFactsV1 {
    let (request, native_record, mut admission) =
        fixture_with_status(NativeRunStatus::Failed, NativeBoundaryStatus::Failed);
    admission.completed_at_ms = 0;
    admission.response_id.clear();
    admission.stream_sha256 = [0; 32];
    admission.model_output_bytes = 0;
    admission.model_output_sha256 = [0; 32];
    SelfIterationModelFailureFactsV1 {
        request,
        native_record,
        root_outcome_bytes: serde_json::to_vec(&RootModelOutcomeReceiptV1::Failed {
            admission,
            observed_at_ms: 2000,
            stream_sha256: [5; 32],
            failure: RootModelFailureV1::ProviderFailed {
                response_id: Some("original-failed-response".into()),
            },
        })
        .expect("original codec"),
        observed_at_ms: 3000,
    }
}
#[test]
fn actual_reopened_native_failed_terminal_joins_root_typed_failure_without_a_fake_advice_ack() {
    let original = facts();
    assert_eq!(
        original.native_record.state,
        NativeReservationState::Released
    );
    assert!(
        original.native_record.terminal_owner.is_none()
            && original.native_record.terminal_publication.is_none()
    );
    let failure = validate_root_native_failure_facts_v1(&original, &scope())
        .expect("complete original facts");
    assert_eq!(
        failure.kind,
        SelfIterationModelFailureKindV1::ProviderFailed
    );
    assert!(!failure.authority.grants_any());
    assert_eq!(failure.request_id, original.request.request_id);
    let mut late = original.clone();
    late.observed_at_ms = original.request.deadline_ms + 1;
    let failure =
        validate_root_native_failure_facts_v1(&late, &scope()).expect("late factual terminal");
    assert_eq!(failure.observed_at_ms, late.observed_at_ms);
    assert!(
        !failure.authority.grants_any(),
        "late receipt grants no renewed use"
    );
}
#[test]
fn typed_provider_failure_cannot_replace_unknown_cancelled_native_effect_or_changed_request() {
    let original = facts();
    for mutation in 0..12 {
        let mut changed = original.clone();
        match mutation {
            0 => changed.native_record.state = NativeReservationState::Indeterminate,
            1 => {
                changed
                    .native_record
                    .observation
                    .as_mut()
                    .expect("output")
                    .status = NativeRunStatus::Interrupted
            }
            2 => {
                changed
                    .native_record
                    .observation
                    .as_mut()
                    .expect("output")
                    .boundary_status = NativeBoundaryStatus::TimedOut
            }
            3 => changed.native_record.cancel_requested = true,
            4 => {
                changed
                    .native_record
                    .observation
                    .as_mut()
                    .expect("output")
                    .terminal_observed = false
            }
            5 => changed.native_record.request.principal_id = "different-agent".into(),
            6 => changed.request.prompt.push(' '),
            7 => changed.request.role = SelfIterationModelRoleV1::Evaluator,
            8 => changed.native_record.request.request_id = "different-request".into(),
            9 => changed.native_record.turn_id = Some("different-turn".into()),
            10 => {
                changed
                    .native_record
                    .observation
                    .as_mut()
                    .expect("output")
                    .owner_authority = NativeOwnerAuthority::Unverified
            }
            _ => changed.observed_at_ms = 1500,
        }
        assert!(
            validate_root_native_failure_facts_v1(&changed, &scope()).is_err(),
            "{mutation}"
        );
    }
    let mut changed_scope = scope();
    changed_scope.agentd_socket = Path::new("/foreign/agentd.sock");
    assert!(validate_root_native_failure_facts_v1(&original, &changed_scope).is_err());
    changed_scope = scope();
    changed_scope.app_server_executable_digest = Digest32::of_bytes(b"foreign ELF");
    assert!(validate_root_native_failure_facts_v1(&original, &changed_scope).is_err());
}
#[test]
fn completed_or_malformed_provider_facts_never_become_failed_terminal() {
    let mut original = facts();
    let (_, _, completed) = fixture();
    original.root_outcome_bytes =
        serde_json::to_vec(&RootModelOutcomeReceiptV1::Completed { receipt: completed })
            .expect("bytes");
    assert!(validate_root_native_failure_facts_v1(&original, &scope()).is_err());
    original.root_outcome_bytes = b"timeout or connection lost".to_vec();
    assert!(validate_root_native_failure_facts_v1(&original, &scope()).is_err());
}
