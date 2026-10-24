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
                maximum_provider_input_tokens: 3,
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

struct LoadedContext(Frame);
impl TurnOwner for LoadedContext {
    async fn load(&mut self, _: &TurnBinding) -> Result<Frame> {
        Ok(self.0.clone())
    }
    async fn commit(&mut self, previous: &Frame, transition: Transition) -> Result<Frame> {
        assert_eq!(previous, &self.0);
        self.0.revision += 1;
        self.0.phase = match transition {
            Transition::CancelRequested => Phase::CancelRequested,
            Transition::Cancelled => Phase::Cancelled,
            _ => panic!("unexpected dispatch"),
        };
        Ok(self.0.clone())
    }
}

fn terminal_frame() -> Frame {
    Frame {
        binding: TurnBinding {
            run_id: StableId::new("run:terminal").unwrap(),
            turn_id: StableId::new("turn:terminal").unwrap(),
            generation: Generation::new(1).unwrap(),
            admission_digest: Digest32::of_bytes(b"admission"),
            deadline_unix_ms: u64::MAX,
        },
        revision: 1,
        round: 0,
        consumed_tokens: 2,
        phase: Phase::Complete(ModelOutput {
            request_id: StableId::new("request:terminal").unwrap(),
            continuation_digest: Digest32::of_bytes(b"continuation"),
            text: "done".into(),
            calls: vec![],
            usage: Usage {
                input_tokens: 1,
                output_tokens: 1,
            },
        }),
    }
}

async fn check_terminal_budget(expired: bool, round: bool) {
    let mut frame = terminal_frame();
    let limits = Limits::default();
    if round {
        frame.round = limits.maximum_rounds;
    } else {
        frame.consumed_tokens = limits.maximum_total_tokens + 1;
    }
    // Ordinary entry already rejects exactly this frame under caller limits.
    let mut normal = LoadedContext(frame.clone());
    let binding = frame.binding.clone();
    assert!(matches!(
        run(
            &mut normal,
            &mut Inference::default(),
            &mut Effects::default(),
            &binding,
            &limits,
            &CancellationToken::new()
        )
        .await,
        Err(Error::Limit("rounds or tokens"))
    ));
    let cancellation = CancellationToken::new();
    if expired {
        frame.binding.deadline_unix_ms = 1;
    } else {
        cancellation.cancel();
    }
    let binding = frame.binding.clone();
    let mut context = LoadedContext(frame);
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    let result = run(
        &mut context,
        &mut inference,
        &mut effects,
        &binding,
        &limits,
        &cancellation,
    )
    .await;
    assert!(
        matches!(result, Err(Error::Limit("rounds or tokens"))),
        "terminal budget bypass: {result:?}"
    );
    assert_eq!((inference.cancellations, effects.cancellations), (0, 0));
}

#[tokio::test]
async fn terminal_precancel_round_limit() {
    check_terminal_budget(false, true).await;
}
#[tokio::test]
async fn terminal_precancel_token_limit() {
    check_terminal_budget(false, false).await;
}
#[tokio::test]
async fn terminal_deadline_round_limit() {
    check_terminal_budget(true, true).await;
}
#[tokio::test]
async fn terminal_deadline_token_limit() {
    check_terminal_budget(true, false).await;
}

#[tokio::test]
async fn terminal_valid_cancellation_entry_preserves_completion() {
    for expired in [false, true] {
        let mut frame = terminal_frame();
        let output = match &frame.phase {
            Phase::Complete(output) => output.clone(),
            _ => unreachable!(),
        };
        let cancellation = CancellationToken::new();
        if expired {
            frame.binding.deadline_unix_ms = 1;
        } else {
            cancellation.cancel();
        }
        let binding = frame.binding.clone();
        let outcome = run(
            &mut LoadedContext(frame),
            &mut Inference::default(),
            &mut Effects::default(),
            &binding,
            &Limits::default(),
            &cancellation,
        )
        .await
        .unwrap();
        assert_eq!(outcome, Outcome::Completed(output));
    }
}

#[tokio::test]
async fn active_over_budget_still_cancels_both_owners() {
    let mut frame = terminal_frame();
    frame.consumed_tokens = Limits::default().maximum_total_tokens + 1;
    frame.phase = Phase::CancelRequested;
    let binding = frame.binding.clone();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    let outcome = run(
        &mut LoadedContext(frame),
        &mut inference,
        &mut effects,
        &binding,
        &Limits::default(),
        &cancellation,
    )
    .await
    .unwrap();
    assert_eq!(outcome, Outcome::Cancelled);
    assert_eq!((inference.cancellations, effects.cancellations), (1, 1));
}
