//! File-backed fixture diagnostics, not product durability or process-crash qualification.
#![allow(
    clippy::unwrap_used,
    reason = "fixed test fixture setup must fail immediately"
)]

use codex_hepta_agent_loop::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::fs;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use tokio_util::sync::CancellationToken;

static DIRECTORY_ID: AtomicU64 = AtomicU64::new(0);
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        let root = std::env::temp_dir().join(format!(
            "hepta-loop-ack-{}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            DIRECTORY_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn binding() -> TurnBinding {
    TurnBinding {
        run_id: id("run:ack"),
        turn_id: id("turn:ack"),
        generation: Generation::new(1).unwrap(),
        admission_digest: Digest32::of_bytes(b"admitted-fixture"),
        deadline_unix_ms: u64::MAX,
    }
}
fn request(round: u32) -> ModelRequest {
    ModelRequest {
        request_id: id(&format!("request:{round}")),
        payload: "fixture-context".into(),
        context_digest: Digest32::of_bytes(b"fixture-context"),
        input_tokens: 3,
        maximum_output_tokens: 10,
    }
}
fn call() -> ToolCall {
    ToolCall {
        call_id: id("call:1"),
        name: id("fixture.effect"),
        arguments: "{}".into(),
    }
}
fn output(round: u32) -> ModelOutput {
    ModelOutput {
        request_id: id(&format!("request:{round}")),
        continuation_digest: Digest32::of_bytes(format!("fixture-continuation:{round}").as_bytes()),
        text: "fixture-answer".into(),
        calls: if round == 0 { vec![call()] } else { vec![] },
        usage: Usage {
            input_tokens: 3,
            output_tokens: 2,
        },
    }
}
fn count(root: &Path, name: &str) -> u64 {
    match fs::read_to_string(root.join(name)) {
        Ok(v) => v.parse().unwrap(),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => 0,
        Err(e) => panic!("counter read: {e}"),
    }
}
fn increment(root: &Path, name: &str) {
    fs::write(root.join(name), (count(root, name) + 1).to_string()).unwrap();
}
fn save(root: &Path, frame: &Frame) {
    let phase = match &frame.phase {
        Phase::Model(_) => "model",
        Phase::Tools { .. } => "tools",
        Phase::Complete(_) => "complete",
        Phase::CancelRequested => "requested",
        Phase::Cancelled => "cancelled",
    };
    let mut file = fs::File::create(root.join("frame.pending")).unwrap();
    write!(
        file,
        "{} {} {} {phase}",
        frame.revision, frame.round, frame.consumed_tokens
    )
    .unwrap();
    file.sync_all().unwrap();
    drop(file);
    fs::rename(root.join("frame.pending"), root.join("frame")).unwrap();
}
fn load(root: &Path) -> Frame {
    let bytes = fs::read_to_string(root.join("frame")).unwrap();
    let values: Vec<_> = bytes.split_whitespace().collect();
    assert_eq!(values.len(), 4);
    let round = values[1].parse().unwrap();
    Frame {
        binding: binding(),
        revision: values[0].parse().unwrap(),
        round,
        consumed_tokens: values[2].parse().unwrap(),
        phase: match values[3] {
            "model" => Phase::Model(request(round)),
            "tools" => Phase::Tools {
                calls: vec![call()],
                next: 0,
            },
            "complete" => Phase::Complete(output(round)),
            "requested" => Phase::CancelRequested,
            "cancelled" => Phase::Cancelled,
            _ => panic!("invalid fixture checkpoint"),
        },
    }
}
#[derive(Clone, Copy, Debug, PartialEq)]
enum Point {
    Model,
    Tool,
    Intent,
    Ack,
}
struct Context {
    root: PathBuf,
    fault: Option<Point>,
    before_write: bool,
}
impl TurnOwner for Context {
    async fn load(&mut self, expected: &TurnBinding) -> Result<Frame> {
        let frame = load(&self.root);
        assert_eq!(&frame.binding, expected);
        Ok(frame)
    }
    async fn commit(&mut self, previous: &Frame, transition: Transition) -> Result<Frame> {
        let mut next = load(&self.root);
        if &next != previous {
            return Err(Error::Owner("fixture CAS conflict".into()));
        }
        let point = match &transition {
            Transition::ModelCompleted(_) => Point::Model,
            Transition::ToolCompleted { .. } => Point::Tool,
            Transition::CancelRequested => Point::Intent,
            Transition::Cancelled => Point::Ack,
        };
        let fail = self.fault == Some(point);
        if fail {
            self.fault = None;
        }
        if fail && self.before_write {
            return Err(Error::Owner("injected before fixture snapshot".into()));
        }
        next.revision += 1;
        match transition {
            Transition::ModelCompleted(value) => {
                next.consumed_tokens += value.usage.input_tokens + value.usage.output_tokens;
                next.phase = if value.calls.is_empty() {
                    Phase::Complete(value)
                } else {
                    Phase::Tools {
                        calls: value.calls,
                        next: 0,
                    }
                };
            }
            Transition::ToolCompleted { output, .. } => {
                assert_eq!(output, "fixture-effect-result");
                next.round += 1;
                next.phase = Phase::Model(request(next.round));
            }
            Transition::CancelRequested => next.phase = Phase::CancelRequested,
            Transition::Cancelled => next.phase = Phase::Cancelled,
        }
        save(&self.root, &next);
        if fail {
            return Err(Error::Owner(
                "injected reply loss after fixture snapshot".into(),
            ));
        }
        Ok(next)
    }
}
struct Inference {
    root: PathBuf,
}
impl InferenceOwner for Inference {
    async fn open_or_reconcile(
        &mut self,
        _: &TurnBinding,
        request: &ModelRequest,
    ) -> Result<ModelSession> {
        let round: u32 = request
            .request_id
            .as_str()
            .split(':')
            .nth(1)
            .unwrap()
            .parse()
            .unwrap();
        let receipt = self.root.join(format!("model-receipt-{round}"));
        if !receipt.exists() {
            increment(&self.root, "model-executions");
            fs::write(receipt, "fixture-completed").unwrap();
        }
        Ok(ModelSession::Completed(output(round)))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        increment(&self.root, "model-cancellations");
        Ok(StopObservation::Stopped)
    }
}
struct Effects {
    root: PathBuf,
    retain_receipt: bool,
}
impl EffectOwner for Effects {
    async fn execute_or_observe(
        &mut self,
        _: &TurnBinding,
        key: Digest32,
        _: &ToolCall,
    ) -> Result<EffectObservation> {
        increment(&self.root, "effect-observations");
        let key = key.to_string();
        let mut log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("effect-keys"))
            .unwrap();
        writeln!(log, "{key}").unwrap();
        let receipt = self.root.join("effect-receipt");
        if receipt.exists() {
            assert_eq!(fs::read_to_string(&receipt).unwrap(), key);
        } else {
            increment(&self.root, "effect-executions");
            if self.retain_receipt {
                fs::write(receipt, key).unwrap();
            }
        }
        Ok(EffectObservation::Completed("fixture-effect-result".into()))
    }
    async fn cancel(&mut self, _: &TurnBinding) -> Result<StopObservation> {
        increment(&self.root, "effect-cancellations");
        Ok(StopObservation::Stopped)
    }
}
async fn scenario(point: Point, before_write: bool, retain_receipt: bool) {
    let directory = Directory::new();
    save(
        &directory.0,
        &Frame {
            binding: binding(),
            revision: 0,
            round: 0,
            consumed_tokens: 0,
            phase: Phase::Model(request(0)),
        },
    );
    let cancelled = matches!(point, Point::Intent | Point::Ack);
    let token = CancellationToken::new();
    if cancelled {
        token.cancel();
    }
    let mut context = Context {
        root: directory.0.clone(),
        fault: Some(point),
        before_write,
    };
    let mut inference = Inference {
        root: directory.0.clone(),
    };
    let mut effects = Effects {
        root: directory.0.clone(),
        retain_receipt,
    };
    assert!(matches!(
        run(
            &mut context,
            &mut inference,
            &mut effects,
            &binding(),
            &Limits::default(),
            &token
        )
        .await,
        Err(Error::Owner(_))
    ));
    let expected_phase = match (point, before_write) {
        (Point::Model, false) | (Point::Tool, true) => Phase::Tools {
            calls: vec![call()],
            next: 0,
        },
        (Point::Tool, false) => Phase::Model(request(1)),
        (Point::Intent, false) => Phase::CancelRequested,
        (Point::Ack, false) => Phase::Cancelled,
        _ => panic!("unplanned scenario"),
    };
    assert_eq!(load(&directory.0).phase, expected_phase);
    if point == Point::Intent {
        assert_eq!(
            (
                count(&directory.0, "model-cancellations"),
                count(&directory.0, "effect-cancellations")
            ),
            (0, 0)
        );
    }
    drop(context);
    drop(inference);
    drop(effects);
    // Rebuild every adapter from disk only; no frame or owner receipt is carried over.
    let mut context = Context {
        root: directory.0.clone(),
        fault: None,
        before_write: false,
    };
    let mut inference = Inference {
        root: directory.0.clone(),
    };
    let mut effects = Effects {
        root: directory.0.clone(),
        retain_receipt,
    };
    let recovered = run(
        &mut context,
        &mut inference,
        &mut effects,
        &binding(),
        &Limits::default(),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    println!(
        "ACK_LOSS_DIAGNOSTIC point={point:?} before_write={before_write} retain_receipt={retain_receipt} model_executions={} effect_executions={} effect_observations={} model_cancellations={} effect_cancellations={}",
        count(&directory.0, "model-executions"),
        count(&directory.0, "effect-executions"),
        count(&directory.0, "effect-observations"),
        count(&directory.0, "model-cancellations"),
        count(&directory.0, "effect-cancellations")
    );
    if cancelled {
        assert_eq!(recovered, Outcome::Cancelled);
        assert_eq!(
            (
                count(&directory.0, "model-cancellations"),
                count(&directory.0, "effect-cancellations")
            ),
            (1, 1)
        );
        assert_eq!(
            (
                count(&directory.0, "model-executions"),
                count(&directory.0, "effect-executions")
            ),
            (0, 0)
        );
    } else {
        assert_eq!(recovered, Outcome::Completed(output(1)));
        assert_eq!(count(&directory.0, "model-executions"), 2);
        assert_eq!(
            count(&directory.0, "effect-executions"),
            if retain_receipt { 1 } else { 2 }
        );
        assert_eq!(
            count(&directory.0, "effect-observations"),
            if before_write { 2 } else { 1 }
        );
        let keys = fs::read_to_string(directory.0.join("effect-keys")).unwrap();
        let keys: Vec<_> = keys.lines().collect();
        assert!(keys.iter().all(|key| *key == keys[0]));
    }
}
#[tokio::test]
async fn model_commit_reply_loss_reloads_committed_tool_cursor() {
    scenario(
        Point::Model,
        /*before_write*/ false,
        /*retain_receipt*/ true,
    )
    .await;
}
#[tokio::test]
async fn tool_commit_reply_loss_does_not_repeat_effect_observation() {
    scenario(
        Point::Tool,
        /*before_write*/ false,
        /*retain_receipt*/ true,
    )
    .await;
}
#[tokio::test]
async fn cancel_intent_reply_loss_reloads_before_both_owner_acks() {
    scenario(
        Point::Intent,
        /*before_write*/ false,
        /*retain_receipt*/ true,
    )
    .await;
}
#[tokio::test]
async fn cancel_terminal_reply_loss_does_not_repeat_owner_cancellation() {
    scenario(
        Point::Ack,
        /*before_write*/ false,
        /*retain_receipt*/ true,
    )
    .await;
}
#[tokio::test]
async fn prewrite_failure_reobserves_same_key_with_owner_receipt() {
    scenario(
        Point::Tool,
        /*before_write*/ true,
        /*retain_receipt*/ true,
    )
    .await;
}
#[tokio::test]
async fn missing_owner_receipt_negative_control_executes_twice() {
    scenario(
        Point::Tool,
        /*before_write*/ true,
        /*retain_receipt*/ false,
    )
    .await;
}
