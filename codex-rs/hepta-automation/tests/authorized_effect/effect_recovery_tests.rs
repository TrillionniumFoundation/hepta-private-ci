use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owned_effect_fence_survives_terminal_run_lease_clear_and_reopen() {
    for (outcome, state) in [
        (
            AuthorizedEffectOutcome::Succeeded,
            TaskFlowRunState::Succeeded,
        ),
        (AuthorizedEffectOutcome::Failed, TaskFlowRunState::Failed),
    ] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        assert_eq!(
            store
                .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
                .await
                .expect("uncontacted step read"),
            None,
            "step history alone cannot supply an effect recovery fence"
        );
        let (authority, signed, _authority_dir) = final_use(expected.clone(), "terminal-fence");
        let mut driver = RecordingDriver::receipt(outcome, b"terminal-fence-receipt");
        let receipt = store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "terminal-fence-dispatch",
                /*now_ms*/ 30,
            )
            .await
            .expect("terminal effect");
        let run = store
            .taskflow_run(&effect.run_id)
            .await
            .expect("terminal run read")
            .expect("terminal run");
        assert_eq!(run.state, state);
        assert_eq!(
            (
                run.owner_id,
                run.owner_epoch,
                run.generation,
                run.fencing_token,
                run.lease_expires_at_ms,
            ),
            (None, None, None, None, None),
        );
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen terminal store");
        let recovered = reopened
            .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("verified historical effect fence")
            .expect("owned effect fence");
        assert_eq!(recovered, owner);
        assert_eq!(
            reopened
                .settle_authorized_taskflow_effect_observation(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &recovered,
                )
                .await
                .expect("settle durable terminal evidence"),
            Some(AuthorizedEffectRecoveryResult::Observed(receipt)),
        );
        assert_eq!(
            reopened
                .authorized_taskflow_effect_fence(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt + 1,
                )
                .await
                .expect("different attempt read"),
            None,
        );
        assert_eq!(driver.calls, 1);
    }
}

#[tokio::test]
async fn unresolved_effect_fence_retains_exact_owner_identity() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "unresolved-fence");
    let mut driver = RecordingDriver::receipt(AuthorizedEffectOutcome::Indeterminate, b"unknown");
    store
        .execute_authorized_taskflow_effect(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "unresolved-fence-dispatch",
            /*now_ms*/ 30,
        )
        .await
        .expect("indeterminate effect");
    assert_eq!(
        store
            .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("historical unresolved owner"),
        Some(owner.clone()),
    );
    let mut wrong_owner = owner;
    wrong_owner.generation += 1;
    assert!(matches!(
        store
            .read_taskflow_step(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &wrong_owner
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::StaleFence),
    ));
    assert_eq!(driver.calls, 1);
}

#[tokio::test]
async fn proven_absent_effect_recovery_survives_successor_owner_and_attempt() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "absence-successor");
    let adapter = RecordingProviderEffectAdapter::new(
        ProviderEffectDispatch::Unknown,
        ProviderEffectLookup::NotFound,
    );
    let mut driver =
        ProviderEffectTaskFlowDriver::new(effect.destination_id.clone(), adapter).expect("driver");
    store
        .execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &effect,
            EFFECT_PAYLOAD,
            &owner,
            &signed,
            &expected,
            "absence-successor-dispatch",
            /*now_ms*/ 30,
        )
        .await
        .expect("unknown dispatch");
    let proof_digest = Sha256Digest::for_bytes(b"authoritative-provider-absence");
    assert_eq!(
        store
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::ProvenAbsent {
                    proof_digest: proof_digest.clone(),
                },
                /*observed_at_ms*/ 31,
            )
            .await
            .expect("prove absence after unknown"),
        AuthorizedEffectRecoveryResult::ProvenAbsent,
    );
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen");
    let historical = reopened
        .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
        .await
        .expect("cleared owner history")
        .expect("absence fence");
    assert_eq!(historical, owner);
    assert_eq!(
        reopened
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &historical,
            )
            .await
            .expect("repeat queued absence"),
        Some(AuthorizedEffectRecoveryResult::ProvenAbsent),
    );
    let mut successor = owner.clone();
    successor.owner_id = "successor-effect-owner".to_string();
    successor.owner_epoch += 1;
    successor.generation += 1;
    successor.fencing_token = "successor-effect-fence".to_string();
    let claimed = reopened
        .claim_taskflow_run(
            &effect.run_id,
            &successor,
            /*now_ms*/ 40,
            /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("terminal reconciliation absence permits retry");
    reopened
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &effect.run_id,
                "absence-successor-start",
                successor.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 41,
            )
            .expect("successor start command"),
        )
        .await
        .expect("start successor");
    let mut next_effect = effect.clone();
    next_effect.attempt += 1;
    let next_digest = next_effect.digest().expect("successor intent");
    reopened
        .prepare_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &successor,
            &next_digest,
            &next_effect.payload_digest,
            "absence-successor-prepare",
            /*now_ms*/ 42,
        )
        .await
        .expect("prepare successor attempt");
    let next_step = reopened
        .claim_taskflow_step(
            &next_effect.run_id,
            &next_effect.step_id,
            next_effect.attempt,
            &successor,
            &next_digest,
            &next_effect.payload_digest,
            "absence-successor-claim",
            /*now_ms*/ 43,
        )
        .await
        .expect("claim successor attempt")
        .receipt;
    let next_run = reopened
        .taskflow_run(&effect.run_id)
        .await
        .expect("run snapshot");
    let page = reopened
        .scan_authorized_taskflow_effects(/*cursor*/ None, /*limit*/ 1)
        .await
        .expect("settled absence remains excluded after successor advancement");
    assert!(page.effects.is_empty());
    assert_eq!(
        page.progress,
        codex_hepta_automation::AuthorizedEffectRecoveryProgress::Complete
    );
    assert_eq!(
        reopened
            .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("old absence under successor"),
        Some(owner.clone()),
    );
    assert_eq!(
        reopened
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &owner,
                AuthorizedEffectRecovery::ProvenAbsent { proof_digest },
                /*observed_at_ms*/ 44,
            )
            .await
            .expect("repeat old absence under successor"),
        AuthorizedEffectRecoveryResult::ProvenAbsent,
    );
    assert!(matches!(
        reopened
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &successor,
            )
            .await,
        Err(AuthorizedEffectError::TaskFlow(
            codex_hepta_automation::TaskFlowError::StaleFence
        )),
    ));
    assert_eq!(
        reopened
            .taskflow_run(&effect.run_id)
            .await
            .expect("run unchanged"),
        next_run
    );
    assert_eq!(
        reopened
            .read_taskflow_step(
                &next_effect.run_id,
                &next_effect.step_id,
                next_effect.attempt,
                &successor,
            )
            .await
            .expect("successor step unchanged"),
        Some(next_step),
    );
    assert_eq!(driver.adapter().dispatch_calls.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn pre_contact_absence_recovers_after_cleared_run_owner() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _authority_dir) = final_use(expected.clone(), "pre-contact-fence");
    let mut driver = RecordingDriver::before_provider_contact();
    assert!(matches!(
        store
            .execute_authorized_taskflow_effect(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "pre-contact-fence-dispatch",
                /*now_ms*/ 30,
            )
            .await,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        )),
    ));
    let historical = store
        .authorized_taskflow_effect_fence(&effect.run_id, &effect.step_id, effect.attempt)
        .await
        .expect("claimed cancellation history")
        .expect("owned absence fence");
    assert_eq!(historical, owner);
    assert_eq!(
        store
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &historical,
            )
            .await
            .expect("repeat claimed cancellation"),
        Some(AuthorizedEffectRecoveryResult::ProvenAbsent),
    );
    assert_eq!(driver.calls, 1);
}
