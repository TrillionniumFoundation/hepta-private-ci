//! ACT-1: real destination effects through the authorized TaskFlow driver.
//!
//! Fault plans are private to the destination. Assertions use a separate
//! connection to the business ledger, never the provider's success field.
#![cfg(unix)]
#![allow(
    clippy::expect_used,
    reason = "fault qualification fixtures fail loudly"
)]

mod action_skill_support;

use std::io::BufRead;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_automation::ActionCancellationStateV1;
use codex_hepta_automation::ActionExecutionStateV1;
use codex_hepta_automation::ActionGoalStateV1;
use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::GoalCheckedActionSkillDriver;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;

use action_skill_support::KEY_ENV;
use action_skill_support::ROOT_ENV;
use action_skill_support::baselines::BASELINES;
use action_skill_support::baselines::Baseline;
use action_skill_support::baselines::metric;
use action_skill_support::baselines::oracle;
use action_skill_support::destination::Destination;
use action_skill_support::destination::Fault;
use action_skill_support::destination::LookupAvailability;
use action_skill_support::destination::facts;
use action_skill_support::harness::Harness;
use action_skill_support::harness::key;
use action_skill_support::observer::Observer;
use action_skill_support::observer::contract;
use action_skill_support::observer::driver;
use action_skill_support::observer::wire;

#[tokio::test]
async fn act1_shared_fault_matrix_preserves_truth_durable_workflow() {
    assert_shared_fault_matrix_preserves_truth(Baseline::DurableWorkflow).await;
}

#[tokio::test]
async fn act1_shared_fault_matrix_preserves_truth_handwritten_dsl() {
    assert_shared_fault_matrix_preserves_truth(Baseline::HandwrittenDsl).await;
}

#[tokio::test]
async fn act1_shared_fault_matrix_preserves_truth_flat_skills() {
    assert_shared_fault_matrix_preserves_truth(Baseline::FlatSkills).await;
}

async fn assert_shared_fault_matrix_preserves_truth(baseline: Baseline) {
    let cases = [
        (
            "no_fault",
            Fault::None,
            LookupAvailability::Available,
            2,
            true,
        ),
        (
            "committed_ack_lost",
            Fault::AckLost,
            LookupAvailability::Available,
            2,
            true,
        ),
        (
            "waiting_for_input",
            Fault::WaitingInput,
            LookupAvailability::Available,
            0,
            false,
        ),
        (
            "partial_success",
            Fault::Partial,
            LookupAvailability::Available,
            1,
            false,
        ),
        (
            "rejected_after_partial_effect",
            Fault::RejectedPartial,
            LookupAvailability::Available,
            1,
            false,
        ),
        (
            "cancel_before_commit",
            Fault::PauseBeforeCommit,
            LookupAvailability::Available,
            0,
            false,
        ),
        (
            "commit_before_cancel",
            Fault::PauseAfterCommit,
            LookupAvailability::Available,
            2,
            true,
        ),
        (
            "exit_zero_without_effect",
            Fault::ExitZero,
            LookupAvailability::Available,
            0,
            false,
        ),
        (
            "lookup_unavailable",
            Fault::AckLost,
            LookupAvailability::Unavailable,
            2,
            false,
        ),
    ];
    for (scenario, fault, availability, events, expected_success) in cases {
        let temp = tempfile::tempdir().expect("isolated case");
        let root = temp.path().canonicalize().expect("canonical case root");
        let destination = Destination::open(&root, fault)
            .await
            .with_lookup(availability);
        let harness = Harness::create(&root, wire()).await;
        let mut driver = driver(&root, destination.clone()).await;
        let outcome = if matches!(fault, Fault::PauseBeforeCommit | Fault::PauseAfterCommit) {
            let controller = async {
                tokio::time::timeout(Duration::from_secs(10), destination.reached.notified())
                    .await
                    .expect("destination reached the explicit race barrier");
                destination.cancel(&key()).await;
                destination.release.notify_one();
            };
            let (outcome, ()) = tokio::join!(baseline.run(&harness, &mut driver), controller);
            outcome
        } else {
            baseline.run(&harness, &mut driver).await
        };
        let truth = oracle(&root).await;
        assert_eq!(truth.business_events, events, "{baseline:?} {scenario}");
        assert_eq!(
            outcome.reported_success, expected_success,
            "{baseline:?} {scenario}"
        );
        if matches!(fault, Fault::WaitingInput) {
            wait_for_file(&root.join("input-reader.ready")).await;
            assert!(destination.input_process_waits());
        }
        if matches!(fault, Fault::PauseBeforeCommit | Fault::PauseAfterCommit) {
            assert!(
                facts(&destination.pool, &key())
                    .await
                    .expect("cancel facts")
                    .cancel_received
            );
        }
        if matches!(fault, Fault::ExitZero) {
            assert_eq!(
                facts(&destination.pool, &key())
                    .await
                    .expect("process facts")
                    .exit_code,
                Some(0)
            );
        }
        metric(baseline, scenario, &outcome, &truth);
        harness.store.close().await;
    }
}

#[tokio::test]
async fn act1_real_input_reader_resumes_original_job_then_verifies_goal() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::WaitingInput).await;
    let harness = Harness::create(&root, wire()).await;
    let mut driver = driver(&root, destination.clone()).await;
    let first = harness.dispatch(&mut driver).await.expect("admission");
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    wait_for_file(&root.join("input-reader.ready")).await;
    assert!(
        destination.input_process_waits(),
        "input-waiting process has not returned"
    );
    assert_eq!(oracle(&root).await.business_events, 0);
    let pending = harness.pending().await;
    let feedback = driver
        .observe_pending(&pending, &harness.wire)
        .await
        .expect("input feedback");
    assert_eq!(
        feedback.binding.provider_intent,
        ProviderEffectIntent::new(key(), harness.effect.payload_digest.clone())
    );
    assert_eq!(
        feedback.binding.effect_intent_digest,
        harness.effect.digest().expect("original effect identity")
    );
    assert_eq!(feedback.execution, ActionExecutionStateV1::WaitingForInput);
    assert_eq!(feedback.goal, ActionGoalStateV1::Unsatisfied);
    assert!(feedback.absence_proof_digest.is_none());

    destination.provide_input();
    let recovered = harness
        .recover(driver.lookup(&pending, &harness.wire).await)
        .await
        .expect("verified goal after explicit input");
    assert_eq!(
        recovered.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    let truth = oracle(&root).await;
    assert!(truth.actual_business_success);
    assert_eq!(
        truth.dispatch_contacts, 1,
        "input resumes the same destination job"
    );
    assert_eq!(truth.duplicate_effects, 0);
}

#[tokio::test]
async fn act1_partial_completion_recovers_only_after_missing_subeffect_exists() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::Partial).await;
    let harness = Harness::create(&root, wire()).await;
    let mut driver = driver(&root, destination.clone()).await;
    let first = harness
        .dispatch(&mut driver)
        .await
        .expect("partial job returned");
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let pending = harness.pending().await;
    let feedback = driver
        .observe_pending(&pending, &harness.wire)
        .await
        .expect("partial feedback");
    assert_eq!(
        feedback.binding.provider_intent,
        ProviderEffectIntent::new(key(), harness.effect.payload_digest.clone())
    );
    assert_eq!(
        feedback.binding.effect_intent_digest,
        harness.effect.digest().expect("original effect identity")
    );
    assert_eq!(
        feedback.execution,
        ActionExecutionStateV1::Returned { exit_code: Some(0) }
    );
    assert_eq!(feedback.goal, ActionGoalStateV1::Partial);
    assert!(feedback.absence_proof_digest.is_none());
    assert_eq!(oracle(&root).await.business_events, 1);
    destination.finish(&key()).await;
    let recovered = harness
        .recover(driver.lookup(&pending, &harness.wire).await)
        .await
        .expect("all requested effects now observed");
    assert_eq!(
        recovered.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    let truth = oracle(&root).await;
    assert!(truth.actual_business_success);
    assert_eq!(truth.business_events, 2);
    assert_eq!(
        truth.duplicate_effects, 0,
        "repair never repeats the first subeffect"
    );
    assert_eq!(truth.dispatch_contacts, 1);
}

#[tokio::test]
async fn act1_cancellation_feedback_retains_both_commit_orders() {
    for (fault, expected_goal, expected_cancel) in [
        (
            Fault::PauseBeforeCommit,
            ActionGoalStateV1::Unsatisfied,
            ActionCancellationStateV1::Confirmed,
        ),
        (
            Fault::PauseAfterCommit,
            ActionGoalStateV1::Satisfied,
            ActionCancellationStateV1::Requested,
        ),
    ] {
        let temp = tempfile::tempdir().expect("race root");
        let root = temp.path().canonicalize().expect("canonical root");
        let destination = Destination::open(&root, fault).await;
        let harness = Harness::create(&root, wire()).await;
        let mut driver = driver(&root, destination.clone()).await;
        let controller = async {
            tokio::time::timeout(Duration::from_secs(10), destination.reached.notified())
                .await
                .expect("race barrier");
            let pending = harness.pending().await;
            destination.cancel(&key()).await;
            destination.release.notify_one();
            pending
        };
        let (receipt, pending) = tokio::join!(harness.dispatch(&mut driver), controller);
        receipt.expect("race settles as observed");
        let feedback = driver
            .observe_pending(&pending, &harness.wire)
            .await
            .expect("cancel feedback");
        assert_eq!(
            feedback.binding.provider_intent,
            ProviderEffectIntent::new(key(), harness.effect.payload_digest.clone())
        );
        assert_eq!(
            feedback.binding.effect_intent_digest,
            harness.effect.digest().expect("original effect identity")
        );
        assert_eq!(feedback.goal, expected_goal);
        assert_eq!(feedback.cancellation, expected_cancel);
        assert!(
            feedback.absence_proof_digest.is_none(),
            "cancel ACK alone grants no absence proof"
        );
        assert_eq!(oracle(&root).await.dispatch_contacts, 1);
    }
}

#[tokio::test]
async fn act1_unknown_without_lookup_survives_reopen_without_resending() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::AckLost).await;
    let harness = Harness::create(&root, wire()).await;
    let mut original = driver(&root, destination.clone()).await;
    let first = harness
        .dispatch(&mut original)
        .await
        .expect("lost acknowledgement");
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    harness.store.close().await;
    // Closing SQLite does not release FinalUse's exclusive authority lock.
    drop(harness);
    drop(original);
    let reopened = Harness::reopen(&root, wire()).await;
    let mut unavailable = driver(
        &root,
        destination
            .clone()
            .with_lookup(LookupAvailability::Unavailable),
    )
    .await;
    let pending = reopened.pending().await;
    for _ in 0..2 {
        assert!(matches!(
            unavailable.lookup(&pending, &reopened.wire).await,
            AuthorizedProviderEffectLookup::Unresolved
        ));
    }
    assert!(reopened.dispatch(&mut unavailable).await.is_err());
    let truth = oracle(&root).await;
    assert!(
        truth.actual_business_success,
        "truth is known only to the independent test oracle"
    );
    assert_eq!(truth.dispatch_contacts, 1);
    assert_eq!(truth.duplicate_effects, 0);
}

#[tokio::test]
async fn act1_payload_and_contract_drift_are_rejected_before_destination_contact() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::AckLost).await;
    let harness = Harness::create(&root, wire()).await;
    let mut driver = driver(&root, destination.clone()).await;
    let mut drifted = harness.wire.clone();
    drifted.push(b' ');
    assert!(matches!(
        harness.dispatch_bytes(&mut driver, &drifted).await,
        Err(AuthorizedEffectError::BindingMismatch)
    ));
    assert_eq!(destination.contact_count("dispatch").await, 0);
    let first = harness
        .dispatch(&mut driver)
        .await
        .expect("same grant still usable for original bytes");
    assert_eq!(
        first.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let pending = harness.pending().await;
    assert!(matches!(
        driver.lookup(&pending, &drifted).await,
        AuthorizedProviderEffectLookup::Unresolved
    ));
    let mut changed = contract();
    changed.version += 1;
    let changed_driver = GoalCheckedActionSkillDriver::new(
        changed,
        destination.clone(),
        Observer::open(&root).await,
    )
    .expect("individually valid changed contract");
    assert!(matches!(
        changed_driver.lookup(&pending, &harness.wire).await,
        AuthorizedProviderEffectLookup::Unresolved
    ));
    assert_eq!(destination.contact_count("lookup").await, 0);
    assert_eq!(destination.contact_count("dispatch").await, 1);
    assert!(
        harness
            .recover(driver.lookup(&pending, &harness.wire).await)
            .await
            .is_some()
    );
}

#[tokio::test]
async fn act1_unsupported_destination_is_rejected_before_any_business_effect() {
    let temp = tempfile::tempdir().expect("root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::None)
        .await
        .with_lookup(LookupAvailability::Unsupported);
    let harness = Harness::create(&root, wire()).await;
    let mut driver = driver(&root, destination).await;
    assert!(harness.dispatch(&mut driver).await.is_err());
    let truth = oracle(&root).await;
    assert_eq!(truth.dispatch_contacts, 0);
    assert_eq!(truth.business_events, 0);
}

#[tokio::test]
async fn act1_durable_rejection_proves_failure_and_fences_late_effects() {
    let temp = tempfile::tempdir().expect("rejection root");
    let root = temp.path().canonicalize().expect("canonical root");
    let destination = Destination::open(&root, Fault::RejectBeforeStart).await;
    let harness = Harness::create(&root, wire()).await;
    let mut checked = driver(&root, destination.clone()).await;
    let controller = async {
        tokio::time::timeout(Duration::from_secs(10), destination.reached.notified())
            .await
            .expect("durable tombstone before provider reply");
        let pending = harness.pending().await;
        destination.release.notify_one();
        pending
    };
    let (receipt, pending) = tokio::join!(harness.dispatch(&mut checked), controller);
    assert_eq!(
        receipt.expect("proven rejection").observation,
        Some(TaskFlowStepObservation::Failed)
    );
    assert_eq!(
        harness
            .store
            .taskflow_run(&harness.effect.run_id)
            .await
            .expect("read run")
            .expect("run exists")
            .state,
        TaskFlowRunState::Failed
    );
    let feedback = checked
        .observe_pending(&pending, &harness.wire)
        .await
        .expect("rejection proof");
    assert_eq!(
        feedback.binding.provider_intent,
        ProviderEffectIntent::new(key(), harness.effect.payload_digest.clone())
    );
    assert_eq!(feedback.goal, ActionGoalStateV1::Unsatisfied);
    let proof = feedback
        .absence_proof_digest
        .expect("independent late-commit exclusion proof");
    assert!(
        root.join("observations")
            .join(format!("{}.json", proof.as_str()))
            .exists()
    );
    harness.store.close().await;
    drop(harness);
    drop(checked);
    destination.pool.close().await;

    let reopened_target = Destination::open(&root, Fault::None).await;
    let reopened = Harness::reopen(&root, wire()).await;
    let mut recovered_driver = driver(&root, reopened_target.clone()).await;
    // A late target worker and an owner replay both preserve the tombstone.
    reopened_target.finish(&key()).await;
    assert!(reopened.dispatch(&mut recovered_driver).await.is_err());
    let durable = facts(&reopened_target.pool, &key())
        .await
        .expect("durable rejection row");
    assert_eq!(durable.phase, "rejected_tombstone");
    assert_eq!(durable.payload, reopened.effect.payload_digest.as_str());
    let after = recovered_driver
        .observe_pending(&pending, &reopened.wire)
        .await
        .expect("reopened proof");
    assert_eq!(after.absence_proof_digest, Some(proof));
    let truth = oracle(&root).await;
    assert_eq!(truth.business_events, 0);
    assert_eq!(truth.dispatch_contacts, 1);
    assert_eq!(truth.duplicate_effects, 0);
}

#[tokio::test]
async fn act1_sigkill_after_commit_reopens_and_reconciles_all_baselines() {
    for baseline in BASELINES {
        let temp = tempfile::tempdir().expect("crash root");
        let root = temp.path().canonicalize().expect("canonical root");
        let mut child = Command::new(std::env::current_exe().expect("test executable"))
            .args([
                "--ignored",
                "--exact",
                "action_skill_crash_worker",
                "--nocapture",
            ])
            .env(ROOT_ENV, &root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .spawn()
            .expect("spawn fresh execution owner");
        let deadline = Instant::now() + Duration::from_secs(30);
        while !root.join("destination.committed").exists() {
            if let Some(status) = child.try_wait().expect("observe owner process") {
                panic!("owner exited before committed kill barrier: {status}");
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("owner did not reach committed kill barrier");
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        // Unix Child::kill sends SIGKILL. No graceful close or Rust destructors.
        child
            .kill()
            .expect("kill owner after real destination commit");
        assert!(!child.wait().expect("wait killed owner").success());
        let destination = Destination::open(&root, Fault::None).await;
        let reopened = Harness::reopen(&root, wire()).await;
        let mut driver = driver(&root, destination).await;
        assert!(matches!(
            reopened.dispatch(&mut driver).await,
            Err(AuthorizedEffectError::RecoveryRequired)
        ));
        let original = reopened.pending().await;
        assert_eq!(
            original.intent_digest,
            reopened.effect.digest().expect("original intent")
        );
        assert_eq!(original.payload_digest, reopened.effect.payload_digest);
        let outcome = baseline.resume(&reopened, &mut driver).await;
        let truth = oracle(&root).await;
        assert!(outcome.reported_success);
        assert!(truth.actual_business_success);
        metric(baseline, "sigkill_after_commit", &outcome, &truth);
    }
}

async fn wait_for_file(path: &Path) {
    tokio::time::timeout(Duration::from_secs(10), async {
        while !path.exists() {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("child process reached input-read boundary");
}

#[test]
#[ignore = "only parent ACT-1 tests launch the real input-reading process"]
fn action_skill_input_worker() {
    let root = std::env::var_os(ROOT_ENV).expect("parent root");
    let root = Path::new(&root);
    let key = ProviderEffectKey::parse(std::env::var(KEY_ENV).expect("original operation key"))
        .expect("valid provider key");
    std::fs::write(root.join("input-reader.ready"), b"stdin reader attached")
        .expect("reader barrier");
    let mut line = String::new();
    std::io::stdin()
        .lock()
        .read_line(&mut line)
        .expect("wait for explicit stdin");
    assert_eq!(line, "continue\n");
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    runtime.block_on(async {
        Destination::open(root, Fault::None)
            .await
            .finish(&key)
            .await;
    });
}

#[test]
#[ignore = "only parent ACT-1 tests SIGKILL this process after committed mutation"]
fn action_skill_crash_worker() {
    let root = std::env::var_os(ROOT_ENV).expect("parent root");
    let root = Path::new(&root);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    runtime.block_on(async {
        let destination = Destination::open(root, Fault::CrashAfterCommit).await;
        let harness = Harness::create(root, wire()).await;
        let mut driver = driver(root, destination).await;
        let _ = harness.dispatch(&mut driver).await;
        panic!("parent must kill owner before dispatch can return");
    });
}
