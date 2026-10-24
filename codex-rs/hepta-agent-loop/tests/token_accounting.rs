use codex_hepta_agent_loop::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

struct Context(Frame);
struct Inference(ModelOutput, usize);
struct Effects;

impl TurnOwner for Context {
    async fn load(&mut self, _: &TurnBinding) -> Result<Frame> {
        Ok(self.0.clone())
    }
    async fn commit(&mut self, before: &Frame, change: Transition) -> Result<Frame> {
        assert_eq!(before, &self.0);
        match change {
            Transition::ModelCompleted(output) => {
                self.0.consumed_tokens += output.usage.input_tokens + output.usage.output_tokens;
                self.0.phase = Phase::Complete(output);
            }
            Transition::CancelRequested => self.0.phase = Phase::CancelRequested,
            Transition::Cancelled => self.0.phase = Phase::Cancelled,
            Transition::ToolCompleted { .. } => panic!("unexpected tool commit"),
        }
        self.0.revision += 1;
        Ok(self.0.clone())
    }
}

impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        _: &ModelRequest,
    ) -> Result<ModelSession> {
        self.1 += 1;
        Ok(ModelSession::Completed(self.0.clone()))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        Ok(StopObservation::Stopped)
    }
}

impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        _: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        panic!("these accounting cases must not dispatch tools");
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        Ok(StopObservation::Stopped)
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture ID")
}

async fn execute(actual_input: u64, maximum_total: u64) -> (Result<Outcome>, Context, Inference) {
    let binding = TurnBinding {
        run_id: id("run:accounting"),
        turn_id: id("turn:1"),
        generation: Generation::new(1).expect("generation"),
        admission_digest: Digest32::of_bytes(b"admitted"),
        deadline_unix_ms: u64::MAX,
    };
    let request = ModelRequest {
        request_id: id("model:1"),
        payload: "compiled".into(),
        context_digest: Digest32::of_bytes(b"compiled"),
        input_tokens: 3,
        maximum_provider_input_tokens: 8,
        maximum_output_tokens: 4,
    };
    let mut context = Context(Frame {
        binding: binding.clone(),
        revision: 1,
        round: 0,
        consumed_tokens: 0,
        phase: Phase::Model(request),
    });
    let mut inference = Inference(
        ModelOutput {
            request_id: id("model:1"),
            continuation_digest: Digest32::of_bytes(b"retained"),
            text: "answer".into(),
            calls: Vec::new(),
            usage: Usage {
                input_tokens: actual_input,
                output_tokens: 2,
            },
        },
        0,
    );
    let mut effects = Effects;
    let limits = Limits {
        maximum_total_tokens: maximum_total,
        ..Default::default()
    };
    let result = run(
        &mut context,
        &mut inference,
        &mut effects,
        &binding,
        &limits,
        &CancellationToken::new(),
    )
    .await;
    (result, context, inference)
}

#[tokio::test]
async fn charge_provider_usage_instead_of_substituting_compiled_context_count() {
    let (result, context, _) = execute(6, 12).await;
    assert!(matches!(result, Ok(Outcome::Completed(_))));
    assert_eq!(context.0.consumed_tokens, 8);
}

#[tokio::test]
async fn provider_framing_must_fit_an_explicit_reservation() {
    let (result, context, inference) = execute(9, 12).await;
    assert!(matches!(result, Err(Error::Limit("model output or usage"))));
    assert!(matches!(context.0.phase, Phase::Cancelled));
    assert_eq!(inference.0.usage.input_tokens, 9);
}

#[tokio::test]
async fn preflight_reserves_provider_overhead_before_dispatch() {
    let (result, _, inference) = execute(6, 7).await;
    assert!(matches!(result, Err(Error::Limit("prepared context"))));
    assert_eq!(inference.1, 0);
}
