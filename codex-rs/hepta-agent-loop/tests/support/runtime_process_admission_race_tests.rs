//! Exercise the original database's Cancel/admission transaction ordering.

use super::*;
use pretty_assertions::assert_eq;

struct InflightDriver(Process);

impl AsyncAuthorizedEffectDriver for InflightDriver {
    fn dispatch<'a>(
        &'a mut self,
        request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            let _ = self
                .0
                .dispatch(&request.provider_intent, request.wire_payload)
                .await;
            Ok(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Indeterminate,
                receipt_digest: Sha256Digest::for_bytes(
                    b"fixture contacted original process without terminal reply",
                ),
            })
        })
    }
}

#[tokio::test]
async fn persisted_original_cancel_blocks_an_already_prepared_dispatch() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    let mut effects = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process.clone(),
        prebound(&frame, &intent, &fence, &grant),
    );
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("original native owner");
    turn.commit(&frame, Transition::CancelRequested)
        .await
        .expect("persist cancel before contact");
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("original guarded cancellation"),
        StopObservation::Stopped
    );
    drop(turn);
    drop(effects);
    store.close().await;

    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen original cancel evidence");
    let mut driver = InflightDriver(process.clone());
    // Model an old caller that passed a native-frame check before cancellation.
    // The original admission transaction must still reject it before driver I/O.
    assert!(
        store
            .execute_authorized_taskflow_effect_async(
                &authority,
                &mut driver,
                &intent,
                call(&frame).arguments.as_bytes(),
                &fence,
                &grant,
                &intent.final_use_binding().expect("binding"),
                "fixture-process-dispatch",
                clock()
            )
            .await
            .is_err()
    );
    assert_eq!(process.0.lock().expect("lock").dispatches, 0);
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("original attempt")
            .is_none()
    );
    let mut replay = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process,
        prebound(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        replay
            .cancel(&frame.binding)
            .await
            .expect("durable cancellation replay"),
        StopObservation::Stopped
    );
}

// Each independently named case retains one fresh original database and the
// complete admission/cancel race. Eight separate 60-second watchdogs measure
// eight cases, rather than aggregating eight unrelated cold migrations.
async fn competing_original_admission_case(iteration: usize) {
    let started = std::time::Instant::now();
    phase_timing(
        &format!("admission_race.iteration_{iteration}.begin"),
        started,
    );
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native_with_tool(RUNTIME_PROCESS_TOOL_NAME).await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let process = Process::default();
    let mut effects = RuntimeProcessEffectOwner::new(
        &store,
        &authority,
        process.clone(),
        prebound(&frame, &intent, &fence, &grant),
    );
    let mut turn = TaskFlowTurnOwner::open(
        &store,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("original native owner");
    turn.commit(&frame, Transition::CancelRequested)
        .await
        .expect("persisted native stop intent");
    phase_timing("admission_race.cancel_intent_ready", started);
    let mut driver = InflightDriver(process.clone());
    let binding = intent.final_use_binding().expect("binding");
    // Both calls reach the original store. No test-side ledger or mock
    // transaction decides whether admission or cancellation wins.
    phase_timing("admission_race.join_begin", started);
    let (dispatch, stopped) = tokio::join!(
        store.execute_authorized_taskflow_effect_async(
            &authority,
            &mut driver,
            &intent,
            call(&frame).arguments.as_bytes(),
            &fence,
            &grant,
            &binding,
            "fixture-process-dispatch",
            clock()
        ),
        effects.cancel(&frame.binding),
    );
    phase_timing("admission_race.join_complete", started);
    let contacts = process.0.lock().expect("lock").dispatches;
    assert!(contacts <= 1);
    let stopped = stopped.expect("original cancellation read");
    if stopped == StopObservation::Stopped {
        assert_eq!(contacts, 0);
        assert!(dispatch.is_err());
        assert_eq!(
            store
                .taskflow_run(&intent.run_id)
                .await
                .expect("run")
                .expect("present")
                .state,
            TaskFlowRunState::Cancelled
        );
    } else if contacts == 1 {
        assert!(dispatch.is_ok());
        assert_eq!(
            store
                .taskflow_run(&intent.run_id)
                .await
                .expect("run")
                .expect("present")
                .state,
            TaskFlowRunState::Indeterminate
        );
        assert_eq!(
            effects
                .cancel(&frame.binding)
                .await
                .expect("no terminal witness"),
            StopObservation::Unresolved
        );
    } else {
        // SQLite may reject one writer during a snapshot race. Only a
        // subsequent successful original cancellation can prove no contact.
        assert_eq!(
            effects
                .cancel(&frame.binding)
                .await
                .expect("retry original cancellation"),
            StopObservation::Stopped
        );
    }
    phase_timing("admission_race.assertions_complete", started);
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_00() {
    competing_original_admission_case(0).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_01() {
    competing_original_admission_case(1).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_02() {
    competing_original_admission_case(2).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_03() {
    competing_original_admission_case(3).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_04() {
    competing_original_admission_case(4).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_05() {
    competing_original_admission_case(5).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_06() {
    competing_original_admission_case(6).await;
}

#[tokio::test]
async fn competing_original_admission_never_coexists_with_a_false_stop_case_07() {
    competing_original_admission_case(7).await;
}
