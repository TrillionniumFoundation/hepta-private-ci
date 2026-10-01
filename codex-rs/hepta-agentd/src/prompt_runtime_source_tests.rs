use super::*;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use pretty_assertions::assert_eq;

fn product_request() -> PromptRuntimePrepareRequest {
    PromptRuntimePrepareRequest {
        thread_id: "thread:product".to_owned(),
        turn_id: "turn:product".to_owned(),
        model_context_window: Some(128),
    }
}

#[test]
fn pipeline_attachment_deadline_is_capped_at_selected_portfolio_expiry() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let fixture = staged_product_pipeline(&temporary);
    let staged = fixture
        .pipeline
        .runtime_owner()
        .prepare(product_request())
        .unwrap()
        .unwrap();
    // The actual pipeline requested wall_now + 60_000; selection expires first.
    assert_eq!(staged.deadline_ms, fixture.wall_now + 10_000);
    staged.validate().unwrap();
}

#[test]
fn signed_revoke_after_reopen_blocks_staged_prompt_before_deadline() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let ProductPromptFixture {
        pipeline,
        authority,
        signing_key,
        wall_now,
    } = staged_product_pipeline(&temporary);
    let runtime = pipeline.runtime_owner();
    let staged = runtime.prepare(product_request()).unwrap().unwrap();
    assert!(wall_now < staged.deadline_ms);
    drop(runtime);
    drop(pipeline);

    {
        let mut registry = DurablePromptRegistry::open_state_dir(
            &temporary.path().join("prompt-registry"),
            /*maximum_records*/ 64,
        )
        .unwrap();
        let factor_id = id("factor:agentd-product");
        let factor = registry.registry().unwrap().factor(&factor_id).unwrap();
        let actor = id("reviewer:agentd-revoke");
        let scope = digest("scope:agentd-revoke");
        let reason = digest("reason:agentd-revoke");
        let binding = final_use_revoke_binding(factor, &actor, scope, reason, wall_now).unwrap();
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "review-authority:agentd-prompt".to_owned(),
            authority_epoch: 1,
            grant_id: "grant:agentd-prompt-revoke".to_owned(),
            nonce: [64; 32],
            binding,
            not_before_unix_ms: wall_now.saturating_sub(1_000),
            expires_at_unix_ms: wall_now + 30_000,
        };
        let signed = SignedFinalUseGrant {
            signature: signing_key
                .sign(&grant.signing_bytes().unwrap())
                .to_bytes()
                .to_vec(),
            grant,
        };
        registry
            .revoke_factor_final_use(
                &authority, &signed, &factor_id, &actor, scope, reason, wall_now,
            )
            .unwrap();
    }

    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        &temporary.path().join("prompt-runtime"),
        /*maximum_registry_records*/ 64,
    )
    .unwrap();
    let runtime = reopened.runtime_owner();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    assert!(now < staged.deadline_ms);
    assert_eq!(
        runtime.prepare(product_request()),
        Err(host_error(AgentdPromptRuntimeError::SourceValidationFailed))
    );
    assert_eq!(runtime.staged_count().unwrap(), 1);
    assert_eq!(
        runtime.record_dispatch(dispatch(
            &staged,
            "thread:product",
            "turn:product",
            "attempt:stale",
            "request:stale",
            digest("request:stale")
        )),
        Err(host_error(AgentdPromptRuntimeError::SourceValidationFailed))
    );
    assert_eq!(runtime.dispatch_record("attempt:stale").unwrap(), None);
}

#[test]
fn cached_prepare_and_idempotent_dispatch_recheck_current_owner() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let fixture = staged_product_pipeline(&temporary);
    let runtime = fixture.pipeline.runtime_owner();
    let staged = runtime.prepare(product_request()).unwrap().unwrap();
    let first = dispatch(
        &staged,
        "thread:product",
        "turn:product",
        "attempt:first",
        "request:first",
        digest("request:first"),
    );
    runtime.record_dispatch(first.clone()).unwrap();
    let terminal = PromptRuntimeTerminalRecordV1 {
        compilation_id: first.compilation_id.clone(),
        context_attachment_digest: first.context_attachment_digest,
        context_payload_digest: first.context_payload_digest,
        source_binding_digest: first.source_binding_digest,
        thread_id: first.thread_id.clone(),
        turn_id: first.turn_id.clone(),
        attempt_id: first.attempt_id.clone(),
        request_binding_id: first.request_binding_id.clone(),
        provider_request_digest: first.provider_request_digest,
        outcome: PromptRuntimeTerminalOutcomeV1::NotDispatched,
        end_turn: None,
        terminal_reason_code: Some("pre_send_cancel".to_owned()),
        delivery_observation: None,
        observed_unix_ms: 10,
    };
    runtime.record(terminal.clone()).unwrap();
    {
        let mut registry = fixture.pipeline.registry.lock().unwrap();
        let mut additional = registry
            .registry()
            .unwrap()
            .factor(&id("factor:agentd-product"))
            .unwrap()
            .clone();
        additional.factor_id = id("factor:additional");
        additional.content_digest = digest("factor:additional");
        additional.lifecycle = Lifecycle::Draft;
        registry.register_factor(additional).unwrap();
    }
    let rejected = Err(host_error(AgentdPromptRuntimeError::SourceValidationFailed));
    assert_eq!(runtime.record_dispatch(first.clone()), rejected);
    assert_eq!(
        runtime.record_dispatch(dispatch(
            &staged,
            "thread:product",
            "turn:product",
            "attempt:cached",
            "request:cached",
            digest("request:cached")
        )),
        rejected
    );
    assert_eq!(runtime.dispatch_record("attempt:cached").unwrap(), None);
    assert_eq!(
        runtime.dispatch_record("attempt:first").unwrap(),
        Some(first)
    );
    // Historical observations remain recordable after source drift.
    runtime.record(terminal.clone()).unwrap();
    assert_eq!(
        runtime.terminal_record("attempt:first").unwrap(),
        Some(terminal)
    );
}

#[test]
fn legacy_unbound_stage_is_restored_but_cannot_dispatch_through_pipeline() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap();
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
    }
    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        &root,
        /*maximum_registry_records*/ 64,
    )
    .unwrap();
    let runtime = pipeline.runtime_owner();
    assert_eq!(
        runtime.prepare(PromptRuntimePrepareRequest {
            thread_id: "thread:one".to_owned(),
            turn_id: "turn:one".to_owned(),
            model_context_window: Some(4096)
        }),
        Err(host_error(AgentdPromptRuntimeError::SourceValidationFailed))
    );
    assert_eq!(
        runtime.record_dispatch(dispatch(
            &value,
            "thread:one",
            "turn:one",
            "attempt:legacy",
            "request:legacy",
            digest("request:legacy")
        )),
        Err(host_error(AgentdPromptRuntimeError::SourceValidationFailed))
    );
    assert_eq!(runtime.staged_count().unwrap(), 1);
}

#[test]
fn legacy_pending_dispatch_can_be_reconciled_through_bound_pipeline() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let root = temporary.path().join("prompt-runtime");
    let value = attachment();
    let request_digest = digest("request:legacy-pending");
    let claim = dispatch(
        &value,
        "thread:one",
        "turn:one",
        "attempt:legacy",
        "request:legacy",
        request_digest,
    );
    {
        let owner = AgentdPromptRuntimeOwner::open_state_dir(&root).unwrap();
        stage_raw(&owner, "thread:one", "turn:one", value.clone());
        owner.record_dispatch(claim.clone()).unwrap();
    }
    let pipeline = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        &root,
        /*maximum_registry_records*/ 64,
    )
    .unwrap();
    let runtime = pipeline.runtime_owner();
    let terminal = delivered_terminal(
        &value,
        "attempt:legacy",
        "request:legacy",
        request_digest,
        10,
    );
    runtime.record(terminal.clone()).unwrap();
    assert_eq!(
        runtime.dispatch_record("attempt:legacy").unwrap(),
        Some(claim)
    );
    assert_eq!(
        runtime.terminal_record("attempt:legacy").unwrap(),
        Some(terminal)
    );
    assert_eq!(runtime.staged_count().unwrap(), 0);
}

#[test]
fn persisted_registry_source_digest_is_checked_on_restore() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    drop(staged_product_pipeline(&temporary));
    let path = temporary.path().join("prompt-runtime").join(STATE_FILE);
    let mut stored: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    let digest = &mut stored["staged"][0]["registry_source"]["registry_digest"][0];
    *digest = serde_json::Value::from(digest.as_u64().unwrap() ^ 1);
    std::fs::write(&path, serde_json::to_vec(&stored).unwrap()).unwrap();
    assert!(matches!(
        AgentdPromptRuntimeOwner::open_state_dir(&temporary.path().join("prompt-runtime")),
        Err(AgentdPromptRuntimeError::CorruptState)
    ));
}

#[test]
fn waiting_prepare_rechecks_poison_after_indeterminate_commit() {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let fixture = staged_product_pipeline(&temporary);
    let runtime = fixture.pipeline.runtime_owner();
    runtime.fail_directory_sync_after_rename_once();
    let (entered_tx, entered_rx) = std::sync::mpsc::sync_channel(0);
    let (release_tx, release_rx) = std::sync::mpsc::sync_channel(0);
    let writer_owner = Arc::clone(&runtime);
    let writer = std::thread::spawn(move || {
        writer_owner.commit_state(|state| {
            entered_tx.send(()).unwrap();
            release_rx.recv().unwrap();
            state.staged.clear();
            state.stage_sources.clear();
            Ok(())
        })
    });
    entered_rx.recv().unwrap();
    let prepare_owner = Arc::clone(&runtime);
    let waiter = std::thread::spawn(move || prepare_owner.prepare(product_request()));

    // The writer holds state. Holding registry proves prepare passed its first
    // availability check and is now waiting for the state lock, without sleeps.
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
    let waiting = loop {
        match fixture.pipeline.registry.try_lock() {
            Err(std::sync::TryLockError::WouldBlock) => break true,
            Err(std::sync::TryLockError::Poisoned(_)) => break false,
            Ok(guard) => drop(guard),
        }
        if std::time::Instant::now() >= deadline {
            break false;
        }
        std::thread::yield_now();
    };
    release_tx.send(()).unwrap();
    assert_eq!(
        writer.join().unwrap(),
        Err(AgentdPromptRuntimeError::IndeterminateDurability)
    );
    assert_eq!(
        waiter.join().unwrap(),
        Err(host_error(AgentdPromptRuntimeError::ReopenRequired))
    );
    assert!(waiting);
    // Reads and commits share prepare's lock_state check, so no caller can
    // interpret the old in-memory snapshot as authoritative after this failure.
    assert_eq!(
        runtime.staged_count(),
        Err(AgentdPromptRuntimeError::ReopenRequired)
    );
    assert_eq!(
        runtime.dispatch_record("attempt:absent"),
        Err(AgentdPromptRuntimeError::ReopenRequired)
    );
    assert_eq!(
        runtime.terminal_record("attempt:absent"),
        Err(AgentdPromptRuntimeError::ReopenRequired)
    );
    assert_eq!(
        runtime.clear_turn("thread:product", "turn:product"),
        Err(AgentdPromptRuntimeError::ReopenRequired)
    );
    drop(runtime);
    drop(fixture);
    let reopened = AgentdPromptPipelineOwner::open_state_dirs(
        &temporary.path().join("prompt-registry"),
        &temporary.path().join("prompt-runtime"),
        /*maximum_registry_records*/ 64,
    )
    .unwrap();
    assert_eq!(reopened.runtime_owner().staged_count().unwrap(), 0);
}
