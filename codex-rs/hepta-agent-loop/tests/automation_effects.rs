#![cfg(all(unix, feature = "automation-effects", feature = "taskflow-owner"))]
#![allow(
    clippy::expect_used,
    reason = "isolated original-owner and explicit issuer fixtures fail loudly"
)]

use codex_hepta_agent_loop::*;
use codex_hepta_automation::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;

#[path = "support/automation_effect_fixture.rs"]
mod fixture;
#[path = "support/automation_effect_provider.rs"]
mod provider;
use fixture::*;
use provider::*;

fn driver(
    intent: &AuthorizedEffectIntent,
    provider: &FileProvider,
) -> ProviderEffectTaskFlowDriver<FileProvider> {
    ProviderEffectTaskFlowDriver::new(intent.destination_id.clone(), provider.clone())
        .expect("original provider driver")
}

#[tokio::test]
async fn status_effect_uses_original_owners_and_terminal_replay_contacts_provider_once() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    let observed = effects
        .execute_or_observe(&frame.binding, key, call(&frame))
        .await
        .expect("original authorized dispatch");
    let EffectObservation::Completed(status) = &observed else {
        panic!("original terminal status");
    };
    let value: serde_json::Value = serde_json::from_str(status).expect("status projection");
    assert_eq!(value["status"], "succeeded");
    assert_eq!(value["native_operation_key"], key.to_string());
    assert_eq!(value["effect_run_id"], intent.run_id);
    assert!(value.get("fencing_token").is_none());
    assert!(!status.contains(&fence.fencing_token));
    assert_eq!(provider.payload(), call(&frame).arguments.as_bytes());
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("effect run")
            .expect("present")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert_eq!(
        store
            .taskflow_run(NATIVE_RUN)
            .await
            .expect("native run")
            .expect("present")
            .state,
        TaskFlowRunState::Running
    );

    // The actual native cursor can commit this tool status and prepare a new
    // frame because original effect settlement ended only the admitted effect run.
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("same original native owner");
    let next = turn
        .commit(
            &frame,
            Transition::ToolCompleted {
                operation_key: key,
                output: status.clone(),
            },
        )
        .await
        .expect("actual runner-key validation and atomic status continuation");
    assert!(matches!(next.phase, Phase::Model(_)));
    drop(turn);
    drop(effects);
    store.close().await;

    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen original database");
    let mut replay = AutomationStatusEffectOwner::new(
        &reopened,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        replay
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("terminal replay"),
        observed
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn changed_native_identity_selection_payload_and_output_tool_are_refused() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    let mut changed_call = call(&frame).clone();
    changed_call.arguments.push(' ');
    assert!(
        effects
            .execute_or_observe(&frame.binding, key, &changed_call)
            .await
            .is_err()
    );
    assert!(
        effects
            .execute_or_observe(
                &frame.binding,
                Digest32::of_bytes(b"other key"),
                call(&frame)
            )
            .await
            .is_err()
    );
    let mut changed_binding = frame.binding.clone();
    changed_binding.turn_id = id("different-turn");
    assert!(
        effects
            .execute_or_observe(&changed_binding, key, call(&frame))
            .await
            .is_err()
    );
    changed_binding = frame.binding.clone();
    changed_binding.generation = Generation::new(2).expect("next generation");
    assert!(
        effects
            .execute_or_observe(&changed_binding, key, call(&frame))
            .await
            .is_err()
    );

    let mut changed = frame.clone();
    let Phase::Tools { calls, next } = &mut changed.phase else {
        unreachable!();
    };
    let mut other = calls[0].clone();
    other.call_id = id("different-selected-call");
    calls.push(other);
    *next = 1;
    assert_ne!(
        automation_status_effect_run_id(&changed).expect("other selected mapping"),
        intent.run_id
    );
    assert!(
        PreboundAutomationStatusEffect::new(
            &changed,
            intent.clone(),
            call(&changed).arguments.as_bytes().to_vec(),
            fence.clone(),
            grant.clone(),
            "fixture-effect-dispatch".into()
        )
        .is_err()
    );
    for changed in [
        Frame {
            revision: frame.revision + 1,
            ..frame.clone()
        },
        Frame {
            binding: TurnBinding {
                deadline_unix_ms: frame.binding.deadline_unix_ms + 1,
                ..frame.binding.clone()
            },
            ..frame.clone()
        },
    ] {
        assert_ne!(
            automation_status_effect_run_id(&changed).expect("changed frame mapping"),
            intent.run_id
        );
    }
    let mut changed = frame.clone();
    let Phase::Tools { calls, .. } = &mut changed.phase else {
        unreachable!();
    };
    calls[0].name = id("arbitrary.output.tool");
    assert!(automation_status_effect_run_id(&changed).is_err());
    let mut changed_intent = intent.clone();
    changed_intent.run_id = NATIVE_RUN.into();
    assert!(
        PreboundAutomationStatusEffect::new(
            &frame,
            changed_intent,
            call(&frame).arguments.as_bytes().to_vec(),
            fence.clone(),
            grant.clone(),
            "fixture-effect-dispatch".into()
        )
        .is_err()
    );
    assert!(
        PreboundAutomationStatusEffect::new(
            &frame,
            intent.clone(),
            b"different full bytes".to_vec(),
            fence,
            grant,
            "fixture-effect-dispatch".into()
        )
        .is_err()
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 0);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("original attempt read")
            .is_none()
    );
}

#[path = "support/automation_effect_recovery_tests.rs"]
mod recovery_tests;

#[path = "support/automation_effect_cancel_reopen_tests.rs"]
mod cancel_reopen_tests;

#[path = "support/automation_effect_concurrency_tests.rs"]
mod concurrency_tests;

#[path = "support/automation_effect_late_ack_tests.rs"]
mod late_ack_tests;
