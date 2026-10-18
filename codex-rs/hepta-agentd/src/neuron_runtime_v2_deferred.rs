/// The existing host retains a bounded invocation until the canonical neural
/// stage arrives. Capturing this value performs no encoding or model work.
pub(crate) struct AgentdDeferredNeuronInvocationV2 {
    host: Arc<AgentdNeuronRuntimeV2Host>,
    identity: crate::AgentdIdentity,
    record: codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
    invocation: crate::AgentdIntelligenceInvocationV1,
    candidate_set_digest: Digest32,
}

impl AgentdNeuronRuntimeV2Host {
    pub(crate) fn defer(
        self: &Arc<Self>,
        identity: crate::AgentdIdentity,
        record: codex_hepta_agent_components::learning_ledger::RunStartRecordV1,
        invocation: crate::AgentdIntelligenceInvocationV1,
    ) -> Result<AgentdDeferredNeuronInvocationV2, crate::AgentdError> {
        invocation.validate(&identity, &record)?;
        let candidates = codex_hepta_agent_components::intelligence::build_legal_candidates(
            invocation.request.legal_candidates.clone(),
        )
        .map_err(|error| crate::AgentdError::Invalid(format!("neural candidates: {error}")))?;
        Ok(AgentdDeferredNeuronInvocationV2 {
            host: Arc::clone(self),
            identity,
            record,
            invocation,
            candidate_set_digest: candidates.candidate_set_digest,
        })
    }
}

impl AgentdDeferredNeuronInvocationV2 {
    pub(crate) fn runtime_body_digest(&self) -> Digest32 {
        self.record.runtime_body_digest
    }

    pub(crate) fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        &self.invocation.request.run_id == run_id
            && self.invocation.request.snapshot.body_generation().get() == body_generation
    }

    pub(crate) fn execute(
        &self,
        stage: &codex_hepta_agent_components::intelligence::CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        use codex_hepta_agent_components::intelligence::CanonicalStageV1;
        let snapshot = &self.invocation.request.snapshot;
        let denied = || NeuronRuntimeV2Error::Admission(NeuronAdmissionError::BindingMismatch);
        if self.host.stopped.load(Ordering::Acquire)
            || self.host.iteration_quarantine.load(Ordering::Acquire)
        {
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::Revoked,
            ));
        }
        if stage.stage != CanonicalStageV1::NeuralSignalCollected
            || stage.run_id != self.invocation.request.run_id
            || stage.snapshot_digest != snapshot.digest()
            || stage.objective_digest != snapshot.objective_digest()
            || stage.candidate_set_digest != self.candidate_set_digest
            || stage.predecessor_digest.is_zero()
        {
            return Err(denied());
        }
        self.invocation
            .validate(&self.identity, &self.record)
            .map_err(|_| denied())?;
        self.host
            .ensure_goal_scope_v3(&self.identity, &self.record, &self.invocation, stage)?;
        let current =
            self.host.controller.current_tick_anchor().map_err(
                |error| match compatibility_error(error) {
                    NeuronRuntimeV2Error::PendingOperation => {
                        NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable)
                    }
                    error => error,
                },
            )?;
        if current.0 != snapshot.body_generation() {
            return Err(denied());
        }
        let tick = self
            .host
            .tick_provider
            .build_tick_for_stage(
                &self.identity,
                &self.record,
                &self.invocation,
                stage,
                current,
            )
            .map_err(|_| NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable))?;
        let sequence = current.1.map_or(Ok(1), |anchor| {
            anchor
                .sequence
                .checked_add(1)
                .ok_or(NeuronRuntimeV2Error::Arithmetic)
        })?;
        if tick.tick_id != stage.run_id
            || tick.objective_digest != stage.objective_digest
            || tick.ndu_snapshot_digest != stage.predecessor_digest
            || tick.body_generation != Some(current.0.get())
            || tick.logical_sequence != sequence
            || tick.checkpoint_digest
                != current
                    .1
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
        {
            return Err(denied());
        }
        self.host
            .controller
            .prepare(stage.run_id.clone(), self.record.runtime_body_digest, tick)
            .map_err(compatibility_error)?
            .execute(stage, guard)
    }
}
