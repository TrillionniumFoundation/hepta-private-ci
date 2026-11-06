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

#[tokio::test]
async fn cursor_rejects_wrong_store_owner_anchor_and_invalid_limits() {
    let (_temp, _layout, store, fence) = prepared_store().await;
    append_attempt(&store, &fence, "effect-run").await;
    append_attempt(&store, &fence, "second").await;
    let page = store
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("page");
    let AuthorizedEffectRecoveryProgress::More(cursor) = page.progress else {
        panic!("continuation")
    };
    for limit in [0, 1_025, usize::MAX] {
        assert!(matches!(
            store
                .scan_authorized_taskflow_effects(Some(&cursor), limit)
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
        ));
    }
    let (_other_temp, _other_layout, other, _) = prepared_store().await;
    assert!(matches!(
        other
            .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
            .await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
    ));
    let owner_root = tempfile::tempdir().expect("other owner root");
    let owner = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")
        .expect("owner");
    let other_owner = AutomationStore::open_root(
        owner_root
            .path()
            .canonicalize()
            .expect("root")
            .join("store"),
        owner,
    )
    .await
    .expect("other owner store");
    assert!(matches!(
        other_owner
            .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
            .await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
    ));
    for malformed in [
        AuthorizedEffectRecoveryCursor {
            after: AttemptAnchor {
                rowid: 0,
                ..cursor.after.clone()
            },
            ..cursor.clone()
        },
        AuthorizedEffectRecoveryCursor {
            after: cursor.through.clone(),
            ..cursor.clone()
        },
        AuthorizedEffectRecoveryCursor {
            through: AttemptAnchor {
                identity: Sha256Digest::for_bytes(b"replaced database"),
                ..cursor.through.clone()
            },
            ..cursor.clone()
        },
        AuthorizedEffectRecoveryCursor {
            after: AttemptAnchor {
                identity: Sha256Digest::for_bytes(b"changed immutable attempt"),
                ..cursor.after.clone()
            },
            ..cursor.clone()
        },
    ] {
        assert!(matches!(
            store
                .scan_authorized_taskflow_effects(Some(&malformed), /*limit*/ 1)
                .await,
            Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
        ));
    }
}

#[tokio::test]
async fn conflict_and_wrong_fence_cannot_hide_or_change_terminal_evidence() {
    let (_temp, _layout, store, fence) = prepared_store().await;
    append_attempt(&store, &fence, "effect-run").await;
    let proof = Sha256Digest::for_bytes(b"immutable-terminal");
    let original = store
        .record_effect_dispatch_observation(
            "effect-run",
            "work",
            /*attempt*/ 1,
            EffectDispatchObservationKind::Succeeded,
            &proof,
            /*observed_at_ms*/ 22,
            /*provider*/ None,
        )
        .await
        .expect("terminal fact");
    let mut wrong = fence.clone();
    wrong.fencing_token = "wrong-fence".to_string();
    assert!(
        store
            .settle_authorized_taskflow_effect_observation(
                "effect-run",
                "work",
                /*attempt*/ 1,
                &wrong
            )
            .await
            .is_err()
    );
    assert!(
        store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                /*attempt*/ 1,
                EffectDispatchObservationKind::Failed,
                &Sha256Digest::for_bytes(b"wrong-receipt"),
                /*observed_at_ms*/ 23,
                /*provider*/ None
            )
            .await
            .is_err()
    );
    assert_eq!(
        store
            .effect_dispatch_attempt("effect-run", "work", /*attempt*/ 1)
            .await
            .expect("fact")
            .expect("attempt")
            .observation,
        original.observation
    );
    let page = store
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("still recoverable");
    assert_eq!(page.effects.len(), 1);
    assert_eq!(page.progress, AuthorizedEffectRecoveryProgress::Complete);
    store
        .settle_authorized_taskflow_effect_observation(
            "effect-run",
            "work",
            /*attempt*/ 1,
            &fence,
        )
        .await
        .expect("exact settlement");
    assert!(
        store
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
            .await
            .expect("settled")
            .effects
            .is_empty()
    );
}

#[tokio::test]
async fn retirement_and_vacuum_preserve_read_only_cursor_or_explicitly_reject_changed_anchors() {
    let (_temp, layout, store, fence) = prepared_store().await;
    append_attempt(&store, &fence, "effect-run").await;
    append_attempt(&store, &fence, "second").await;
    let page = store
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("page");
    let AuthorizedEffectRecoveryProgress::More(cursor) = page.progress else {
        panic!("continuation")
    };
    assert!(
        sqlx::query("DELETE FROM taskflow_effect_dispatch_attempts")
            .execute(store.taskflow_pool())
            .await
            .is_err()
    );
    assert!(
        sqlx::query("UPDATE taskflow_effect_dispatch_attempts SET rowid = rowid + 100")
            .execute(store.taskflow_pool())
            .await
            .is_err()
    );
    sqlx::query("VACUUM")
        .execute(store.taskflow_pool())
        .await
        .expect("vacuum");
    store
        .quiesce_timer()
        .await
        .expect("quiesce unrelated timer admission");
    store
        .retire_timer()
        .await
        .expect("retire timer without deleting history");
    store.close().await;
    let reopened = AutomationStore::open(&layout)
        .await
        .expect("reopen retired owner");
    match reopened
        .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
        .await
    {
        Ok(page) => {
            assert_eq!(
                page.effects
                    .iter()
                    .map(|effect| effect.run_id.as_str())
                    .collect::<Vec<_>>(),
                vec!["second"]
            );
            assert_eq!(page.scanned_attempts, 1);
            assert_eq!(page.progress, AuthorizedEffectRecoveryProgress::Complete);
        }
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_))) => {}
        result => {
            panic!("vacuum must preserve exact continuation or reject stale anchors: {result:?}")
        }
    }
}

#[tokio::test]
async fn replacement_database_at_same_path_rejects_old_high_water_identity() {
    let (_temp, layout, store, fence) = prepared_store().await;
    append_attempt(&store, &fence, "effect-run").await;
    append_attempt(&store, &fence, "second").await;
    let page = store
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("page");
    let AuthorizedEffectRecoveryProgress::More(cursor) = page.progress else {
        panic!("continuation")
    };
    let (_other_temp, _other_layout, other, other_fence) = prepared_store().await;
    append_attempt(&other, &other_fence, "effect-run").await;
    append_attempt(&other, &other_fence, "replacement").await;
    store.close().await;
    other.close().await;
    std::fs::copy(other.path(), store.path()).expect("replace closed test database");
    let replaced = AutomationStore::open(&layout)
        .await
        .expect("valid replacement store");
    assert!(matches!(
        replaced
            .scan_authorized_taskflow_effects(Some(&cursor), /*limit*/ 1)
            .await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::Invalid(_)))
    ));
    assert_eq!(
        replaced
            .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 2)
            .await
            .expect("fresh scan")
            .effects
            .len(),
        2
    );
}
