//! ACT-2 conformance on ACT-1's controlled durable destination, not a product
//! Notes qualification or an independent sample of learned policy performance.

use std::time::Duration;

use codex_hepta_automation::ActionExecutionStateV1;
use codex_hepta_automation::ActionGoalStateV1;
use codex_hepta_automation::ActionRuntimeStateV1;
use codex_hepta_automation::ActionSkillError;
use codex_hepta_automation::ActionTerminalOutcomeV1;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use pretty_assertions::assert_eq;

use super::baselines::oracle;
use super::destination::Destination;
use super::destination::Fault;
use super::destination::LookupAvailability;
use super::harness::Harness;
use super::harness::key;
use super::observer::driver;
use super::observer::wire;

#[tokio::test]
async fn act2_running_readback_is_read_only_then_observes_terminal_goal() {
    let temp = tempfile::tempdir().expect("case");
    let root = temp.path().canonicalize().expect("canonical case");
    let destination = Destination::open(&root, Fault::PauseBeforeCommit).await;
    let harness = Harness::create(&root, wire()).await;
    let mut dispatcher = driver(&root, destination.clone()).await;
    let reader = driver(&root, destination.clone()).await;
    let observation = async {
        tokio::time::timeout(Duration::from_secs(10), destination.reached.notified())
            .await
            .expect("live dispatch barrier");
        let pending = harness.pending().await;
        let before = harness.store.taskflow_run(&harness.effect.run_id).await.expect("run");
        let view = reader.observe_pending_state(&pending, &harness.wire).await.expect("view");
        assert_eq!(view.state, ActionRuntimeStateV1::Running);
        assert_eq!(view.provider_outcome, AuthorizedEffectOutcome::Indeterminate);
        assert_eq!(view.observation.execution, ActionExecutionStateV1::Running);
        assert_eq!(view.observation.goal, ActionGoalStateV1::Unsatisfied);
        assert_eq!(view.observation.binding.effect_intent_digest, pending.intent_digest);
        assert_eq!(harness.store.taskflow_run(&harness.effect.run_id).await.expect("run"), before);
        destination.release.notify_one();
        pending
    };
    let (sent, pending) = tokio::join!(harness.dispatch(&mut dispatcher), observation);
    sent.expect("one authorized effect");
    let view = reader.observe_pending_state(&pending, &harness.wire).await.expect("current goal");
    assert_eq!(view.state, ActionRuntimeStateV1::Terminal { outcome: ActionTerminalOutcomeV1::Succeeded });
    let truth = oracle(&root).await;
    assert!(truth.actual_business_success);
    assert_eq!(truth.dispatch_contacts, 1);
    assert_eq!(truth.duplicate_effects, 0);
}

#[tokio::test]
async fn act2_partial_effect_retains_simultaneous_real_input_wait() {
    let temp = tempfile::tempdir().expect("case");
    let root = temp.path().canonicalize().expect("canonical case");
    let destination = Destination::open(&root, Fault::WaitingInput).await;
    let harness = Harness::create(&root, wire()).await;
    let mut checked = driver(&root, destination.clone()).await;
    harness.dispatch(&mut checked).await.expect("waiting effect");
    crate::wait_for_file(&root.join("input-reader.ready")).await;
    assert!(destination.input_process_waits());
    let pending = harness.pending().await;
    assert_eq!(checked.observe_pending_state(&pending, &harness.wire).await.expect("wait").state,
        ActionRuntimeStateV1::WaitingInput);

    // A controlled destination subeffect occurs while the original reader is
    // still blocked. This is fixture setup, not a second authorized dispatch.
    sqlx::query("INSERT INTO business_events(effect_key, ordinal, value) VALUES (?, 0, 'invoice:42')")
        .bind(key().as_str()).execute(&destination.pool).await.expect("partial effect");
    let partial = checked.observe_pending_state(&pending, &harness.wire).await.expect("partial");
    assert_eq!(partial.state, ActionRuntimeStateV1::PartialEffect);
    assert_eq!(partial.observation.execution, ActionExecutionStateV1::WaitingForInput);
    assert_eq!(partial.observation.goal, ActionGoalStateV1::Partial);
    assert!(destination.input_process_waits());
    destination.provide_input();
    let complete = checked.observe_pending_state(&pending, &harness.wire).await.expect("complete");
    assert_eq!(complete.state, ActionRuntimeStateV1::Terminal { outcome: ActionTerminalOutcomeV1::Succeeded });
    assert_eq!(harness.pending().await, pending, "observing does not settle the owner");
    assert_eq!(harness.recover(checked.lookup(&pending, &harness.wire).await).await.expect("recover").final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded));
    let truth = oracle(&root).await;
    assert_eq!(truth.business_events, 2);
    assert_eq!(truth.dispatch_contacts, 1);
    assert_eq!(truth.duplicate_effects, 0);
}

#[tokio::test]
async fn act2_unknown_readback_preserves_effect_and_original_recovery_identity() {
    let temp = tempfile::tempdir().expect("case");
    let root = temp.path().canonicalize().expect("canonical case");
    let destination = Destination::open(&root, Fault::AckLost).await;
    let harness = Harness::create(&root, wire()).await;
    let mut checked = driver(&root, destination.clone()).await;
    harness.dispatch(&mut checked).await.expect("lost response");
    let pending = harness.pending().await;
    let unavailable = driver(&root, destination.clone().with_lookup(LookupAvailability::Unavailable)).await;
    let view = unavailable.observe_pending_state(&pending, &harness.wire).await.expect("goal readback");
    assert_eq!(view.state, ActionRuntimeStateV1::Unknown);
    assert_eq!(view.provider_outcome, AuthorizedEffectOutcome::Indeterminate);
    assert_eq!(view.observation.goal, ActionGoalStateV1::Satisfied);
    assert_eq!(view.observation.binding.effect_intent_digest, pending.intent_digest);
    let lookups = destination.contact_count("lookup").await;
    let mut different_wire = harness.wire.clone();
    different_wire.push(b' ');
    assert_eq!(checked.observe_pending_state(&pending, &different_wire).await, Err(ActionSkillError::Invocation));
    assert_eq!(destination.contact_count("lookup").await, lookups);
    assert!(harness.dispatch(&mut checked).await.is_err());
    assert_eq!(harness.pending().await, pending);
    assert_eq!(checked.observe_pending_state(&pending, &harness.wire).await.expect("restored lookup").state,
        ActionRuntimeStateV1::Terminal { outcome: ActionTerminalOutcomeV1::Succeeded });
    assert_eq!(destination.contact_count("dispatch").await, 1);
    assert_eq!(oracle(&root).await.duplicate_effects, 0);
}

#[tokio::test]
async fn act2_zero_exit_and_rejected_partial_effect_are_not_terminal_success() {
    for (fault, expected) in [
        (Fault::ExitZero, ActionRuntimeStateV1::Unknown),
        (Fault::RejectedPartial, ActionRuntimeStateV1::PartialEffect),
    ] {
        let temp = tempfile::tempdir().expect("case");
        let root = temp.path().canonicalize().expect("canonical case");
        let destination = Destination::open(&root, fault).await;
        let harness = Harness::create(&root, wire()).await;
        let mut checked = driver(&root, destination.clone()).await;
        harness.dispatch(&mut checked).await.expect("one effect");
        let pending = harness.pending().await;
        let view = checked.observe_pending_state(&pending, &harness.wire).await.expect("current facts");
        assert_eq!(view.state, expected);
        assert_eq!(view.observation.execution, ActionExecutionStateV1::Returned { exit_code: Some(0) });
        assert!(view.observation.absence_proof_digest.is_none());
        assert_eq!(harness.pending().await, pending);
        assert_eq!(destination.contact_count("dispatch").await, 1);
    }
}

#[tokio::test]
async fn act2_failed_terminal_requires_retained_destination_tombstone() {
    let temp = tempfile::tempdir().expect("case");
    let root = temp.path().canonicalize().expect("canonical case");
    let destination = Destination::open(&root, Fault::RejectBeforeStart).await;
    let harness = Harness::create(&root, wire()).await;
    let mut checked = driver(&root, destination.clone()).await;
    let at_tombstone = async {
        tokio::time::timeout(Duration::from_secs(10), destination.reached.notified())
            .await.expect("tombstone barrier");
        let pending = harness.pending().await;
        destination.release.notify_one();
        pending
    };
    let (sent, pending) = tokio::join!(harness.dispatch(&mut checked), at_tombstone);
    sent.expect("proven failure");
    let view = checked.observe_pending_state(&pending, &harness.wire).await.expect("tombstone view");
    assert_eq!(view.state, ActionRuntimeStateV1::Terminal { outcome: ActionTerminalOutcomeV1::Failed });
    let digest = view.observation.absence_proof_digest.expect("retained exclusion proof");
    assert!(root.join("observations").join(format!("{}.json", digest.as_str())).exists());
    destination.finish(&key()).await;
    let truth = oracle(&root).await;
    assert_eq!(truth.business_events, 0);
    assert_eq!(truth.dispatch_contacts, 1);
}
