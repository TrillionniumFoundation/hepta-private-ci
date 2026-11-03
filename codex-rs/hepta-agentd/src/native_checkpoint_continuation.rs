//! Fresh continuation is separate from original-effect observation. Core must
//! own the same logical turn and original persisted Queue binding; the original
//! writer must independently prove which operations can precede the next step.

use codex_core::hosted_turn::HostedCheckpointContinuationInput;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::{ProductionDurableWriter, ProductionScopeFrontier, ProductionUnusedScope};
use codex_thread_store::StoredNativeCheckpoint;

use super::*;
use crate::native_host::NativePreparedGuard;

#[path = "native_checkpoint_fold.rs"]
mod fold;
use fold::NativeCheckpointFold;

enum NativeContinuationFrontier {
    Unused(ProductionUnusedScope),
    Settled(ProductionScopeFrontier),
}

/// Private, non-cloneable evidence consumed by this same-turn path. Neither a
/// serialized checkpoint nor a caller-created Queue observation constructs it.
/// It is not a grant: every physical entry still uses the actual Core task,
/// Agentd/Fleet gate, original writer and original FinalUse authority.
pub(crate) struct NativeContinuationEvidence {
    original: crate::RunRecovery,
    checkpoint: StoredNativeCheckpoint,
    anchor: NativeTurnAnchorV1,
    scope: Sha256Digest,
    frontier: NativeContinuationFrontier,
}

impl NativeContinuationEvidence {
    pub(crate) fn original(&self) -> &crate::RunRecovery { &self.original }

    pub(crate) fn anchor(&self) -> &NativeTurnAnchorV1 { &self.anchor }

    pub(crate) fn verify_binding(&self, writer: &ProductionDurableWriter,
        scope: &Sha256Digest) -> Result<()> {
        ensure!(scope == &self.scope && self.anchor.run.as_ref() == Some(&self.original)
            && self.checkpoint.state.binding == self.anchor.checkpoint,
            "original checkpoint continuation evidence changed its binding");
        match &self.frontier {
            NativeContinuationFrontier::Unused(proof) => proof.verify_binding(writer, scope)?,
            NativeContinuationFrontier::Settled(proof) => proof.verify_binding(writer, scope)?,
        }
        Ok(())
    }

    /// Release the writer's exclusive observation before ThreadStore work can
    /// acquire the same writer's ordinary read permit. The original Core task
    /// and run guard remain owned; a changed checkpoint head is rejected next.
    pub(crate) fn release(self) -> (StoredNativeCheckpoint, NativeTurnAnchorV1) {
        let Self { checkpoint, anchor, frontier, .. } = self;
        drop(frontier);
        (checkpoint, anchor)
    }
}

impl AgentdNativeHostedExecutor {
    pub(super) async fn prepare_original_checkpoint_continuation(&self,
        input: HostedCheckpointContinuationInput) -> Result<Option<HostedTurnPlan>> {
        input.origin.validate(&input.observation)?;
        ensure!(input.origin.original_recovery() == &input.observation.recovery,
            "checkpoint continuation changed Core's original recovery");
        ensure!(!input.cancellation.is_cancelled(), "original checkpoint continuation was cancelled");
        let state = self.host.gate.state()?;
        // An arbitrary custom resolver has no original canonical Prepared
        // journal. It retains observation, never an implicit authority fallback.
        if state.native_objective_executor.get().is_none() { return Ok(None); }
        let observation = &input.observation;
        let original_live = input.origin.original_live_thread().clone();
        let provenance = observation.provenance()?;
        let (correlation, original) = self.preparation_binding(observation)?;
        // A durable cancellation/terminal decision disables only fresh
        // continuation. The original request/job observer still runs below Core.
        if !state.native_continuation_allowed(&correlation.run_id)? { return Ok(None); }
        let (record, anchor, saved) = self.host.read_hosted_checkpoint_record(
            &original_live, &original).await?;
        ensure!(anchor.recovery == observation.recovery
            && anchor.queue.as_ref() == Some(&queue_binding(&observation.queue)),
            "checkpoint continuation changed the original Core or Queue identity");
        correlation.verify_checkpoint(&anchor)?;
        // Pending effects and final answers retain original observation. Only
        // a clean next-step cut can become a new live continuation, after the
        // complete original scope and checkpoint chain have been verified.
        if correlation.schema == LEGACY_CORRELATION_SCHEMA
            || saved.pending_model.is_some() || saved.pending_tool.is_some()
            || saved.cancelled || saved.final_answer.is_some() || saved.last_error.is_some() {
            return Ok(None);
        }
        correlation.verify_preparation_config(&self.agent)?;
        let restored = state.load_canonical_prepared(&correlation.run_id)?
            .context("original checkpoint has no durable canonical preparation")?;
        let original_run = anchor.run.as_ref().context("original checkpoint has no dispatched run")?.clone();
        let candidate = restored.attached_run_receipt();
        let scope = self.resolver.preparation_scope()?;
        ensure!(original_run.snapshot == *restored.context().original_run_snapshot()
            && candidate.run_id == correlation.run_id
            && candidate.generation.to_string() == correlation.fleet_generation
            && candidate.context_digest.as_deref() == Some(original_run.context_digest.as_str())
            && candidate.compilation_receipt_digest.as_deref() == Some(original_run.compilation_receipt_digest.as_str())
            && restored.context().rendered_context_digest().to_string() == correlation.rendered_context_sha256
            && self.host.gate.policy_generation.to_string() == correlation.policy_generation
            && scope.cell_id.as_str() == correlation.cell_id
            && scope.organ_id.as_str() == correlation.organ_id
            && scope.final_scope_id.as_str() == correlation.final_scope_id
            && scope.organ_id == scope.final_scope_id,
            "original checkpoint continuation changed its canonical run or execution scope");
        let mut initial = TurnState::new(anchor.turn_binding()?, String::new());
        initial.context = restored.context().context().to_vec();
        let fingerprint = Digest32::of_bytes(&self.agent.model_request_body(&initial)?).to_string();
        ensure!(fingerprint == observation.recovery.fingerprint_sha256,
            "checkpoint continuation changed the original first model request");
        let writer = self.host.host.writer();
        let scope_digest = crate::native_admission::execution_scope_digest(&original, &candidate,
            writer.owner_agent_id(), &scope, codex_hepta_types::Generation::new(correlation.policy_generation.parse()?)?)?;
        let scope_digest = Sha256Digest::parse(scope_digest.to_string()).map_err(anyhow::Error::msg)?;
        let frontier = if record.version.revision == 1 {
            ensure!(record.state.payload == crate::native_turn_checkpoint::encode(&anchor, &initial)?,
                "first checkpoint is not the exact original canonical initial state");
            NativeContinuationFrontier::Unused(writer.observe_unused_scope(&scope_digest).await?)
        } else {
            let (chain, chain_anchor) = self.host.read_hosted_checkpoint_chain(&original_live, &original).await?;
            ensure!(chain.last() == Some(&record) && chain_anchor == anchor,
                "original checkpoint changed while reading its complete chain");
            let admission = self.host.admission_with_policy(original.clone(), scope.clone(),
                codex_hepta_types::Generation::new(correlation.policy_generation.parse()?)?, &candidate)?;
            let fold = NativeCheckpointFold { agent: &self.agent, anchor: &anchor,
                admission: &admission, model: &self.host.model, runtime: &self.host.runtime };
            let states = fold.decode_chain(&chain, &initial)?;
            let tools = fold.observe_tools(&states).await?;
            if saved.queued_tools.is_empty() {
                ensure!(saved.model_calls < self.agent.limits.model_calls, "original model call budget is exhausted");
            } else {
                ensure!(saved.tool_calls < self.agent.limits.tool_calls, "original tool call budget is exhausted");
            }
            // All external observation awaits are above. The same writer's
            // exclusive fence now excludes admitted operations/checkpoints
            // while pure fold validation and same-run rearm consume its proof.
            let terminal = writer.observe_scope_frontier(&scope_digest).await?;
            fold.verify(&chain, &states, &terminal, &tools)?;
            NativeContinuationFrontier::Settled(terminal)
        };
        let evidence = NativeContinuationEvidence {
            original: original_run, checkpoint: record, anchor, scope: scope_digest, frontier,
        };
        // No ThreadStore work or further async owner operation while this
        // exclusive writer proof is held. Core has already flushed its typed
        // successor before invoking this hook.
        let run = state.restore_native_checkpoint_continuation(&input, &restored, &evidence, &writer)?;
        let guard = self.host.retain_checkpoint_continuation(&run)?;
        Ok(Some(HostedTurnPlan {
            request_fingerprint_sha256: fingerprint.clone(),
            correlation: provenance.correlation.clone(),
            execution: Box::new(NativeCheckpointExecution {
                host: self.host.clone(), agent: self.agent.clone(), evidence, run, scope, guard,
                queue: observation.queue.clone(), correlation: provenance.correlation, fingerprint,
            }),
        }))
    }
}

struct NativeCheckpointExecution {
    host: Arc<AgentdNativeHost>,
    agent: Arc<NativeAgent>,
    evidence: NativeContinuationEvidence,
    run: RunReceipt,
    scope: NativeTurnScope,
    guard: NativePreparedGuard,
    queue: HostedQueueBinding,
    correlation: BTreeMap<String, String>,
    fingerprint: String,
}

impl HostedTurnExecution for NativeCheckpointExecution {
    fn run(self: Box<Self>, turn: HostedAdmittedTurn) -> HostedFuture<'static, HostedTurnOutcome> {
        Box::pin(async move {
            let Self { host, agent, evidence, run, scope, guard, queue, correlation, fingerprint } = *self;
            let checked: Result<()> = (|| {
                let anchor = evidence.anchor();
                ensure!(turn.thread_id() == anchor.checkpoint.thread_id
                    && turn.turn_id() == anchor.checkpoint.turn_id
                    && turn.recovery() == &anchor.recovery && turn.queue() == &queue
                    && turn.recovery().fingerprint_sha256 == fingerprint,
                    "Core changed the original checkpoint continuation");
                let provenance = HostedTurnProvenance::from_recovery(turn.recovery())?
                    .context("Core omitted original continuation provenance")?;
                ensure!(provenance.executor_id == EXECUTOR_ID && provenance.queue == queue
                    && provenance.correlation == correlation,
                    "Core changed original checkpoint continuation correlation");
                Ok(())
            })();
            checked.map_err(held)?;
            let prepared = host.resume_hosted_checkpoint(turn.live_thread().clone(), run, scope, evidence, guard)
                .await.map_err(held)?;
            prepared.confirm_durable().await.map_err(held)?;
            // Core revalidates the original persisted Queue tuple. No new
            // dispatch claim, completion transaction or queued input exists.
            turn.confirm_durable().await?;
            let result = host.drive_prepared(&agent, prepared, turn.cancellation(),
                NativeEntryOwner::Core(Arc::clone(turn.entry()))).await.map_err(held)?;
            Ok(hosted_outcome(result.outcome))
        })
    }
}
