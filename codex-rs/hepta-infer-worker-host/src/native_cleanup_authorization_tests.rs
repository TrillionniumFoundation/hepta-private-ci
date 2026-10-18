use super::*;
use crate::native_app_server::NativeWorkerConfig;
use crate::native_cleanup_store::CleanupState;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::native::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const REQUEST: &str = "cleanup.original.request";

fn original_dispatch(control: &mut DurableInferenceControl) -> Result<NativePreEffectAbortToken> {
    control.reserve_native(
        NativeRequest {
            request_id: REQUEST.to_owned(),
            principal_id: AGENT.to_owned(),
            worker_generation: 1,
            model: "test-model".to_owned(),
            payload_digest: "a".repeat(64),
        },
        /*maximum_in_flight*/ 2,
    )?;
    let dispatch = NativeDispatch {
        thread_id: "original.thread".to_owned(),
        model_provider: "test-provider".to_owned(),
        context_digest: "b".repeat(64),
        owner_context_digest: None,
        codex_payload_digest: Some("c".repeat(64)),
        codex_request_digest: Some("d".repeat(64)),
        app_server_version: Some("test-version".to_owned()),
        protocol_id: Some("codex.app-server.v2".to_owned()),
        codex_source_admission_digest: Some("e".repeat(64)),
        codex_home_digest: Some("f".repeat(64)),
        codex_connection_id: Some(1),
        codex_session_id: Some("original.session".to_owned()),
        codex_deadline_ms: Some(1),
        codex_authority_epoch: None,
        codex_revocation_revision: None,
        codex_revocation_head_sha256: None,
        codex_authority_witness_sha256: Some("1".repeat(64)),
    };
    let (_, proof) = control.dispatch_native_with_pre_effect_abort_bound(
        REQUEST,
        dispatch,
        NativeTerminalOwnerBinding {
            run_id: "owner.original".to_owned(),
            owner_dispatch_revision: 4,
            context_digest: "b".repeat(64),
            envelope_digest: "2".repeat(64),
        },
    )?;
    Ok(proof)
}

fn original_terminal(control: &mut DurableInferenceControl) -> Result<NativeRunRecord> {
    drop(original_dispatch(control)?);
    control.native_started(REQUEST, "turn.original".to_owned())?;
    Ok(control.settle_native(
        REQUEST,
        NativeRunOutput {
            thread_id: "original.thread".to_owned(),
            turn_id: "turn.original".to_owned(),
            model: "test-model".to_owned(),
            model_provider: "test-provider".to_owned(),
            status: NativeRunStatus::Completed,
            boundary_status: NativeBoundaryStatus::Succeeded,
            output: "fixture terminal".to_owned(),
            observed_output_tokens: Some(3),
            terminal_observed: true,
            stop_reason: None,
            owner_authority: NativeOwnerAuthority::ObservedReady,
            codex_terminal_correlation_digest: Some("3".repeat(64)),
        },
    )?)
}

#[tokio::test]
async fn native_cleanup_never_promotes_indeterminate_rejection_or_unacknowledged_abort()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let mut rejected =
        DurableInferenceControl::open(directory.path().join("rejected"), /*capacity*/ 8)?;
    drop(original_dispatch(&mut rejected)?);
    let record = rejected.reject_native_before_start(
        REQUEST,
        NativeDispatchRejection {
            status: NativeDispatchRejectionStatus::Rejected,
            reason: "fixture rejection without proof of non-admission".to_owned(),
            response_digest: "4".repeat(64),
            retry_safe_before_admission: false,
        },
    )?;
    assert_eq!(record.state, NativeReservationState::Indeterminate);
    assert!(!terminal_cleanup_eligible(&record));
    let mut aborted =
        DurableInferenceControl::open(directory.path().join("aborted"), /*capacity*/ 8)?;
    let token = original_dispatch(&mut aborted)?;
    let pending = aborted.prepare_native_abort_before_effect(
        token,
        "owner.original".to_owned(),
        /*owner_dispatch_revision*/ 4,
        "5".repeat(64),
        "fixture unsent abort".to_owned(),
    )?;
    assert_eq!(pending.state, NativeReservationState::AbortPending);
    assert!(!terminal_cleanup_eligible(&pending));
    let abort = pending.pre_effect_abort.as_ref().ok_or("abort proof")?;
    let confirmed = aborted.confirm_native_abort_before_effect(REQUEST, &abort.proof_digest)?;
    assert_eq!(confirmed.state, NativeReservationState::Released);
    assert!(terminal_cleanup_eligible(&confirmed));
    drop(aborted);
    let recovered =
        DurableInferenceControl::open(directory.path().join("aborted"), /*capacity*/ 8)?;
    assert!(terminal_cleanup_eligible(
        &recovered
            .native_record_resolved(REQUEST)?
            .ok_or("recovered abort")?
    ));
    Ok(())
}

#[tokio::test]
async fn native_cleanup_requires_original_outbox_ack_and_exact_session_on_recovery() -> Result<()> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("control.journal");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8)?;
    let terminal = original_terminal(&mut control)?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: directory.path().join("agentd.sock"),
        agent_id: AgentId::parse(AGENT)?,
        generation: 1,
        model: "test-model".to_owned(),
        timeout: Duration::from_secs(30),
    })?;
    let store = driver.cleanup_owner.get().await?;
    let operation = cleanup_operation_id(REQUEST);
    let prepared = store
        .enqueue(
            operation.clone(),
            "original.thread".to_owned(),
            "original.session".to_owned(),
        )
        .await?;
    let unknown = store.mark_effect_possible(&prepared).await?;
    assert!(!terminal_cleanup_eligible(&terminal));
    driver.mark_cleanup_after_ack(&control, REQUEST).await?;
    assert_eq!(store.obligation(&operation).await?, Some(unknown.clone()));
    assert!(
        store
            .claim_ready(
                "before-ack".to_owned(),
                Duration::from_secs(1),
                /*limit*/ 8
            )
            .await?
            .is_empty()
    );
    let publication = terminal.terminal_publication.as_ref().ok_or("outbox")?;
    control.acknowledge_native_terminal_publication(
        REQUEST,
        &publication.publication_digest,
        /*owner_revision*/ 5,
    )?;
    control.maintain_native_history(/*maximum_records*/ 32, Duration::from_secs(2))?;
    assert!(
        control.native_record(REQUEST).is_none(),
        "the original ACKed record must actually be cold"
    );
    drop(control);
    let recovered = DurableInferenceControl::open(&path, /*capacity*/ 8)?;
    driver.mark_cleanup_after_ack(&recovered, REQUEST).await?;
    let ready = store.obligation(&operation).await?.ok_or("ready")?;
    assert_eq!(ready.state, CleanupState::TerminalDurable);
    let claim = store
        .claim_exact(&ready, "after-ack".to_owned(), Duration::from_secs(1))
        .await?
        .ok_or("claim")?;
    assert!(cleanup_claim_matches_control(
        &recovered,
        &driver.config,
        &claim
    )?);
    let mut legacy = claim.clone();
    legacy.operation_id = "native:legacy-opaque-digest".to_owned();
    assert!(!cleanup_claim_matches_control(
        &recovered,
        &driver.config,
        &legacy
    )?);
    let mut replacement = claim.clone();
    replacement.session_id = "replacement.session".to_owned();
    assert!(!cleanup_claim_matches_control(
        &recovered,
        &driver.config,
        &replacement
    )?);
    assert_eq!(
        (&claim.thread_id, &claim.session_id),
        (&ready.thread_id, &ready.session_id)
    );
    // A failed disposal keeps the same session and resumes the durable state.
    store.fail(&claim, "fixture shutdown pending").await?;
    let retained = store.obligation(&operation).await?.ok_or("retained")?;
    assert_eq!(
        (retained.state, retained.thread_id, retained.session_id),
        (
            CleanupState::TerminalDurable,
            "original.thread".to_owned(),
            "original.session".to_owned()
        )
    );
    Ok(())
}

#[tokio::test]
async fn native_cleanup_refuses_replacement_session_and_unowned_intelligence_publication()
-> Result<()> {
    let directory = tempfile::tempdir()?;
    let mut control =
        DurableInferenceControl::open(directory.path().join("control"), /*capacity*/ 8)?;
    let mut terminal = original_terminal(&mut control)?;
    let publication = terminal.terminal_publication.as_ref().ok_or("outbox")?;
    control.acknowledge_native_terminal_publication(
        REQUEST,
        &publication.publication_digest,
        /*owner_revision*/ 5,
    )?;
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: directory.path().join("agentd.sock"),
        agent_id: AgentId::parse(AGENT)?,
        generation: 1,
        model: "test-model".to_owned(),
        timeout: Duration::from_secs(30),
    })?;
    let store = driver.cleanup_owner.get().await?;
    let operation = cleanup_operation_id(REQUEST);
    let prepared = store
        .enqueue(
            operation.clone(),
            "original.thread".to_owned(),
            "replacement.session".to_owned(),
        )
        .await?;
    let unknown = store.mark_effect_possible(&prepared).await?;
    assert!(
        driver
            .mark_cleanup_after_ack(&control, REQUEST)
            .await
            .is_err()
    );
    assert_eq!(store.obligation(&operation).await?, Some(unknown));
    terminal.terminal_publication = None;
    assert!(
        !terminal_cleanup_eligible(&terminal),
        "an Intelligence owner cannot acquire authority from a missing outbox"
    );
    terminal.terminal_owner = None;
    assert!(
        terminal_cleanup_eligible(&terminal),
        "native-only reference terminality has no invented Intelligence owner"
    );
    terminal.state = NativeReservationState::Indeterminate;
    assert!(!terminal_cleanup_eligible(&terminal));
    Ok(())
}
