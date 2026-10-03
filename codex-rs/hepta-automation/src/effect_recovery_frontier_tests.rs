use super::EffectDispatchObservationKind;
use super::tests::prepared_store;
use crate::AutomationStore;
use crate::TaskFlowRunState;
use crate::TaskFlowStepObservation;
use codex_hepta_contracts::Sha256Digest;

#[derive(Clone, Copy, Debug)]
enum ObservationOrigin {
    Primary,
    Reconciliation,
}

#[derive(Clone, Copy, Debug)]
enum ProjectionCut {
    BeforeStep,
    BeforeRun,
}

#[tokio::test]
async fn terminal_primary_observation_remains_discoverable_until_settlement() {
    assert_terminal_frontier(ObservationOrigin::Primary, ProjectionCut::BeforeStep).await;
}

#[tokio::test]
async fn terminal_reconciliation_remains_discoverable_until_settlement() {
    assert_terminal_frontier(ObservationOrigin::Reconciliation, ProjectionCut::BeforeStep).await;
}

#[tokio::test]
async fn terminal_primary_projection_remains_discoverable_after_step_before_run() {
    assert_terminal_frontier(ObservationOrigin::Primary, ProjectionCut::BeforeRun).await;
}

#[tokio::test]
async fn terminal_reconciliation_projection_remains_discoverable_after_step_before_run() {
    assert_terminal_frontier(ObservationOrigin::Reconciliation, ProjectionCut::BeforeRun).await;
}

async fn assert_terminal_frontier(origin: ObservationOrigin, cut: ProjectionCut) {
    let mut missing = Vec::new();
    for kind in [
        EffectDispatchObservationKind::Succeeded,
        EffectDispatchObservationKind::Failed,
        EffectDispatchObservationKind::ProvenAbsent,
    ] {
        let (_temp, layout, store, fence) = prepared_store().await;
        let intent = Sha256Digest::for_bytes(b"effect-intent");
        let payload = Sha256Digest::for_bytes(b"effect-payload");
        let binding = Sha256Digest::for_bytes(b"frontier-binding");
        let nonce = Sha256Digest::for_bytes(b"frontier-nonce");
        store
            .begin_effect_dispatch_attempt(
                "effect-run",
                "work",
                /*attempt*/ 1,
                &intent,
                &payload,
                &binding,
                "provider:test",
                /*authority_epoch*/ 7,
                "frontier-grant",
                &nonce,
                "frontier-record",
                || Ok(21),
                &fence,
                /*provider_contract_binding*/ None,
            )
            .await
            .expect("durable attempt");
        if matches!(origin, ObservationOrigin::Reconciliation) {
            store
                .record_effect_dispatch_observation(
                    "effect-run",
                    "work",
                    /*attempt*/ 1,
                    EffectDispatchObservationKind::Indeterminate,
                    &Sha256Digest::for_bytes(b"frontier-unknown"),
                    /*observed_at_ms*/ 22,
                    /*provider*/ None,
                )
                .await
                .expect("initial unknown");
        }
        let terminal = Sha256Digest::for_bytes(kind.as_str().as_bytes());
        store
            .record_effect_dispatch_observation(
                "effect-run",
                "work",
                /*attempt*/ 1,
                kind,
                &terminal,
                /*observed_at_ms*/ 23,
                /*provider*/ None,
            )
            .await
            .expect("terminal fact before projection crash");
        if matches!(cut, ProjectionCut::BeforeRun) {
            match kind {
                EffectDispatchObservationKind::Succeeded
                | EffectDispatchObservationKind::Failed => {
                    let observation = match kind {
                        EffectDispatchObservationKind::Succeeded => {
                            TaskFlowStepObservation::Succeeded
                        }
                        EffectDispatchObservationKind::Failed => TaskFlowStepObservation::Failed,
                        EffectDispatchObservationKind::ProvenAbsent
                        | EffectDispatchObservationKind::Indeterminate => unreachable!(),
                    };
                    store
                        .record_taskflow_step(
                            "effect-run",
                            "work",
                            /*attempt*/ 1,
                            &fence,
                            &intent,
                            &payload,
                            "frontier-record",
                            &terminal,
                            observation,
                            /*now_ms*/ 23,
                        )
                        .await
                        .expect("step projection before run crash");
                }
                EffectDispatchObservationKind::ProvenAbsent => {
                    store
                        .cancel_taskflow_step_after_proven_absence(
                            "effect-run",
                            "work",
                            /*attempt*/ 1,
                            &fence,
                            &intent,
                            &payload,
                            "automation:step:provider-absent:frontier",
                            &terminal,
                            /*now_ms*/ 23,
                        )
                        .await
                        .expect("absence step projection before requeue crash");
                }
                EffectDispatchObservationKind::Indeterminate => unreachable!(),
            }
        }
        assert_eq!(
            store
                .taskflow_run("effect-run")
                .await
                .expect("run read")
                .expect("run")
                .state,
            TaskFlowRunState::Running,
            "the crash must precede run projection"
        );
        let expected = store
            .authorized_taskflow_effect_attempt("effect-run", "work", /*attempt*/ 1)
            .await
            .expect("attempt read")
            .expect("durable attempt remains");
        store.close().await;
        let reopened = AutomationStore::open(&layout).await.expect("restart");
        let pending = reopened
            .pending_authorized_taskflow_effects(/*limit*/ 10)
            .await
            .expect("restart recovery frontier");
        if pending != vec![expected] {
            missing.push(kind);
        }
        reopened
            .settle_authorized_taskflow_effect_observation("effect-run", "work", 1, &fence)
            .await
            .expect("local settlement");
        reopened
            .settle_authorized_taskflow_effect_observation("effect-run", "work", 1, &fence)
            .await
            .expect("idempotent local settlement");
        assert!(
            reopened
                .pending_authorized_taskflow_effects(/*limit*/ 10)
                .await
                .expect("settled frontier")
                .is_empty()
        );
        reopened.close().await;
    }
    assert!(
        missing.is_empty(),
        "lost terminal {origin:?} at {cut:?}: {missing:?}"
    );
}
