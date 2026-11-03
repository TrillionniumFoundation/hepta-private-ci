//! Reducer ownership regressions using the actual signed preparation and
//! original writer. The adapter stops before the first native checkpoint;
//! direct reducer calls below do not claim to exercise Core recovery admission.

use super::*;
use std::sync::OnceLock;

use codex_core::hosted_turn::{HostedAdmittedTurn, HostedFuture, HostedTurnExecution,
    HostedTurnExecutor, HostedTurnInput, HostedTurnObservation, HostedTurnOutcome, HostedTurnPlan};
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use crate::NativeTurnAdmission;
use crate::canonical_queued_input::CanonicalQueuedRunV1;
use crate::state::native_tests::resume_original_prepared_for_test;

#[derive(Default)]
struct PreparedCut {
    original_turn: OnceLock<(ThreadId, String)>,
    ready: tokio::sync::Notify,
}

struct StopBeforeCheckpoint {
    original: Arc<dyn HostedTurnExecutor>,
    cut: Arc<PreparedCut>,
}

impl HostedTurnExecutor for StopBeforeCheckpoint {
    fn executor_id(&self) -> &str { self.original.executor_id() }

    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        Box::pin(async move {
            let mut plan = self.original.prepare(input).await?;
            plan.execution = Box::new(PreparedOnlyExecution(self.cut.clone()));
            Ok(plan)
        })
    }

    fn observe_admission<'a>(&'a self, input: HostedTurnObservation) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(input)
    }
}

struct PreparedOnlyExecution(Arc<PreparedCut>);

impl HostedTurnExecution for PreparedOnlyExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            self.0.original_turn.set((turn.thread_id(), turn.turn_id().to_owned()))
                .map_err(|_| codex_protocol::error::CodexErr::InvalidRequest(
                    "original prepared cut was entered twice".to_owned()))?;
            self.0.ready.notify_one();
            Ok(HostedTurnOutcome::PendingObservation)
        })
    }
}

async fn prepared_fixture(server: &MockServer) -> Result<(ObjectiveFixture, NativeCheckpointBinding)> {
    let cut = Arc::new(PreparedCut::default());
    let captured = cut.clone();
    let fixture = ObjectiveFixture::with_executor_adapter(server, ReplyFault::None, agent(),
        Arc::new(NoToolCompiler), move |original, _| Arc::new(StopBeforeCheckpoint { original, cut: captured })).await?;
    fixture.submit(fixture.request.clone()).await?;
    tokio::time::timeout(Duration::from_secs(10), cut.ready.notified()).await?;
    let held = wait_for_event_match(&fixture.core.codex, |event| match event {
        EventMsg::Error(error) => Some(format!("{error:?}")), _ => None,
    }).await;
    ensure!(held.contains("outcome is unknown"), "original execution must remain technically held: {held}");
    let (thread_id, turn_id) = cut.original_turn.get().context("actual original Core turn")?;
    let attached = fixture.base.state.native_run_receipt(&fixture.request.body.run_id)?;
    ensure!(attached.phase == RunPhase::ContextAttached, "the original prepared run was dispatched unexpectedly");
    let original = NativeCheckpointBinding {
        thread_id: *thread_id, turn_id: turn_id.clone(), operation_id: attached.run_id,
        generation: attached.generation, lease_id: fixture.base.writer.lease_id().to_owned(),
    };
    Ok((fixture, original))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_attached_reducer_skips_the_old_initial_admission_with_a_real_unused_scope() -> Result<()> {
    let server = provider().await;
    let (fixture, original) = prepared_fixture(&server).await?;
    let state = &fixture.base.state;
    let attached = state.native_run_receipt(&original.operation_id)?;
    let snapshot = state.native_run_snapshot(&original.operation_id)?;
    let journal = fixture.host.committed_prepared(&original.operation_id)?.context("original prepared journal")?;
    let restored = state.load_canonical_prepared(&original.operation_id)?.context("original sealed preparation")?;
    let record = fixture.host.original_record(&original.operation_id)?;
    let queued = CanonicalQueuedRunV1 {
        input: state.canonical_queued_input(&record)?, context: restored.context().clone(),
    };
    let old = fixture.base.native.admission(original.clone(), fixture.base.scope.clone(), &attached)?;
    let old_revision = old.fresh_revision.context("original initial plan's reserved dispatch revision")?;
    assert_eq!(old_revision, attached.revision + 1);
    let scope = Sha256Digest::parse(old.scope_digest.to_string()).map_err(anyhow::Error::msg)?;
    let unused = fixture.base.writer.observe_unused_scope(&scope).await?;
    let resumed = resume_original_prepared_for_test(state, &restored, queued, &unused,
        &fixture.base.writer, &scope)?;
    let mut expected = attached.clone();
    expected.phase = RunPhase::Dispatched;
    expected.revision = old_revision + 1;
    expected.idempotent = false;
    assert_eq!(resumed, expected, "the original reducer must preserve every other receipt field");
    assert_eq!(state.native_run_snapshot(&original.operation_id)?, snapshot);
    assert!(state.dispatch_native_run(&attached).is_err(), "the old actual attachment cannot redispatch");
    drop(unused);

    let mut initial = TurnState::new(old.binding()?, String::new());
    initial.context = restored.context().context().to_vec();
    let body = agent().model_request_body(&initial)?;
    let failure = old.admit_model(&initial.binding, 0, &body).await.err().context("old initial admission was revived")?;
    assert!(failure.to_string().contains("revision"));
    drop(fixture.base.writer.observe_unused_scope(&scope).await?);
    assert_eq!(fixture.host.committed_prepared(&original.operation_id)?, Some(journal));
    assert_eq!(state.native_run_receipt(&original.operation_id)?, resumed);
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.base.final_use.capacity()?.used_nonces), (1, 0, 0));
    assert!(server.received_requests().await.context("original HTTP capture")?.is_empty());
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_completion_belongs_only_to_its_actual_dispatched_attempt() -> Result<()> {
    for replace in [false, true] {
        let server = provider().await;
        let (fixture, original) = prepared_fixture(&server).await?;
        let state = &fixture.base.state;
        let attached = state.native_run_receipt(&original.operation_id)?;
        let restored = state.load_canonical_prepared(&original.operation_id)?.context("original sealed preparation")?;
        let record = fixture.host.original_record(&original.operation_id)?;
        let queued = CanonicalQueuedRunV1 {
            input: state.canonical_queued_input(&record)?, context: restored.context().clone(),
        };
        let admission = fixture.base.native.admission(original.clone(), fixture.base.scope.clone(), &attached)?;
        let scope = Sha256Digest::parse(admission.scope_digest.to_string()).map_err(anyhow::Error::msg)?;
        let active = state.dispatch_native_run(&attached)?;
        let old = state.require_native_effect(&original.operation_id)?;
        let current = if replace {
            let unused = fixture.base.writer.observe_unused_scope(&scope).await?;
            let replacement = resume_original_prepared_for_test(state, &restored, queued, &unused,
                &fixture.base.writer, &scope)?;
            assert_eq!(replacement.revision, old.revision + 1);
            drop(unused);
            replacement
        } else { old.clone() };
        state.response(/*request_id*/ 93, state.identity().spawn_generation, crate::AgentdMethod::RunCancel {
            run_id: original.operation_id.clone(), expected_revision: current.revision,
            reason: "original owner cancellation".to_owned(),
        }).await?;
        let cancelling = state.native_run_receipt(&original.operation_id)?;
        assert_eq!((cancelling.phase, cancelling.revision), (RunPhase::Cancelling, current.revision + 1));
        assert_eq!(cancelling.cancel_reason.as_deref(), Some("original owner cancellation"));
        assert!(state.require_native_effect(&original.operation_id).is_err());
        if replace {
            assert_eq!(cancelling.revision, old.revision + 2);
            for phase in [RunPhase::Cancelled, RunPhase::Succeeded, RunPhase::Indeterminate] {
                assert!(state.observe_native_run_at_revision(&original.operation_id, old.revision, phase).is_err(),
                    "an old attempt cannot borrow its successor's cancellation: {phase:?}");
                assert_eq!(state.native_run_receipt(&original.operation_id)?, cancelling);
            }
            state.abandon_native_run(&original.operation_id, old.revision)?;
            assert_eq!(state.native_run_receipt(&original.operation_id)?, cancelling,
                "old abandonment must not consume the successor's cancellation");
        }
        let terminal = state.observe_native_run_at_revision(&original.operation_id, current.revision, RunPhase::Cancelled)?;
        assert_eq!((terminal.phase, terminal.revision), (RunPhase::Cancelled, cancelling.revision + 1));
        assert!(terminal.terminal_observed);
        assert_eq!(terminal.cancel_reason, cancelling.cancel_reason);
        drop(active);
        drop(fixture.base.writer.observe_unused_scope(&scope).await?);
        assert_eq!((fixture.owners.calls.load(Ordering::SeqCst), fixture.base.issuer.grants.load(Ordering::SeqCst),
            fixture.base.final_use.capacity()?.used_nonces), (1, 0, 0));
        assert!(server.received_requests().await.context("original HTTP capture")?.is_empty());
        fixture.shutdown().await?;
    }
    Ok(())
}
