//! Finish only the original Core turn's interrupted preparation. Its original
//! production operation ledger must prove the complete scope was never used.

use codex_core::hosted_turn::HostedPreparationRecoveryInput;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Generation;

use super::*;

/// Derive the expected scope from Core's private retained origin, not from
/// a caller-supplied scope string or a separately deserialized recovery DTO.
pub(crate) fn retained_preparation_scope(
    input: &HostedTurnInput,
    restored: &crate::intelligence_product::RestoredCanonicalPreparationV1,
    writer: &codex_hepta_memory::ProductionDurableWriter,
) -> Result<Sha256Digest> {
    input
        .origin
        .validate(input.thread_id, &input.turn_id, &input.queue)?;
    let recovery = input.origin.retained_recovery()?;
    let provenance = HostedTurnProvenance::from_recovery(recovery)?
        .context("original retained provenance missing")?;
    ensure!(
        recovery.turn_id == input.turn_id
            && provenance.executor_id == EXECUTOR_ID
            && provenance.queue == input.queue,
        "original Core retained identity changed"
    );
    let correlation: NativeHostedCorrelationV1 =
        serde_json::from_value(serde_json::to_value(provenance.correlation)?)?;
    correlation.validate_schema()?;
    let run = restored.attached_run_receipt();
    ensure!(
        correlation.schema == CORRELATION_SCHEMA
            && correlation.agent_id == writer.owner_agent_id().as_str()
            && correlation.lease_id == writer.lease_id()
            && correlation.thread_id == input.thread_id.to_string()
            && correlation.turn_id == input.turn_id
            && correlation.run_id == run.run_id
            && correlation.fleet_generation == run.generation.to_string()
            && run.context_digest.as_deref() == Some(correlation.context_receipt_sha256.as_str())
            && run.compilation_receipt_digest.as_deref()
                == Some(correlation.compilation_receipt_sha256.as_str())
            && correlation.rendered_context_sha256
                == restored.context().rendered_context_digest().to_string(),
        "original retained scope changed its compiled run or writer"
    );
    let original = NativeCheckpointBinding {
        thread_id: input.thread_id,
        turn_id: input.turn_id.clone(),
        operation_id: run.run_id.clone(),
        generation: run.generation,
        lease_id: correlation.lease_id,
    };
    let scope = NativeTurnScope {
        cell_id: codex_hepta_types::StableId::new(correlation.cell_id)?,
        organ_id: codex_hepta_types::StableId::new(correlation.organ_id)?,
        final_scope_id: codex_hepta_types::StableId::new(correlation.final_scope_id)?,
    };
    ensure!(
        scope.organ_id == scope.final_scope_id,
        "retained native scope differs from its original organ"
    );
    let digest = crate::native_admission::execution_scope_digest(
        &original,
        &run,
        writer.owner_agent_id(),
        &scope,
        Generation::new(correlation.policy_generation.parse()?)?,
    )?;
    Sha256Digest::parse(digest.to_string()).map_err(anyhow::Error::msg)
}

impl AgentdNativeHostedExecutor {
    pub(super) fn preparation_binding(
        &self,
        observation: &HostedTurnObservation,
    ) -> Result<(NativeHostedCorrelationV1, NativeCheckpointBinding)> {
        let provenance = observation.provenance()?;
        ensure!(
            provenance.executor_id == EXECUTOR_ID,
            "original preparation belongs to another executor"
        );
        let correlation: NativeHostedCorrelationV1 =
            serde_json::from_value(serde_json::to_value(provenance.correlation)?)?;
        let writer = self.host.host.writer();
        ensure!(
            correlation.agent_id == writer.owner_agent_id().as_str()
                && correlation.lease_id == writer.lease_id(),
            "original preparation changed its production writer"
        );
        let original = correlation.checkpoint(observation)?;
        Ok((correlation, original))
    }

    pub(super) async fn resume_original_preparation(
        &self,
        request: HostedPreparationRecoveryInput,
    ) -> Result<HostedTurnPlan> {
        let HostedPreparationRecoveryInput { input, recovery } = request;
        input
            .origin
            .validate(input.thread_id, &input.turn_id, &input.queue)?;
        input.origin.require_retained()?;
        ensure!(
            input.origin.retained_recovery()? == &recovery,
            "caller changed the Core-owned original recovery"
        );
        ensure!(
            !input.cancellation.is_cancelled(),
            "original preparation was cancelled"
        );
        ensure!(
            user_input_payload_sha256(&input.input)? == input.queue.payload_sha256,
            "retained input differs from its original Queue payload"
        );
        let observation = HostedTurnObservation {
            live_thread: input.live_thread.clone(),
            thread_id: input.thread_id,
            turn_id: input.turn_id.clone(),
            queue: input.queue.clone(),
            recovery: recovery.clone(),
        };
        let (correlation, original) = self.preparation_binding(&observation)?;
        // Gate before any writer proof or coordinator mutation. Observing an
        // existing effect does not use this fresh-preparation config check.
        correlation.verify_preparation_config(&self.agent)?;
        ensure!(
            !self
                .host
                .has_hosted_checkpoint(&input.live_thread, &original)
                .await?,
            "an original checkpoint already exists; use its observation route"
        );
        let state = self.host.gate.state()?;
        let restored = state
            .load_canonical_prepared(&correlation.run_id)?
            .context("original complete canonical preparation is not durable")?;
        let candidate = restored.attached_run_receipt();
        let scope = self.resolver.preparation_scope()?;
        ensure!(
            candidate.run_id == correlation.run_id
                && candidate.generation.to_string() == correlation.fleet_generation
                && candidate.context_digest.as_deref()
                    == Some(correlation.context_receipt_sha256.as_str())
                && candidate.compilation_receipt_digest.as_deref()
                    == Some(correlation.compilation_receipt_sha256.as_str())
                && restored.context().rendered_context_digest().to_string()
                    == correlation.rendered_context_sha256
                && self.host.gate.policy_generation.to_string() == correlation.policy_generation
                && scope.cell_id.as_str() == correlation.cell_id
                && scope.organ_id.as_str() == correlation.organ_id
                && scope.final_scope_id.as_str() == correlation.final_scope_id,
            "retained preparation changed its original run, compiled context or configured scope"
        );
        let writer = self.host.host.writer();
        let scope_digest = retained_preparation_scope(&input, &restored, &writer)?;
        // This reads the original immutable operation ledger under its actual
        // live lease. Any queued, entered or terminal operation rejects repair.
        // Core's exclusive turn reservation and the Queue's OS process lock
        // exclude another preparation while this read-side fact is consumed.
        let unused = writer.observe_unused_scope(&scope_digest).await?;
        let run =
            state.restore_native_preparation(&input, &restored, &unused, &writer, &scope_digest)?;
        let preparation = match run.phase {
            RunPhase::ContextAttached => NativeHostedPreparation::RecoveredInitial(unused),
            RunPhase::Dispatched => NativeHostedPreparation::Retained(unused),
            _ => anyhow::bail!("original owner did not retain an unentered preparation"),
        };
        let plan = self
            .plan_from_resolution(
                input,
                NativeHostedResolution {
                    run,
                    scope,
                    context: restored.context().clone(),
                },
                preparation,
            )
            .await?;
        let provenance = observation.provenance()?;
        ensure!(
            plan.request_fingerprint_sha256 == recovery.fingerprint_sha256
                && plan.correlation == provenance.correlation,
            "original prepared model request or provenance changed during repair"
        );
        Ok(plan)
    }
}
