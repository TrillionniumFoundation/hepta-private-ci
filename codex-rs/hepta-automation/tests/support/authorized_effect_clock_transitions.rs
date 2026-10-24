//! The original SQLite owner orders generic commands against effect admission.
#![allow(
    clippy::expect_used,
    reason = "two-connection owner transition fixture"
)]

use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::super::EFFECT_PAYLOAD;
use super::super::Fixture;
use super::super::binding;
use super::super::fence;
use super::super::intent;
use super::driver::FileDriver;
use super::driver::queued_store;
use super::driver::spawn_dispatch;
use super::fixture::Clock;
use super::fixture::Security;

fn ordinary_moves() -> Vec<TaskFlowTransition> {
    vec![
        TaskFlowTransition::Cancel {
            reason: "local cancellation is not provider evidence".into(),
        },
        TaskFlowTransition::Succeed {
            output_digest: Sha256Digest::for_bytes(b"caller-only success"),
        },
        TaskFlowTransition::Fail {
            reason: "caller-only failure".into(),
        },
        TaskFlowTransition::Wait {
            token: "caller-wait".into(),
            resume_node: None,
        },
        TaskFlowTransition::Retry { retry_at_ms: 1_001 },
    ]
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_admission_wins_before_generic_transition_or_step_receipt() {
    for asynchronous in [false, true] {
        let fixture = Fixture::new();
        let effect = intent();
        let store = queued_store(&fixture, &effect.run_id).await;
        let other = AutomationStore::open(&fixture.layout)
            .await
            .expect("second real DB connection");
        let clock = Clock::new(/*now*/ 1_000);
        let security = Security::new(
            binding(&effect),
            "admission-wins-state-race",
            clock.clone(),
            /*expiry*/ 5_000,
        );
        let authority = security.authority.clone();
        let witness = fixture._temp.path().join("one-effect");
        let driver = FileDriver::new(witness.clone());
        let calls = driver.calls.clone();
        let running = spawn_dispatch(
            store,
            security,
            effect.clone(),
            driver,
            /*lease_duration*/ 100,
            asynchronous,
        );
        running
            .ready
            .await
            .expect("original typed lease and claimed step");
        clock.block_on(/*call*/ 5);
        running.start.send(()).expect("start original effect");
        clock.entered().await; // Durable admission committed, driver not yet entered.
        assert!(
            other
                .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
                .await
                .expect("durable original attempt")
                .is_some()
        );
        let run = other
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present");
        for (index, transition) in ordinary_moves().into_iter().enumerate() {
            let command = TaskFlowCommand::new(
                &effect.run_id,
                format!("after-admission-{index}"),
                fence(),
                run.revision,
                transition,
                /*now_ms*/ 1_000,
            )
            .expect("ordinary owner command");
            assert!(other.apply_taskflow_command(&command).await.is_err());
            assert_eq!(
                other
                    .taskflow_run(&effect.run_id)
                    .await
                    .expect("unchanged")
                    .expect("run"),
                run
            );
        }
        for (index, observation) in [
            TaskFlowStepObservation::Succeeded,
            TaskFlowStepObservation::Failed,
            TaskFlowStepObservation::Indeterminate,
        ]
        .into_iter()
        .enumerate()
        {
            assert!(
                other
                    .record_taskflow_step(
                        &effect.run_id,
                        &effect.step_id,
                        effect.attempt,
                        &fence(),
                        &effect.digest().expect("intent"),
                        &effect.payload_digest,
                        &format!("unobserved-step-{index}"),
                        &Sha256Digest::for_bytes(b"no provider receipt"),
                        observation,
                        /*now_ms*/ 1_000
                    )
                    .await
                    .is_err()
            );
        }
        assert_eq!(
            other
                .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &fence())
                .await
                .expect("original step")
                .expect("claimed")
                .state,
            TaskFlowStepState::Claimed
        );
        // Quarantine is safe, but an arbitrary digest cannot terminalize it.
        let quarantine = TaskFlowCommand::new(
            &effect.run_id,
            "caller-quarantine",
            fence(),
            run.revision,
            TaskFlowTransition::Indeterminate {
                reason: "retain original uncertainty".into(),
            },
            /*now_ms*/ 1_000,
        )
        .expect("quarantine command");
        other
            .apply_taskflow_command(&quarantine)
            .await
            .expect("fence-preserving quarantine");
        let retained = other
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present");
        for (index, outcome) in [
            TaskFlowReconcileOutcome::Succeeded,
            TaskFlowReconcileOutcome::Failed,
            TaskFlowReconcileOutcome::Cancelled,
        ]
        .into_iter()
        .enumerate()
        {
            let command = TaskFlowCommand::new(
                &effect.run_id,
                format!("unverified-reconcile-{index}"),
                fence(),
                retained.revision,
                TaskFlowTransition::Reconcile {
                    receipt_digest: Sha256Digest::for_bytes(b"not original evidence"),
                    outcome,
                },
                /*now_ms*/ 1_000,
            )
            .expect("generic reconciliation");
            assert!(other.apply_taskflow_command(&command).await.is_err());
        }
        assert_eq!(
            other
                .taskflow_run(&effect.run_id)
                .await
                .expect("preserved fence")
                .expect("run"),
            retained
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        clock.release();
        let receipt = tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
            .await
            .expect("entry resolves")
            .expect("task")
            .expect("real receipt remains writable");
        assert_eq!(
            receipt.observation,
            Some(TaskFlowStepObservation::Indeterminate)
        );
        assert_eq!(
            std::fs::read(&witness).expect("actual effect"),
            EFFECT_PAYLOAD
        );
        assert!(
            other
                .reconcile_taskflow_step(
                    &effect.run_id,
                    &effect.step_id,
                    effect.attempt,
                    &fence(),
                    &effect.digest().expect("intent"),
                    &effect.payload_digest,
                    "unretained-terminal-step",
                    &Sha256Digest::for_bytes(b"caller-only terminal"),
                    TaskFlowReconcileOutcome::Succeeded,
                    /*now_ms*/ 1_000
                )
                .await
                .is_err()
        );
        other
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &fence(),
                AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Succeeded,
                    receipt_digest: Sha256Digest::for_bytes(
                        &std::fs::read(&witness).expect("original witness"),
                    ),
                }),
                /*observed_at_ms*/ 1_000,
            )
            .await
            .expect("original evidence-owned terminal path remains usable");
        assert_eq!(
            other
                .taskflow_run(&effect.run_id)
                .await
                .expect("settled")
                .expect("run")
                .state,
            TaskFlowRunState::Succeeded
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            authority
                .capacity()
                .expect("no replacement grant")
                .used_nonces,
            1
        );
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_generic_transition_wins_before_admission_without_provider_entry() {
    for (index, transition) in ordinary_moves().into_iter().enumerate() {
        let fixture = Fixture::new();
        let effect = intent();
        let store = queued_store(&fixture, &effect.run_id).await;
        let other = AutomationStore::open(&fixture.layout)
            .await
            .expect("second actual owner");
        let clock = Clock::new(/*now*/ 1_000);
        let security = Security::new(
            binding(&effect),
            "state-transition-wins",
            clock,
            /*expiry*/ 5_000,
        );
        let witness = fixture._temp.path().join("must-not-exist");
        let driver = FileDriver::new(witness.clone());
        let calls = driver.calls.clone();
        let running = spawn_dispatch(
            store,
            security,
            effect.clone(),
            driver,
            /*lease_duration*/ 100,
            /*asynchronous*/ true,
        );
        running.ready.await.expect("step ready, no admission");
        let run = other
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present");
        let command = TaskFlowCommand::new(
            &effect.run_id,
            format!("transition-first-{index}"),
            fence(),
            run.revision,
            transition,
            /*now_ms*/ 1_000,
        )
        .expect("command");
        other
            .apply_taskflow_command(&command)
            .await
            .expect("original transition commits first");
        running.start.send(()).expect("later effect request");
        assert!(
            tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
                .await
                .expect("bounded rejection")
                .expect("task")
                .is_err()
        );
        assert!(!witness.exists());
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert!(
            other
                .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
                .await
                .expect("no admitted effect")
                .is_none()
        );
    }
}
