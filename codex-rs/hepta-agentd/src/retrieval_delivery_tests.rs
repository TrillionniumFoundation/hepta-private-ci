use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejection;
use codex_hepta_infer_core::durable_control::native::NativeDispatchRejectionStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::RetrievalAssignmentFact;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn assignment(prepared: bool) -> RetrievalPreparationFactV1 {
    RetrievalPreparationFactV1 {
        assignment: RetrievalAssignmentFact {
            record_id: id("retrieval-assignment:test"),
            episode_id: id("retrieval-episode:test"),
            cue_digest: digest("cue"),
            policy_digest: digest("policy"),
            source_completeness_digest: digest("source"),
            candidate_union_digest: digest("union"),
            recall_packet_digest: digest("recall"),
            enumerated_candidate_digests: vec![digest("candidate")],
            legal_candidate_indices: vec![0],
            selected_candidate_indices: vec![0],
            delivered_candidate_indices: Vec::new(),
            context_exposed: false,
            published_context_digest: None,
            omitted_by_policy_limits: 0,
            assignment_propensity: ProbabilityQ32::ONE,
            downstream_policy_digest: None,
            delivery_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("support"),
        },
        prepared_candidate_indices: prepared.then_some(0).into_iter().collect(),
        prepared_context_digest: prepared.then(|| digest("prepared-context")),
    }
}

fn binding() -> RetrievalNativeBindingV1 {
    RetrievalNativeBindingV1 {
        request_id: "native-request".to_string(),
        principal_id: "principal".to_string(),
        worker_generation: 7,
    }
}

fn native(context: Option<Digest32>) -> NativeRunRecord {
    NativeRunRecord {
        request: NativeRequest {
            request_id: "native-request".to_string(),
            principal_id: "principal".to_string(),
            worker_generation: 7,
            model: "model".to_string(),
            payload_digest: digest("payload").to_string(),
        },
        revision: 2,
        state: NativeReservationState::Dispatching,
        dispatch: Some(NativeDispatch {
            thread_id: "thread".to_string(),
            model_provider: "provider".to_string(),
            context_digest: digest("additional-context").to_string(),
            owner_context_digest: context.map(|value| value.to_string()),
            codex_payload_digest: None,
            codex_request_digest: None,
            app_server_version: None,
            protocol_id: None,
            codex_source_admission_digest: None,
            codex_home_digest: None,
            codex_connection_id: None,
            codex_session_id: None,
            codex_deadline_ms: None,
            codex_authority_epoch: None,
            codex_revocation_revision: None,
            codex_revocation_head_sha256: None,
            codex_authority_witness_sha256: None,
        }),
        turn_id: None,
        cancel_requested: false,
        pre_dispatch_stop: None,
        dispatch_rejection: None,
        observation: None,
    }
}

#[test]
fn prepared_published_start_and_outcome_are_distinct_evidence() {
    let assignment = assignment(true);
    let prepared = verify_retrieval_delivery_v1(&assignment, &binding(), None).expect("prepared");
    assert_eq!(prepared.stage, RetrievalDeliveryStageV1::AssignmentPrepared);

    // A write-ahead dispatch is committed before the external effect boundary
    // and must not be mislabeled as publication.
    let mut run = native(assignment.prepared_context_digest);
    let dispatch_prepared = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run))
        .expect("dispatch prepared");
    assert_eq!(
        dispatch_prepared.stage,
        RetrievalDeliveryStageV1::AssignmentPrepared
    );

    run.revision += 1;
    run.state = NativeReservationState::Released;
    run.dispatch_rejection = Some(NativeDispatchRejection {
        status: NativeDispatchRejectionStatus::Rejected,
        reason: "policy rejection".to_string(),
        response_digest: digest("server-response").to_string(),
        retry_safe_before_admission: false,
    });
    let published = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run))
        .expect("published response");
    assert_eq!(published.stage, RetrievalDeliveryStageV1::Published);
    assert_eq!(
        published.publication_receipt_digest,
        Some(digest("server-response"))
    );

    run.dispatch_rejection = None;
    run.state = NativeReservationState::Running;
    run.revision += 1;
    run.turn_id = Some("turn".to_string());
    let started =
        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("started");
    assert_eq!(started.stage, RetrievalDeliveryStageV1::NativeStarted);

    run.state = NativeReservationState::Released;
    run.revision += 1;
    run.observation = Some(NativeRunOutput {
        thread_id: "thread".to_string(),
        turn_id: "turn".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: "answer".to_string(),
        observed_output_tokens: Some(3),
        terminal_observed: true,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some(digest("terminal").to_string()),
    });
    let outcome =
        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("outcome");
    assert_eq!(outcome.stage, RetrievalDeliveryStageV1::OutcomeObserved);
    assert_eq!(outcome.terminal_status, Some(NativeRunStatus::Completed));
    outcome.validate().expect("receipt");
}

#[test]
fn socket_unknown_and_pre_effect_abort_never_create_false_publication() {
    let assignment = assignment(true);
    let mut run = native(assignment.prepared_context_digest);
    run.state = NativeReservationState::Indeterminate;
    let unknown =
        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("unknown");
    assert_eq!(unknown.stage, RetrievalDeliveryStageV1::AssignmentPrepared);

    run.state = NativeReservationState::Released;
    run.pre_dispatch_stop = Some("proved unsent".to_string());
    let aborted =
        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("aborted");
    assert_eq!(aborted.stage, RetrievalDeliveryStageV1::AssignmentPrepared);
}

#[test]
fn retries_are_digest_identical_and_do_not_duplicate_evidence() {
    let assignment = assignment(true);
    let run = native(assignment.prepared_context_digest);
    let first = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("first");
    let replay = verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)).expect("replay");
    assert_eq!(replay, first);
    assert_eq!(replay.receipt_digest, first.receipt_digest);
}

#[test]
fn unprepared_or_mismatched_context_cannot_be_upgraded_to_native_use() {
    let unprepared = assignment(false);
    let run = native(Some(digest("prepared-context")));
    assert_eq!(
        verify_retrieval_delivery_v1(&unprepared, &binding(), Some(&run)),
        Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
    );

    let prepared = assignment(true);
    let wrong = native(Some(digest("different-context")));
    assert_eq!(
        verify_retrieval_delivery_v1(&prepared, &binding(), Some(&wrong)),
        Err(RetrievalDeliveryError::NativeContextDigestMismatch)
    );
}

#[test]
fn terminal_observation_must_match_the_durable_started_turn() {
    let assignment = assignment(true);
    let mut run = native(assignment.prepared_context_digest);
    run.state = NativeReservationState::Running;
    run.turn_id = Some("turn-a".to_string());
    run.observation = Some(NativeRunOutput {
        thread_id: "thread".to_string(),
        turn_id: "turn-b".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Failed,
        boundary_status: NativeBoundaryStatus::Failed,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: true,
        stop_reason: Some("failed".to_string()),
        owner_authority: NativeOwnerAuthority::ObservedReady,
        codex_terminal_correlation_digest: Some(digest("terminal").to_string()),
    });
    assert_eq!(
        verify_retrieval_delivery_v1(&assignment, &binding(), Some(&run)),
        Err(RetrievalDeliveryError::NativeTurnMismatch)
    );
}

#[test]
fn legacy_exposure_flags_are_not_accepted_as_a_preparation() {
    let mut prepared = assignment(true);
    prepared.assignment.context_exposed = true;
    assert_eq!(
        verify_retrieval_delivery_v1(&prepared, &binding(), None),
        Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
    );
}

#[test]
fn equal_context_cannot_join_another_native_request_or_owner() {
    let prepared = assignment(true);
    for field in 0..3 {
        let mut run = native(prepared.prepared_context_digest);
        match field {
            0 => run.request.request_id = "other-request".to_string(),
            1 => run.request.principal_id = "other-principal".to_string(),
            _ => run.request.worker_generation += 1,
        }
        assert_eq!(
            verify_retrieval_delivery_v1(&prepared, &binding(), Some(&run)),
            Err(RetrievalDeliveryError::NativeIdentityMismatch)
        );
    }
}

#[test]
fn preparation_bounds_and_selected_membership_are_checked_before_join() {
    for indices in [vec![0, 0], vec![1], vec![u32::MAX], vec![0; 17]] {
        let mut prepared = assignment(true);
        prepared.prepared_candidate_indices = indices;
        assert_eq!(
            verify_retrieval_delivery_v1(&prepared, &binding(), None),
            Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
        );
    }
    let mut prepared = assignment(true);
    prepared.assignment.selected_candidate_indices.clear();
    assert_eq!(
        verify_retrieval_delivery_v1(&prepared, &binding(), None),
        Err(RetrievalDeliveryError::AssignmentPreparationMismatch)
    );
}

#[test]
fn receipt_preserves_positions_and_binds_the_order() {
    let mut prepared = assignment(true);
    prepared
        .assignment
        .enumerated_candidate_digests
        .push(digest("second"));
    prepared.assignment.legal_candidate_indices.push(1);
    prepared.assignment.selected_candidate_indices.push(1);
    prepared.prepared_candidate_indices = vec![1, 0];
    let first = verify_retrieval_delivery_v1(&prepared, &binding(), None).expect("receipt");
    assert_eq!(
        first.prepared_candidate_digests,
        vec![digest("second"), digest("candidate")]
    );
    prepared.prepared_candidate_indices.reverse();
    let reordered = verify_retrieval_delivery_v1(&prepared, &binding(), None).expect("receipt");
    assert_ne!(first.receipt_digest, reordered.receipt_digest);
    let mut tampered = first;
    tampered.prepared_candidate_digests.reverse();
    assert_eq!(
        tampered.validate(),
        Err(RetrievalDeliveryError::DigestMismatch)
    );
}
