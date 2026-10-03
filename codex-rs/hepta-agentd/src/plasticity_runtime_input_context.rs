//! Explicit whole input-context refresh in the original serial owner. Root
//! pins immutable material; this seam preserves the original writers/history.
use super::*;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;
use std::path::PathBuf;

pub(crate) struct PlasticityInputContextV2 {
    pub(crate) round: crate::AgentdSelfIterationRoundV1,
    pub(crate) source: (PathBuf, Digest32),
    pub(crate) predecessor: Digest32,
    pub(crate) baseline: StableId,
    pub(crate) baseline_source: Option<(PathBuf, Digest32)>,
    pub(crate) baseline_material:
        Option<codex_hepta_agent_components::neuron::NeuronGenerationMaterialV2>,
    pub(crate) artifacts: ArtifactRegistry,
    pub(crate) current_artifacts: PlasticityCurrentArtifactsV1,
    pub(crate) resolver: Box<dyn PlasticityOwnerEvidenceResolverV1 + Send>,
    pub(crate) policy: PlasticityOwnerEvidencePolicyV1,
    pub(crate) verifier: LearningEvidenceVerifierV1,
}

impl PlasticityRuntimeHandleV1 {
    /// Admit whole Root-protected context while the same original Round owner
    /// retains its command turn. No new model effect may race final admission.
    pub async fn refresh_input_context_v2(
        &self,
        runtime: &crate::AgentdSelfIterationHandleV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        runtime
            .refresh_plasticity_input_context_v2(self.clone(), None, path, pin)
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)
    }
    pub(crate) async fn refresh_input_context_for_round_v2(
        &self,
        runtime: &crate::AgentdSelfIterationHandleV1,
        round: crate::AgentdSelfIterationRoundV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        runtime
            .refresh_plasticity_input_context_v2(self.clone(), Some(round), path, pin)
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)
    }
    pub(crate) fn refresh_while_round_owned(
        &self,
        fence: crate::self_iteration::runtime::plasticity_context::RoundContextFence,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .blocking_send(PlasticityRuntimeCommandV1::RefreshInputContext {
                fence,
                path,
                pin,
                response,
            })
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .blocking_recv()
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
}

pub(crate) fn permits_refresh(
    view: &crate::self_iteration::AgentdSelfIterationCurrentRoundV1,
    round: &crate::AgentdSelfIterationRoundV1,
) -> bool {
    if &view.status.round != round || view.has_pending_model_requests {
        return false;
    }
    view.can_admit_next_round()
        || (!view.status.terminal
            && view.status.candidate_effects
                == crate::AgentdSelfIterationCandidateEffectsV1::NotStarted
            && view.status.generator_request_id.is_none()
            && view.status.generator_output.is_none()
            && view.status.frozen_digest.is_none())
}

impl PlasticityRuntimeOwnerV1 {
    pub(super) fn refresh_input_context_v2(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        fence: crate::self_iteration::runtime::plasticity_context::RoundContextFence,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        let installed = state
            .self_iteration_handle
            .get()
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        if !ready
            || cancellation.is_cancelled()
            || pin.is_zero()
            || !fence.same_owner(installed)
            || !permits_refresh(fence.view(), &fence.view().status.round)
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        let host = state
            .neuron_runtime_v2
            .get()
            .cloned()
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        let context = crate::plasticity_process_bootstrap::load_input_context_v2(
            &path,
            pin,
            state.identity(),
            &self.ledger,
            host,
            now,
        )
        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        if !permits_refresh(fence.view(), &context.round) {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        self.admit_input_context(state, cancellation, generation, context)
    }

    pub(super) fn admit_input_context(
        &mut self,
        state: &AgentdState,
        cancellation: &CancellationToken,
        generation: u64,
        context: PlasticityInputContextV2,
    ) -> Result<(), PlasticityRuntimeCallErrorV1> {
        // Same Round cannot substitute another input packet. Exact repetition
        // remains read-only and rechecks actual CURRENT/lifecycle before return.
        let repeated = self
            .input_context
            .as_ref()
            .is_some_and(|(round, source)| round == &context.round && source == &context.source);
        if self
            .input_context
            .as_ref()
            .is_some_and(|(round, source)| round == &context.round && source != &context.source)
            || !repeated && context.predecessor != self.artifacts.head_digest()
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        if self.parameter_writer.current_anchor().is_err()
            || self.topology_writer.current_anchor().is_err()
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if now < context.round.admitted_at_ms()
            || now >= context.round.deadline_ms()
            || cancellation.is_cancelled()
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let guard = state
            .plasticity_final_admission_guard(generation)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let window = context
            .current_artifacts
            .verify(&context.artifacts, &context.baseline, now)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        // CURRENT inspection may perform protected file I/O. Close the same
        // Round and verified actor windows using a fresh original clock sample.
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if now < context.round.admitted_at_ms() || now >= context.round.deadline_ms() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        window
            .revalidate_at(now)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        if cancellation.is_cancelled() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        if repeated {
            drop(guard);
            return Ok(());
        }
        self.artifacts = context.artifacts;
        self.current_artifacts = Some(context.current_artifacts);
        self.owner_evidence_resolver = context.resolver;
        self.owner_evidence_policy = context.policy;
        self.verifier = context.verifier;
        self.input_context = Some((context.round, context.source));
        drop(guard);
        Ok(())
    }
}
