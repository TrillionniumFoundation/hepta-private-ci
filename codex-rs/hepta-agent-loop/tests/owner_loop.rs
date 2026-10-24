use std::collections::BTreeMap;
use std::collections::VecDeque;

use codex_hepta_agent_loop::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("invalid fixture ID: {error}"))
}

fn request(round: u32) -> ModelRequest {
    let payload = format!("compiled-context-{round}");
    ModelRequest {
        request_id: id(&format!("inference:{round}")),
        context_digest: Digest32::of_bytes(payload.as_bytes()),
        payload: payload.into(),
        input_tokens: 3,
        maximum_output_tokens: 10,
    }
}

struct Context {
    frame: Frame,
    transitions: Vec<Transition>,
    fail_tool_commit: bool,
}

impl Context {
    fn new() -> Self {
        Self {
            frame: Frame {
                binding: TurnBinding {
                    run_id: id("run:1"),
                    turn_id: id("turn:1"),
                    generation: Generation::new(1)
                        .unwrap_or_else(|error| panic!("invalid generation: {error}")),
                    admission_digest: Digest32::of_bytes(b"admission"),
                    deadline_unix_ms: u64::MAX,
                },
                revision: 1,
                round: 0,
                consumed_tokens: 0,
                phase: Phase::Model(request(0)),
            },
            transitions: Vec::new(),
            fail_tool_commit: false,
        }
    }
}

impl TurnOwner for Context {
    async fn load(&mut self, _: &TurnBinding) -> Result<Frame> {
        Ok(self.frame.clone())
    }
    async fn commit(&mut self, previous: &Frame, transition: Transition) -> Result<Frame> {
        if previous != &self.frame {
            return Err(Error::Owner("CAS conflict".into()));
        }
        if matches!(transition, Transition::ToolCompleted { .. }) && self.fail_tool_commit {
            self.fail_tool_commit = false;
            return Err(Error::Owner("interrupted durable commit".into()));
        }
        match &transition {
            Transition::ModelCompleted(output) => {
                self.frame.consumed_tokens +=
                    output.usage.input_tokens + output.usage.output_tokens;
                self.frame.phase = if output.calls.is_empty() {
                    Phase::Complete(output.clone())
                } else {
                    Phase::Tools {
                        calls: output.calls.clone(),
                        next: 0,
                    }
                };
            }
            Transition::ToolCompleted { .. } => {
                let Phase::Tools { calls, next } = &mut self.frame.phase else {
                    panic!("tool phase")
                };
                *next += 1;
                if *next == calls.len() {
                    self.frame.round += 1;
                    self.frame.phase = Phase::Model(request(self.frame.round));
                }
            }
            Transition::CancelRequested => self.frame.phase = Phase::CancelRequested,
            Transition::Cancelled => self.frame.phase = Phase::Cancelled,
        }
        self.transitions.push(transition);
        self.frame.revision += 1;
        Ok(self.frame.clone())
    }
}

#[derive(Default)]
struct Inference {
    sessions: VecDeque<ModelSession>,
    opened: Vec<StableId>,
    cancelled: usize,
    stall_cancel: bool,
}

impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        request: &ModelRequest,
    ) -> Result<ModelSession> {
        self.opened.push(request.request_id.clone());
        Ok(self
            .sessions
            .pop_front()
            .unwrap_or(ModelSession::Unresolved))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancelled += 1;
        if self.stall_cancel {
            std::future::pending::<()>().await;
        }
        Ok(StopObservation::Stopped)
    }
}

#[derive(Default)]
struct Effects {
    keys: Vec<Digest32>,
    receipts: BTreeMap<Digest32, String>,
    executions: usize,
    unresolved: bool,
    cancelled: usize,
}

impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        key: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        self.keys.push(key);
        if self.unresolved {
            return Ok(EffectObservation::Unresolved);
        }
        let output = self.receipts.entry(key).or_insert_with(|| {
            self.executions += 1;
            "tool-result".into()
        });
        Ok(EffectObservation::Completed(output.clone()))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        self.cancelled += 1;
        Ok(if self.unresolved {
            StopObservation::Unresolved
        } else {
            StopObservation::Stopped
        })
    }
}

fn call() -> ToolCall {
    ToolCall {
        call_id: id("call:1"),
        name: id("owned.read"),
        arguments: "{}".into(),
    }
}

fn output(round: u32, calls: Vec<ToolCall>) -> ModelOutput {
    ModelOutput {
        request_id: id(&format!("inference:{round}")),
        continuation_digest: Digest32::of_bytes(
            format!("full-provider-continuation:{round}").as_bytes(),
        ),
        text: "answer".into(),
        calls,
        usage: Usage {
            input_tokens: 3,
            output_tokens: 2,
        },
    }
}

async fn drive(
    context: &mut Context,
    inference: &mut Inference,
    effects: &mut Effects,
) -> Result<Outcome> {
    let binding = context.frame.binding.clone();
    run(
        context,
        inference,
        effects,
        &binding,
        &Limits::default(),
        &CancellationToken::new(),
    )
    .await
}

#[tokio::test]
async fn streamed_tool_turn_commits_before_dispatch_and_resumes_model() {
    let (tx, rx) = mpsc::channel(4);
    tx.send(Ok(ModelEvent::TextDelta("thinking".into())))
        .await
        .unwrap();
    tx.send(Ok(ModelEvent::ToolCall(call()))).await.unwrap();
    tx.send(Ok(ModelEvent::Completed {
        request_id: id("inference:0"),
        continuation_digest: Digest32::of_bytes(b"retained-provider-items"),
        usage: Usage {
            input_tokens: 3,
            output_tokens: 2,
        },
    }))
    .await
    .unwrap();
    let mut context = Context::new();
    let mut inference = Inference {
        sessions: VecDeque::from([
            ModelSession::Stream(rx),
            ModelSession::Completed(output(1, Vec::new())),
        ]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Completed(output(1, Vec::new()))
    );
    assert_eq!(
        (
            effects.executions,
            context.frame.round,
            context.frame.consumed_tokens
        ),
        (1, 1, 10)
    );
    assert_eq!(inference.opened, vec![id("inference:0"), id("inference:1")]);
}

#[tokio::test]
async fn partial_stream_never_executes_tools_and_reconnect_uses_original_request() {
    let (tx, rx) = mpsc::channel(2);
    tx.send(Ok(ModelEvent::ToolCall(call()))).await.unwrap();
    drop(tx);
    let mut context = Context::new();
    let original = context.frame.clone();
    let mut inference = Inference {
        sessions: VecDeque::from([ModelSession::Stream(rx)]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Paused
    );
    assert_eq!((&context.frame, effects.executions), (&original, 0));
    inference
        .sessions
        .push_back(ModelSession::Completed(output(0, Vec::new())));
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Completed(output(0, Vec::new()))
    );
    assert_eq!(inference.opened, vec![id("inference:0"), id("inference:0")]);
}

#[tokio::test]
async fn unresolved_effect_keeps_exact_key_across_loop_instances() {
    let mut context = Context::new();
    let mut inference = Inference {
        sessions: VecDeque::from([
            ModelSession::Completed(output(0, vec![call()])),
            ModelSession::Completed(output(1, Vec::new())),
        ]),
        ..Default::default()
    };
    let mut effects = Effects {
        unresolved: true,
        ..Default::default()
    };
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Paused
    );
    effects.unresolved = false;
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Completed(output(1, Vec::new()))
    );
    assert_eq!(
        (&effects.keys[0], effects.executions),
        (&effects.keys[1], 1)
    );
}

#[tokio::test]
async fn commit_interruption_reconciles_effect_without_executing_it_twice() {
    let mut context = Context::new();
    context.fail_tool_commit = true;
    let mut inference = Inference {
        sessions: VecDeque::from([
            ModelSession::Completed(output(0, vec![call()])),
            ModelSession::Completed(output(1, Vec::new())),
        ]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert!(matches!(
        drive(&mut context, &mut inference, &mut effects).await,
        Err(Error::Owner(_))
    ));
    assert_eq!(inference.cancelled, 0);
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Completed(output(1, Vec::new()))
    );
    assert_eq!(
        (&effects.keys[0], effects.executions),
        (&effects.keys[1], 1)
    );
}

#[tokio::test]
async fn cancellation_waits_for_effect_owner_acknowledgement() {
    let mut context = Context::new();
    let mut inference = Inference::default();
    let mut effects = Effects {
        unresolved: true,
        ..Default::default()
    };
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let binding = context.frame.binding.clone();
    assert_eq!(
        run(
            &mut context,
            &mut inference,
            &mut effects,
            &binding,
            &Limits::default(),
            &cancellation
        )
        .await
        .unwrap(),
        Outcome::CancellationPending
    );
    assert_eq!(context.frame.phase, Phase::CancelRequested);
    effects.unresolved = false;
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Cancelled
    );
    assert_eq!((inference.opened.len(), effects.executions), (0, 0));
}

#[tokio::test(start_paused = true)]
async fn stalled_model_cancellation_does_not_prevent_effect_cancellation() {
    let mut context = Context::new();
    let mut inference = Inference {
        stall_cancel: true,
        ..Default::default()
    };
    let mut effects = Effects::default();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let binding = context.frame.binding.clone();
    assert_eq!(
        run(
            &mut context,
            &mut inference,
            &mut effects,
            &binding,
            &Limits::default(),
            &cancellation
        )
        .await
        .unwrap(),
        Outcome::CancellationPending
    );
    assert_eq!((inference.cancelled, effects.cancelled), (1, 1));
    assert_eq!(context.frame.phase, Phase::CancelRequested);
}

#[tokio::test]
async fn reconnect_does_not_reset_the_original_deadline() {
    let mut context = Context::new();
    context.frame.binding.deadline_unix_ms = 1;
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Cancelled
    );
    assert_eq!(inference.opened.len(), 0);
}

#[tokio::test]
async fn duplicate_provider_calls_are_rejected_before_any_effect() {
    let mut context = Context::new();
    let mut inference = Inference {
        sessions: VecDeque::from([ModelSession::Completed(output(0, vec![call(), call()]))]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert!(matches!(
        drive(&mut context, &mut inference, &mut effects).await,
        Err(Error::Contract("duplicate tool call"))
    ));
    assert_eq!((effects.executions, inference.cancelled), (0, 1));
}

#[tokio::test]
async fn foreign_completion_cannot_dispatch_a_tool() {
    let mut context = Context::new();
    let mut inference = Inference {
        sessions: VecDeque::from([ModelSession::Completed(output(9, vec![call()]))]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert!(matches!(
        drive(&mut context, &mut inference, &mut effects).await,
        Err(Error::Contract("model completion binding"))
    ));
    assert_eq!(effects.executions, 0);
}

#[tokio::test]
async fn text_only_completion_without_retained_provider_items_is_rejected() {
    let mut context = Context::new();
    let mut terminal = output(0, Vec::new());
    terminal.continuation_digest = Digest32::ZERO;
    let mut inference = Inference {
        sessions: VecDeque::from([ModelSession::Completed(terminal)]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert!(matches!(
        drive(&mut context, &mut inference, &mut effects).await,
        Err(Error::Contract("model completion binding"))
    ));
}

#[tokio::test(start_paused = true)]
async fn deadline_cancels_a_stalled_stream_without_terminal_success() {
    let (_tx, rx) = mpsc::channel(1);
    let mut context = Context::new();
    let mut inference = Inference {
        sessions: VecDeque::from([ModelSession::Stream(rx)]),
        ..Default::default()
    };
    let mut effects = Effects::default();
    assert_eq!(
        drive(&mut context, &mut inference, &mut effects)
            .await
            .unwrap(),
        Outcome::Cancelled
    );
    assert_eq!(inference.cancelled, 1);
}

#[tokio::test]
async fn oversized_context_is_rejected_before_provider_dispatch() {
    let mut context = Context::new();
    let Phase::Model(request) = &mut context.frame.phase else {
        panic!("model")
    };
    request.payload = "x".repeat(256 * 1024 + 1).into();
    let mut inference = Inference::default();
    let mut effects = Effects::default();
    assert!(matches!(
        drive(&mut context, &mut inference, &mut effects).await,
        Err(Error::Limit("prepared context"))
    ));
    assert_eq!(inference.opened.len(), 0);
}
