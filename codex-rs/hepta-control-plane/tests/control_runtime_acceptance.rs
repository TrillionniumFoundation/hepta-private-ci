use codex_hepta_control_plane::CanonicalDecisionEnvelopeV1;
use codex_hepta_control_plane::ControlRuntimeExecutionConsumerV1;
use codex_hepta_control_plane::CurrentExecutionFenceV1;
use codex_hepta_control_plane::EffectTerminalDispositionV1;
use codex_hepta_control_plane::EffectTerminalReceiptV1;
use codex_hepta_control_plane::GrantRequestV1;
use codex_hepta_control_plane::IndependentAuthorizationV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_control_plane::ProductExecutionErrorV1;
use codex_hepta_control_plane::ProductExecutionPhaseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable fixture id")
}

fn envelope(name: &str) -> CanonicalDecisionEnvelopeV1 {
    CanonicalDecisionEnvelopeV1 {
        operation_identity_digest: digest(&format!("operation-identity:{name}")),
        snapshot_bytes: format!("snapshot:{name}").into_bytes(),
        prepared_plan_bytes: format!("prepared:{name}").into_bytes(),
        ndu_evaluation_bytes: format!("ndu:{name}").into_bytes(),
        plan_receipt_bytes: format!("plan-receipt:{name}").into_bytes(),
        grant_request_set_bytes: format!("grant-request-set:{name}").into_bytes(),
    }
}

fn request(name: &str) -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id(&format!("operation-{name}")),
        candidate_id: id(&format!("candidate-{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        final_payload_digest: digest(&format!("payload:{name}")),
        objective_digest: digest("objective"),
        snapshot_digest: digest("global-snapshot"),
        revocation_frontier_digest: digest("revocation-frontier"),
        expires_at_micros: 10_000,
    }
}

fn authorization(request: &GrantRequestV1, name: &str) -> IndependentAuthorizationV1 {
    IndependentAuthorizationV1 {
        authority_principal: id("independent-kernel-authority"),
        signed_grant_digest: digest(&format!("signed-grant:{name}")),
        operation_id: request.operation_id.clone(),
        candidate_id: request.candidate_id.clone(),
        plan_digest: request.plan_digest,
        final_payload_digest: request.final_payload_digest,
        snapshot_digest: request.snapshot_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        expires_at_micros: request.expires_at_micros,
    }
}

fn current_fence(request: &GrantRequestV1) -> CurrentExecutionFenceV1 {
    CurrentExecutionFenceV1 {
        snapshot_digest: request.snapshot_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        final_payload_digest: request.final_payload_digest,
        now_micros: 100,
    }
}

#[test]
fn bounded_store_rejects_overload_without_advancing_the_log() {
    let directory = tempfile::tempdir().expect("tempdir");
    let mut store =
        PlannerStoreV1::open(directory.path().join("planner.store")).expect("planner store");
    let before = store.records().len();
    let oversized = vec![0_u8; 5 * 1024 * 1024];
    assert!(matches!(
        store.append(PlannerStoreRecordKindV1::Dispatch, &oversized),
        Err(PlannerStoreError::PayloadTooLarge)
    ));
    assert_eq!(store.records().len(), before);
    store
        .append(PlannerStoreRecordKindV1::Dispatch, b"bounded-dispatch")
        .expect("store remains usable after overload rejection");
}

#[test]
fn fanout_partial_failure_is_isolated_and_success_reaches_terminal_receipt() {
    let directory = tempfile::tempdir().expect("tempdir");
    let mut store =
        PlannerStoreV1::open(directory.path().join("planner.store")).expect("planner store");
    let mut consumer = ControlRuntimeExecutionConsumerV1::new();

    let successful = envelope("successful");
    let rejected = envelope("rejected");
    let successful_identity = successful.operation_identity_digest;
    let rejected_identity = rejected.operation_identity_digest;
    consumer
        .commit_decision(&mut store, &successful)
        .expect("durable successful decision");
    consumer
        .commit_decision(&mut store, &rejected)
        .expect("durable rejected decision");

    let successful_request = request("successful");
    let rejected_request = request("rejected");
    consumer
        .record_authority_request(&mut store, successful_identity, &successful_request)
        .expect("successful authority request");
    consumer
        .record_authority_request(&mut store, rejected_identity, &rejected_request)
        .expect("rejected authority request");

    consumer
        .consume_independent_authorization(
            &mut store,
            successful_identity,
            &successful_request,
            &current_fence(&successful_request),
            &authorization(&successful_request, "successful"),
        )
        .expect("independent current-state authorization");

    let mut revoked_fence = current_fence(&rejected_request);
    revoked_fence.revocation_frontier_digest = digest("revocation-after-decision");
    assert_eq!(
        consumer.consume_independent_authorization(
            &mut store,
            rejected_identity,
            &rejected_request,
            &revoked_fence,
            &authorization(&rejected_request, "rejected"),
        ),
        Err(ProductExecutionErrorV1::RevocationDrift)
    );

    consumer
        .mark_dispatched(
            &mut store,
            successful_identity,
            b"named-effect-executor-dispatch-receipt",
        )
        .expect("dispatch successful operation");
    let terminal = consumer
        .record_terminal(
            &mut store,
            &EffectTerminalReceiptV1 {
                operation_identity_digest: successful_identity,
                observed_outcome_digest: digest("successful-terminal-outcome"),
                disposition: EffectTerminalDispositionV1::Succeeded,
            },
        )
        .expect("terminal receipt");

    assert_eq!(terminal.phase, ProductExecutionPhaseV1::Succeeded);
    assert_eq!(
        consumer
            .operation(rejected_identity)
            .expect("rejected operation remains observable")
            .phase,
        ProductExecutionPhaseV1::AuthorityRequested
    );
}

#[test]
fn backup_rollback_rehearsal_restores_last_anchored_generation() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("planner.store");
    let backup = directory.path().join("planner.backup");
    let restored = directory.path().join("planner.restored");

    let anchored_count;
    {
        let mut store = PlannerStoreV1::open(&path).expect("planner store");
        store
            .append_decision(&envelope("anchored"))
            .expect("anchored decision");
        store
            .append_checkpoint(b"externally-signed-anchor-receipt")
            .expect("anchored checkpoint");
        anchored_count = store.records().len();
        store.backup(&backup).expect("backup anchored generation");
        store
            .append(
                PlannerStoreRecordKindV1::TerminalReceipt,
                b"post-backup-unanchored-terminal",
            )
            .expect("post-backup record");
        assert!(store.records().len() > anchored_count);
    }

    PlannerStoreV1::restore_from_backup(&restored, &backup).expect("restore backup");
    let restored_store = PlannerStoreV1::open(&restored).expect("open restored store");
    assert_eq!(restored_store.records().len(), anchored_count);
    assert_eq!(
        restored_store.records().last().expect("checkpoint").kind,
        PlannerStoreRecordKindV1::Checkpoint
    );
}

#[test]
fn canary_rehearsal_cannot_dispatch_without_independent_authorization() {
    let directory = tempfile::tempdir().expect("tempdir");
    let mut store =
        PlannerStoreV1::open(directory.path().join("planner.store")).expect("planner store");
    let mut consumer = ControlRuntimeExecutionConsumerV1::new();
    let canary = envelope("canary");
    let identity = canary.operation_identity_digest;
    consumer
        .commit_decision(&mut store, &canary)
        .expect("durable canary decision");
    consumer
        .record_authority_request(&mut store, identity, &request("canary"))
        .expect("canary authority request");

    assert_eq!(
        consumer.mark_dispatched(&mut store, identity, b"forged-dispatch"),
        Err(ProductExecutionErrorV1::InvalidPhase)
    );
    assert_eq!(
        consumer.operation(identity).expect("canary state").phase,
        ProductExecutionPhaseV1::AuthorityRequested
    );
}
