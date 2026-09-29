impl AgentdNeuronInvocationV2 {
    pub fn runtime_body_digest(&self) -> Digest32 {
        self.runtime_body_digest
    }

    pub(crate) fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        &self.run_id == run_id && self.input.body_generation == Some(body_generation)
    }

    fn enter_lifecycle_gate(&self) -> Result<RwLockReadGuard<'_, ()>, NeuronRuntimeV2Error> {
        match self.handle.lifecycle_gate.enter(self.lifecycle_epoch) {
            Ok(guard) => Ok(guard),
            Err(error @ NeuronRuntimeV2Error::Admission(_)) => {
                self.handle.owner.record_stale_invocation_rejection();
                Err(error)
            }
            Err(error) => Err(error),
        }
    }

    pub(crate) fn execute(
        &self,
        input: &codex_hepta_intelligence::CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<NeuronRuntimeCommitV2, NeuronRuntimeV2Error> {
        // The read guard is held through the entire owner call. Quiesce first
        // closes and advances the epoch; seal then waits for every invocation
        // admitted by the prior epoch to leave this critical section.
        let _lifecycle_guard = self.enter_lifecycle_gate()?;
        if input.run_id != self.run_id
            || input.objective_digest != self.input.objective_digest
            || input.predecessor_digest != self.input.ndu_snapshot_digest
        {
            self.handle.owner.record_entry_rejection();
            return Err(NeuronRuntimeV2Error::Admission(
                NeuronAdmissionError::BindingMismatch,
            ));
        }
        let mut bound = BoundConfiguration {
            expected_config: self.handle.config_digest,
            inner: guard,
        };
        match &self.context {
            AgentdNeuronInvocationContextV2::Neuron => {
                self.handle.owner.execute(self.input.clone(), &mut bound)
            }
            AgentdNeuronInvocationContextV2::DecisionCell(invocation) => self
                .handle
                .owner
                .execute_decision_cell(invocation, self.input.clone(), &mut bound),
        }
    }
}

struct BoundConfiguration<'a> {
    expected_config: Digest32,
    inner: &'a mut dyn NeuronAdmissionGuard,
}

impl NeuronAdmissionGuard for BoundConfiguration<'_> {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if config.semantic_digest().ok() != Some(self.expected_config) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.inner.check(config, input)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AgentdNeuronOperationalCountersV2 {
    pub owner_busy_rejections: u64,
    pub owner_poisoned_failures: u64,
    pub entry_rejections_before_runtime: u64,
    pub stale_invocation_rejections: u64,
    pub runtime_admission_denials: u64,
    pub recovery_attempts: u64,
    pub recovery_preserve_requests: u64,
    pub recovery_close_requests: u64,
    pub recovery_converged: u64,
    pub recovery_pending: u64,
    pub recovery_errors: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdNeuronCapacityTrendV2 {
    pub elapsed_micros: u64,
    pub generation_records_delta: i64,
    pub generation_effective_bytes_delta: i64,
    pub index_records_delta: i64,
    pub index_effective_bytes_delta: i64,
    pub witness_records_remaining_delta: Option<i64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdNeuronOperationalSnapshotV2 {
    pub generation: Option<u64>,
    pub body_bundle_digest: Option<String>,
    pub pending_tick_id: Option<String>,
    pub pending_input_digest: Option<String>,
    pub pending_operation_code: Option<String>,
    /// Process-local lower bound. It resets when the daemon owner is rebuilt.
    pub oldest_outcome_unknown_age_micros: Option<u64>,
    pub pending_witness_count: usize,
    /// Process-local lower bound. Durable truth is the pending witness count.
    pub pending_witness_age_micros: Option<u64>,
    pub capacity: NeuronRuntimeCapacityV2,
    pub capacity_trend: Option<AgentdNeuronCapacityTrendV2>,
    pub counters: AgentdNeuronOperationalCountersV2,
    pub last_measurement: Option<NeuronRuntimeMeasurementV2>,
}

impl AgentdNeuronOperationalSnapshotV2 {
    /// Advisory host action derived from the durable operation status. This
    /// never creates execution or result-use authority.
    #[must_use]
    pub fn pending_operation_action_code(&self) -> Option<&'static str> {
        self.pending_operation_code
            .as_deref()
            .map(operation_status_action_code)
    }

    /// Advisory capacity action. Payload-specific store/index/witness
    /// admission remains authoritative.
    #[must_use]
    pub fn capacity_action_code(&self) -> &'static str {
        self.capacity.action_code()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdNeuronGenerationControllerSnapshotV2 {
    pub lifecycle: AgentdNeuronLifecycleStateV2,
    pub active_generation: u64,
    pub retained_generations: Vec<u64>,
    pub accepting_new_work: bool,
    pub execution_epoch: u64,
    pub active: AgentdNeuronOperationalSnapshotV2,
}

impl AgentdNeuronGenerationControllerSnapshotV2 {
    /// Advisory lifecycle action for operators. Actual transitions still go
    /// through the controller methods and their durable/fencing checks.
    #[must_use]
    pub fn lifecycle_action_code(&self) -> &'static str {
        match self.lifecycle {
            AgentdNeuronLifecycleStateV2::Starting => "reconcile_and_start",
            AgentdNeuronLifecycleStateV2::Serving if self.accepting_new_work => "serve",
            AgentdNeuronLifecycleStateV2::Serving => "inspect_closed_serving_gate",
            AgentdNeuronLifecycleStateV2::Quiescing => "recover_and_seal",
            AgentdNeuronLifecycleStateV2::Sealed => "reload_or_stop",
            AgentdNeuronLifecycleStateV2::Reloading => "complete_or_recover_handoff",
            AgentdNeuronLifecycleStateV2::Stopped => "stopped",
            AgentdNeuronLifecycleStateV2::Failed => "reconstruct_controller",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AgentdNeuronRecoveryReportV2 {
    pub status_code: String,
    pub action_code: String,
    pub terminal: bool,
    pub requires_reconciliation: bool,
    pub failure_code: Option<String>,
    pub operation_digest: Option<String>,
    pub witness_acknowledged: Option<bool>,
}

impl AgentdNeuronRecoveryReportV2 {
    fn from_status(status: NeuronOperationStatusV2) -> Self {
        let failure_code = match &status {
            NeuronOperationStatusV2::Failed(failure) => Some(failure.stable_code().to_owned()),
            _ => None,
        };
        let (operation_digest, witness_acknowledged) = match &status {
            NeuronOperationStatusV2::Committed {
                commit,
                witness_acknowledged,
            } => (
                Some(commit.operation_digest.to_string()),
                Some(*witness_acknowledged),
            ),
            _ => (None, None),
        };
        Self {
            status_code: status.stable_code().to_owned(),
            action_code: status.action_code().to_owned(),
            terminal: status.is_terminal(),
            requires_reconciliation: status.requires_reconciliation(),
            failure_code,
            operation_digest,
            witness_acknowledged,
        }
    }
}

fn operation_status_action_code(status_code: &str) -> &'static str {
    match status_code {
        "not_recorded" => "admit_original_request",
        "reserved_not_executed" => "resume_or_close_unexecuted",
        "outcome_unknown" => "reconcile_provider",
        "failed" => "return_terminal_failure",
        "committed_witness_pending" => "reconcile_witness",
        "committed_witnessed" => "check_current_use",
        _ => "inspect_operation",
    }
}

#[cfg(test)]
mod operational_action_tests {
    use super::*;

    #[test]
    fn operation_action_codes_are_explicit_and_low_cardinality() {
        assert_eq!(
            operation_status_action_code("reserved_not_executed"),
            "resume_or_close_unexecuted"
        );
        assert_eq!(
            operation_status_action_code("outcome_unknown"),
            "reconcile_provider"
        );
        assert_eq!(
            operation_status_action_code("committed_witness_pending"),
            "reconcile_witness"
        );
        assert_eq!(
            operation_status_action_code("committed_witnessed"),
            "check_current_use"
        );
        assert_eq!(
            operation_status_action_code("unexpected_future_status"),
            "inspect_operation"
        );
    }
}
