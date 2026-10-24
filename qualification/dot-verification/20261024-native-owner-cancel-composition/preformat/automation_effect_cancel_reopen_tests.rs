//! Real TaskFlow cursor cancellation across adapter reconstruction, not a remote ACK.
use super::*;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

#[derive(Default)]
struct CancelOnlyInference {
    cancellations: usize,
}

impl InferenceOwner for CancelOnlyInference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
    ) -> Result<ModelSession> {
        panic!("a retained cancellation must not open inference");
    }

    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancellations += 1;
        // Explicit controlled inference ACK; the actual effect owner has none.
        Ok(StopObservation::Stopped)
    }
}

#[tokio::test]
async fn retained_native_cancel_reopens_pending_without_new_effect_dispatch() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    let mut turn = TaskFlowTurnOwner::open(
        &store, fence.clone(), frame.binding.clone(), initial(), Limits::default(), StatusContext,
    ).await.expect("original native turn");
    let cancelled = turn.commit(&frame, Transition::CancelRequested).await.expect("durable intent");
    assert_eq!(cancelled.phase, Phase::CancelRequested);
    drop(turn);
    store.close().await;
    drop(store);

    let reopened = AutomationStore::open(&fixture.layout).await.expect("original SQLite reopen");
    let mut turn = TaskFlowTurnOwner::open(
        &reopened, fence.clone(), frame.binding.clone(), initial(), Limits::default(), StatusContext,
    ).await.expect("reopen same native identity");
    let mut effects = AutomationStatusEffectOwner::new(
        &reopened, &authority, driver(&intent, &provider), admitted(&frame, &intent, &fence, &grant),
    );
    let mut inference = CancelOnlyInference::default();
    // A fresh, uncancelled token cannot erase the original owner's durable intent.
    assert_eq!(run(
        &mut turn, &mut inference, &mut effects, &frame.binding, &Limits::default(),
        &CancellationToken::new(),
    ).await.expect("retained cancellation path"), Outcome::CancellationPending);
    assert_eq!(turn.observe().await.expect("persisted owner").frame, cancelled);
    assert_eq!(inference.cancellations, 1);
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 0);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    assert!(reopened.authorized_taskflow_effect_attempt(
        &intent.run_id, &intent.step_id, intent.attempt,
    ).await.expect("original attempt scan").is_none());
    drop(effects);
    drop(turn);
    reopened.close().await;
}

#[tokio::test]
async fn new_generation_cannot_rebind_original_native_cursor_or_effect_admission() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (_authority, grant) = fixture.authority(&intent);
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open(&fixture.layout).await.expect("original SQLite reopen");
    let mut changed = frame.clone();
    changed.binding.generation = Generation::new(2).expect("new generation");
    let mut changed_fence = fence.clone();
    changed_fence.generation = 2;
    assert!(TaskFlowTurnOwner::open(
        &reopened, changed_fence.clone(), changed.binding.clone(), initial(),
        Limits::default(), StatusContext,
    ).await.is_err());
    assert!(PreboundAutomationStatusEffect::new(
        &changed, intent.clone(), call(&changed).arguments.as_bytes().to_vec(),
        changed_fence, grant.clone(), "fixture-effect-dispatch".into(),
    ).is_err());
    // Positive control: the original admitted identity still attaches unchanged.
    let original = TaskFlowTurnOwner::open(
        &reopened, fence.clone(), frame.binding.clone(), initial(), Limits::default(), StatusContext,
    ).await.expect("original owner remains recoverable");
    assert_eq!(original.observe().await.expect("original frame").frame, frame);
    assert!(PreboundAutomationStatusEffect::new(
        &frame, intent.clone(), call(&frame).arguments.as_bytes().to_vec(),
        fence, grant, "fixture-effect-dispatch".into(),
    ).is_ok());
    assert!(reopened.authorized_taskflow_effect_attempt(
        &intent.run_id, &intent.step_id, intent.attempt,
    ).await.expect("no dispatch attempt created").is_none());
    drop(original);
    reopened.close().await;
}
