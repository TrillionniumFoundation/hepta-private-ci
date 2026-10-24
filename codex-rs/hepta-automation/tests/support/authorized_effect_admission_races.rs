//! Actual SQLite owner serialization; no adapter-local mutex supplies the proof.

use super::*;
use std::sync::Arc;

#[path = "authorized_effect_admission_fixture.rs"]
mod fixture;
use fixture::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_admission_committed_cancel_takeover_or_step_change_prevents_provider_entry() {
    for competing in ["cancel", "takeover", "step"] {
        let fixture = Fixture::new();
        let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
        let competitor = AutomationStore::open(&fixture.layout)
            .await
            .expect("independent owner connection");
        // Clock call 1 is inside the original final-use claim, after the old
        // preliminary step read and before immutable SQLite attempt insertion.
        let mut gated = GatedAuthority::new(expected.clone(), competing, 1);
        let witness = fixture._temp.path().join("provider-effect");
        let driver = FileEffectDriver::new(witness.clone());
        let calls = Arc::clone(&driver.calls);
        let task = OwnedDispatch {
            store,
            authority: gated.authority.clone(),
            signed: gated.signed.clone(),
            effect: effect.clone(),
            fence: owner.clone(),
            binding: expected,
            driver,
        }
        .spawn(competing != "cancel", 30);
        gated.entered().await;
        let run = competitor
            .taskflow_run(&effect.run_id)
            .await
            .expect("read original run")
            .expect("run");
        match competing {
            "cancel" => {
                let command = TaskFlowCommand::new(
                    &effect.run_id,
                    "race-cancel-first",
                    owner.clone(),
                    run.revision,
                    TaskFlowTransition::Cancel {
                        reason: "no effect admitted yet".into(),
                    },
                    31,
                )
                .expect("cancel command");
                assert_eq!(
                    competitor
                        .apply_taskflow_command(&command)
                        .await
                        .expect("cancellation commits first")
                        .state,
                    TaskFlowRunState::Cancelled
                );
            }
            "takeover" => {
                let mut successor = owner.clone();
                successor.generation += 1;
                successor.fencing_token = "race-successor-fence".into();
                let next = competitor
                    .claim_taskflow_run(
                        &effect.run_id,
                        &successor,
                        run.lease_expires_at_ms.expect("original lease") + 1,
                        10_000,
                    )
                    .await
                    .expect("takeover commits first");
                assert_eq!(next.generation, Some(successor.generation));
            }
            "step" => {
                competitor
                    .record_taskflow_step(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                        &owner,
                        &effect.digest().expect("intent"),
                        &effect.payload_digest,
                        "race-step-observation",
                        &Sha256Digest::for_bytes(b"explicit other-owner observation"),
                        TaskFlowStepObservation::Indeterminate,
                        31,
                    )
                    .await
                    .expect("step change commits first");
            }
            _ => unreachable!("bounded fixture case"),
        }
        gated.release();
        let result = tokio::time::timeout(Duration::from_secs(3), task)
            .await
            .expect("dispatch resolves")
            .expect("dispatch task");
        assert!(result.is_err(), "stale admission must reject");
        assert_eq!(
            calls.load(Ordering::SeqCst),
            0,
            "an error after contact is insufficient"
        );
        assert!(!witness.exists(), "provider side effect must not occur");
        assert!(
            competitor
                .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
                .await
                .expect("original attempt lookup")
                .is_none()
        );
        assert_eq!(
            gated
                .authority
                .capacity()
                .expect("original nonce accounting")
                .used_nonces,
            1,
            "failed SQLite admission conservatively does not refund the original nonce"
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_admission_wins_before_cancel_and_preserves_original_uncertainty() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let competitor = AutomationStore::open(&fixture.layout)
        .await
        .expect("independent owner connection");
    // Claim calls the configured clock twice; call 3 is the original final
    // live-use check after the immutable attempt has committed, before driver entry.
    let mut gated = GatedAuthority::new(expected.clone(), "insert-first", 3);
    let witness = fixture._temp.path().join("provider-effect");
    let driver = FileEffectDriver::new(witness.clone());
    let calls = Arc::clone(&driver.calls);
    let task = OwnedDispatch {
        store,
        authority: gated.authority.clone(),
        signed: gated.signed.clone(),
        effect: effect.clone(),
        fence: owner.clone(),
        binding: expected,
        driver,
    }
    .spawn(true, 30);
    gated.entered().await;
    let pending = competitor
        .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
        .await
        .expect("original attempt")
        .expect("attempt committed before physical entry");
    assert_eq!(pending.grant_id, gated.signed.grant.grant_id);
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let run = competitor
        .taskflow_run(&effect.run_id)
        .await
        .expect("run")
        .expect("present");
    let command = TaskFlowCommand::new(
        &effect.run_id,
        "race-cancel-after-admission",
        owner.clone(),
        run.revision,
        TaskFlowTransition::Cancel {
            reason: "must not fabricate a stop ACK".into(),
        },
        31,
    )
    .expect("cancel command");
    assert!(competitor.apply_taskflow_command(&command).await.is_err());
    assert_eq!(
        competitor
            .taskflow_run(&effect.run_id)
            .await
            .expect("unchanged original run")
            .expect("run"),
        run
    );
    let mut successor = owner.clone();
    successor.generation += 1;
    successor.fencing_token = "forbidden-inflight-takeover".into();
    assert!(
        competitor
            .claim_taskflow_run(
                &effect.run_id,
                &successor,
                run.lease_expires_at_ms.expect("original lease") + 1,
                10_000
            )
            .await
            .is_err()
    );
    gated.release();
    let receipt = tokio::time::timeout(Duration::from_secs(3), task)
        .await
        .expect("physical dispatch completes")
        .expect("dispatch task")
        .expect("original indeterminate observation retained");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        std::fs::read(&witness).expect("actual provider effect"),
        EFFECT_PAYLOAD
    );
    let retained = competitor
        .taskflow_run(&effect.run_id)
        .await
        .expect("recoverable run")
        .expect("run");
    assert_eq!(retained.state, TaskFlowRunState::Indeterminate);
    assert_eq!(
        retained.fencing_token.as_deref(),
        Some(owner.fencing_token.as_str())
    );
    assert!(
        !retained.cancel_requested,
        "rejection does not invent a cancellation request or ACK"
    );

    // The same explicit provider fixture later supplies its terminal evidence;
    // original reconciliation remains possible without another physical effect.
    let recovered = competitor
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &owner,
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(
                    &std::fs::read(&witness).expect("provider-owned witness"),
                ),
            }),
            32,
        )
        .await
        .expect("original-key reconciliation");
    assert!(matches!(
        recovered,
        AuthorizedEffectRecoveryResult::Observed(_)
    ));
    assert_eq!(
        competitor
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("run")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn effect_admission_checks_original_caller_owned_lease_timestamp() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let (authority, signed, _directory) = final_use(expected.clone(), "declared-expiry");
    let witness = fixture._temp.path().join("provider-effect");
    let mut driver = FileEffectDriver::new(witness.clone());
    let expired = store
        .taskflow_run(&effect.run_id)
        .await
        .expect("run")
        .expect("run")
        .lease_expires_at_ms
        .expect("original lease");
    assert!(
        store
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &owner,
                &signed,
                &expected,
                "expired-admission",
                expired
            )
            .await
            .is_err()
    );
    assert_eq!(driver.calls.load(Ordering::SeqCst), 0);
    assert!(!witness.exists());
    assert!(
        store
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("no admitted attempt")
            .is_none()
    );
}
