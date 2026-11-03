//! Valid historical double-claimed chains must not cross effect admission.

use super::*;
use crate::effect_dispatch_ledger::EffectDispatchStart;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn historical_sibling_claim_blocks_dispatch_until_terminal_settlement() {
    let (_temp, layout, store, fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let intent = Sha256Digest::for_bytes(b"effect-intent");
    let payload = Sha256Digest::for_bytes(b"effect-payload");
    // Reconstruct exactly the valid append-only history authored by the old
    // prepare/claim implementation, without weakening current admission.
    let mut tx = store.begin_step_write_tx().await.expect("writer");
    for (operation, state) in [
        ("prepare", TaskFlowStepState::Prepared),
        ("claim", TaskFlowStepState::Claimed),
    ] {
        let command = format!("historical-sibling-{operation}");
        let digest = operation_digest(
            operation,
            store.taskflow_owner_agent_id(),
            "effect-run",
            "work",
            /*attempt*/ 2,
            &command,
            intent.as_str(),
            payload.as_str(),
            &fence,
            /*receipt_digest*/ None,
            /*observation*/ None,
            /*final_outcome*/ None,
            /*now_ms*/ 20,
        )
        .expect("historical command digest");
        append_step_event(
            &mut tx,
            &store,
            "effect-run",
            "work",
            /*attempt*/ 2,
            state,
            &command,
            digest.as_str(),
            intent.as_str(),
            payload.as_str(),
            /*receipt_digest*/ None,
            /*observation*/ None,
            /*final_outcome*/ None,
            &fence,
            /*recorded_at_ms*/ 20,
        )
        .await
        .expect("append valid historical event");
    }
    tx.commit().await.expect("commit historical chain");
    store.close().await;
    let store = AutomationStore::open(&layout).await.expect("reopen history");
    let mut before = Vec::new();
    for attempt in [1, 2] {
        before.push(
            store
                .read_taskflow_step("effect-run", "work", attempt, &fence)
                .await
                .expect("historical receipt"),
        );
        assert_eq!(
            store
                .read_taskflow_step("effect-run", "work", attempt, &fence)
                .await
                .expect("verify complete historical chain")
                .expect("historical step")
                .state,
            TaskFlowStepState::Claimed
        );
    }
    let binding = Sha256Digest::for_bytes(b"effect-binding");
    let nonce = Sha256Digest::for_bytes(b"effect-nonce");
    let clock_called = std::sync::atomic::AtomicBool::new(false);
    let rejected = store
        .begin_effect_dispatch_attempt(
            "effect-run",
            "work",
            /*attempt*/ 1,
            &intent,
            &payload,
            &binding,
            "provider:test",
            /*authority_epoch*/ 7,
            "sibling-grant",
            &nonce,
            "sibling-record",
            || {
                clock_called.store(true, std::sync::atomic::Ordering::SeqCst);
                Ok(21)
            },
            &fence,
            /*provider_contract_binding*/ None,
        )
        .await;
    assert!(matches!(rejected, Err(TaskFlowError::Conflict(_))));
    assert!(!clock_called.load(std::sync::atomic::Ordering::SeqCst));
    assert!(
        store
            .effect_dispatch_attempt("effect-run", "work", /*attempt*/ 1)
            .await
            .expect("no new dispatch")
            .is_none()
    );
    for (index, attempt) in [1, 2].into_iter().enumerate() {
        assert_eq!(
            store
                .read_taskflow_step("effect-run", "work", attempt, &fence)
                .await
                .expect("unchanged historical receipt"),
            before[index]
        );
    }
    let dispatch_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM taskflow_effect_dispatch_attempts",
    )
    .fetch_one(store.taskflow_pool())
    .await
    .expect("all dispatch rows");
    assert_eq!(dispatch_rows, 0);
    store
        .record_taskflow_step(
            "effect-run",
            "work",
            /*attempt*/ 2,
            &fence,
            &intent,
            &payload,
            "sibling-terminal",
            &Sha256Digest::for_bytes(b"terminal sibling"),
            TaskFlowStepObservation::Failed,
            /*now_ms*/ 22,
        )
        .await
        .expect("settle sibling");
    let admitted = store
        .begin_effect_dispatch_attempt(
            "effect-run",
            "work",
            /*attempt*/ 1,
            &intent,
            &payload,
            &binding,
            "provider:test",
            /*authority_epoch*/ 7,
            "sibling-grant",
            &nonce,
            "sibling-record",
            || Ok(23),
            &fence,
            /*provider_contract_binding*/ None,
        )
        .await
        .expect("terminal sibling permits dispatch admission");
    assert!(matches!(admitted, EffectDispatchStart::Inserted(_)));
    store.close().await;
}

#[tokio::test]
async fn distinct_steps_and_runs_do_not_block_effect_admission() {
    let (_temp, _layout, store, fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let intent = Sha256Digest::for_bytes(b"effect-intent");
    let payload = Sha256Digest::for_bytes(b"effect-payload");
    let definition = crate::TaskFlowDefinition::new(
        "independent-steps",
        /*version*/ 1,
        "work",
        vec![
            crate::TaskFlowNodeSpec::new("work", crate::TaskFlowNodeKind::Activity),
            crate::TaskFlowNodeSpec::new("other", crate::TaskFlowNodeKind::Activity),
            crate::TaskFlowNodeSpec::new("done", crate::TaskFlowNodeKind::TerminalSuccess),
            crate::TaskFlowNodeSpec::new("failed", crate::TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            crate::TaskFlowEdgeSpec::new("work", "other"),
            crate::TaskFlowEdgeSpec::new("other", "done"),
            crate::TaskFlowEdgeSpec::new("other", "failed"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"independent-policy"),
    )
    .expect("definition");
    store
        .register_taskflow_definition(&definition, &fence, /*registered_at_ms*/ 20)
        .await
        .expect("register");
    store
        .create_taskflow_run(
            "independent-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "independent-thread",
            /*created_at_ms*/ 20,
        )
        .await
        .expect("create");
    let claimed = store
        .claim_taskflow_run(
            "independent-run", &fence, /*now_ms*/ 20, /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim run");
    store
        .apply_taskflow_command(
            &crate::TaskFlowCommand::new(
                "independent-run", "start-independent", fence.clone(), claimed.revision,
                crate::TaskFlowTransition::Start, /*now_ms*/ 20,
            )
            .expect("start command"),
        )
        .await
        .expect("start");
    for step in ["work", "other"] {
        store
            .prepare_taskflow_step(
                "independent-run", step, /*attempt*/ 1, &fence, &intent, &payload,
                &format!("independent-prepare-{step}"), /*now_ms*/ 21,
            )
            .await
            .expect("different step prepares");
        store
            .claim_taskflow_step(
                "independent-run", step, /*attempt*/ 1, &fence, &intent, &payload,
                &format!("independent-claim-{step}"), /*now_ms*/ 22,
            )
            .await
            .expect("different step claims");
    }
    // Both effect-run/work and independent-run/other remain Claimed.
    let admitted = store
        .begin_effect_dispatch_attempt(
            "independent-run", "work", /*attempt*/ 1, &intent, &payload,
            &Sha256Digest::for_bytes(b"independent-binding"), "provider:test",
            /*authority_epoch*/ 7, "independent-grant",
            &Sha256Digest::for_bytes(b"independent-nonce"), "independent-record",
            || Ok(23), &fence, /*provider_contract_binding*/ None,
        )
        .await
        .expect("other steps and runs do not block");
    assert!(matches!(admitted, EffectDispatchStart::Inserted(_)));
    store.close().await;
}
