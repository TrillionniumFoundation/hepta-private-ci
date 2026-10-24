//! Controlled invalid-owner replies, not a durable product-owner qualification.
#![allow(
    clippy::unwrap_used,
    reason = "invalid fixed fixture identifiers must fail the test immediately"
)]

use codex_hepta_agent_loop::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

#[derive(Clone, Copy)]
enum Drift {
    SameRevision,
    SkippedRevision,
    Round,
    Tokens,
}

struct Context {
    frame: Frame,
    corrupt_final: bool,
    drift: Drift,
}

impl TurnOwner for Context {
    async fn load(&mut self, _: &TurnBinding) -> Result<Frame> {
        Ok(self.frame.clone())
    }

    async fn commit(&mut self, previous: &Frame, transition: Transition) -> Result<Frame> {
        assert_eq!(previous, &self.frame);
        let final_commit = matches!(transition, Transition::Cancelled);
        self.frame.revision += 1;
        self.frame.phase = match transition {
            Transition::CancelRequested => Phase::CancelRequested,
            Transition::Cancelled => Phase::Cancelled,
            _ => panic!("unexpected normal transition"),
        };
        if final_commit == self.corrupt_final {
            match self.drift {
                Drift::SameRevision => self.frame.revision -= 1,
                Drift::SkippedRevision => self.frame.revision += 1,
                Drift::Round => self.frame.round += 1,
                Drift::Tokens => self.frame.consumed_tokens += 1,
            }
        }
        Ok(self.frame.clone())
    }
}

#[derive(Default)]
struct Inference {
    cancellations: usize,
}

impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
    ) -> Result<ModelSession> {
        panic!("pre-cancelled turn must not dispatch")
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancellations += 1;
        Ok(StopObservation::Stopped)
    }
}

#[derive(Default)]
struct Effects {
    cancellations: usize,
}

impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        _: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        panic!("pre-cancelled turn must not execute")
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancellations += 1;
        Ok(StopObservation::Stopped)
    }
}

async fn rejects_drift(drift: Drift, corrupt_final: bool) {
    let binding = TurnBinding {
        run_id: StableId::new("run:cancel").unwrap(),
        turn_id: StableId::new("turn:cancel").unwrap(),
        generation: Generation::new(1).unwrap(),
        admission_digest: Digest32::of_bytes(b"admission"),
        deadline_unix_ms: u64::MAX,
    };
    let mut context = Context {
        frame: Frame {
            binding: binding.clone(),
            revision: 7,
            round: 2,
            consumed_tokens: 10,
            phase: Phase::Model(ModelRequest {
                request_id: StableId::new("request:cancel").unwrap(),
                payload: "context".into(),
                context_digest: Digest32::of_bytes(b"context"),
                input_tokens: 3,
                maximum_output_tokens: 10,
            }),
        },
        corrupt_final,
        drift,
    };
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let outcome = run(
        &mut context,
        &mut inference,
        &mut effects,
        &binding,
        &Limits::default(),
        &cancellation,
    )
    .await;
    assert!(
        matches!(outcome, Err(Error::Contract(_))),
        "accepted invalid cancellation successor: {outcome:?}"
    );
    let expected = usize::from(corrupt_final);
    assert_eq!(
        (inference.cancellations, effects.cancellations),
        (expected, expected)
    );
}

#[tokio::test]
async fn cancel_intent_rejects_unchanged_revision() {
    rejects_drift(Drift::SameRevision, /*corrupt_final*/ false).await;
}
#[tokio::test]
async fn cancel_intent_rejects_skipped_revision() {
    rejects_drift(Drift::SkippedRevision, /*corrupt_final*/ false).await;
}
#[tokio::test]
async fn cancel_intent_rejects_round_drift() {
    rejects_drift(Drift::Round, /*corrupt_final*/ false).await;
}
#[tokio::test]
async fn cancel_intent_rejects_token_drift() {
    rejects_drift(Drift::Tokens, /*corrupt_final*/ false).await;
}
#[tokio::test]
async fn cancel_ack_rejects_unchanged_revision() {
    rejects_drift(Drift::SameRevision, /*corrupt_final*/ true).await;
}
#[tokio::test]
async fn cancel_ack_rejects_skipped_revision() {
    rejects_drift(Drift::SkippedRevision, /*corrupt_final*/ true).await;
}
#[tokio::test]
async fn cancel_ack_rejects_round_drift() {
    rejects_drift(Drift::Round, /*corrupt_final*/ true).await;
}
#[tokio::test]
async fn cancel_ack_rejects_token_drift() {
    rejects_drift(Drift::Tokens, /*corrupt_final*/ true).await;
}
