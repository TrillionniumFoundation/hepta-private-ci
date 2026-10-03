use super::*;
use crate::TaskFlowCommand;
use crate::TaskFlowFence;
use crate::TaskFlowTransition;
use crate::effect_dispatch_ledger::tests::prepared_store;

async fn append_attempt(store: &AutomationStore, fence: &TaskFlowFence, run_id: &str) {
    let intent = Sha256Digest::for_bytes(b"effect-intent");
    let payload = Sha256Digest::for_bytes(b"effect-payload");
    if run_id != "effect-run" {
        let base = store
            .taskflow_run("effect-run")
            .await
            .expect("base")
            .expect("run");
        store
            .create_taskflow_run(
                run_id,
                &base.workflow_id,
                base.workflow_version,
                &base.definition_digest,
                "scan-thread",
                /*now_ms*/ 10,
            )
            .await
            .expect("run");
        let claimed = store
            .claim_taskflow_run(
                run_id, fence, /*now_ms*/ 20, /*lease_duration_ms*/ 10_000,
            )
            .await
            .expect("claim");
        store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    run_id,
                    "start",
                    fence.clone(),
                    claimed.revision,
                    TaskFlowTransition::Start,
                    /*now_ms*/ 20,
                )
                .expect("command"),
            )
            .await
            .expect("start");
        store
            .prepare_taskflow_step(
                run_id,
                "work",
                /*attempt*/ 1,
                fence,
                &intent,
                &payload,
                &format!("prepare:{run_id}"),
                /*now_ms*/ 20,
            )
            .await
            .expect("prepare");
        store
            .claim_taskflow_step(
                run_id,
                "work",
                /*attempt*/ 1,
                fence,
                &intent,
                &payload,
                &format!("claim:{run_id}"),
                /*now_ms*/ 20,
            )
            .await
            .expect("claim");
    }
    store
        .begin_effect_dispatch_attempt(
            run_id,
            "work",
            /*attempt*/ 1,
            &intent,
            &payload,
            &Sha256Digest::for_bytes(b"scan-binding"),
            "provider:test",
            /*authority_epoch*/ 7,
            run_id,
            &Sha256Digest::for_bytes(run_id.as_bytes()),
            &format!("record:{run_id}"),
            || Ok(21),
            fence,
            /*provider_contract_binding*/ None,
        )
        .await
        .expect("attempt");
}

async fn settle_success(store: &AutomationStore, fence: &TaskFlowFence, run_id: &str) {
    store
        .record_effect_dispatch_observation(
            run_id,
            "work",
            /*attempt*/ 1,
            EffectDispatchObservationKind::Succeeded,
            &Sha256Digest::for_bytes(run_id.as_bytes()),
            /*observed_at_ms*/ 22,
            /*provider*/ None,
        )
        .await
        .expect("terminal fact");
    store
        .settle_authorized_taskflow_effect_observation(run_id, "work", /*attempt*/ 1, fence)
        .await
        .expect("settlement");
}

#[tokio::test]
async fn empty_filtered_page_continues_after_restart_and_new_attempt_waits_for_next_scan() {
    let (_temp, layout, store, fence) = prepared_store().await;
    append_attempt(&store, &fence, "effect-run").await;
    settle_success(&store, &fence, "effect-run").await;
    append_attempt(&store, &fence, "second").await;
    let first = store
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("page");
    assert!(first.effects.is_empty());
    assert_eq!(first.scanned_attempts, 1);
    let AuthorizedEffectRecoveryProgress::More(cursor) = first.progress else {
        panic!("empty is not complete")
    };
    append_attempt(&store, &fence, "later").await;
    store.close().await;
    let reopened = AutomationStore::open(&layout).await.expect("restart");
    let second = reopened
        .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
        .await
        .expect("continued");
    assert_eq!(
        second
            .effects
            .iter()
            .map(|effect| effect.run_id.as_str())
            .collect::<Vec<_>>(),
        vec!["second"]
    );
    assert_eq!(second.scanned_attempts, 1);
    assert_eq!(second.progress, AuthorizedEffectRecoveryProgress::Complete);
    assert_eq!(
        reopened
            .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
            .await
            .expect("replay"),
        second
    );
    settle_success(&reopened, &fence, "second").await;
    let replay = reopened
        .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
        .await
        .expect("current settlement");
    assert!(replay.effects.is_empty());
    assert_eq!(replay.progress, AuthorizedEffectRecoveryProgress::Complete);
    let fresh = reopened
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 3)
        .await
        .expect("next cycle");
    assert_eq!(
        fresh
            .effects
            .iter()
            .map(|effect| effect.run_id.as_str())
            .collect::<Vec<_>>(),
        vec!["later"]
    );
    assert_eq!(fresh.scanned_attempts, 3);
    assert_eq!(fresh.progress, AuthorizedEffectRecoveryProgress::Complete);
}

