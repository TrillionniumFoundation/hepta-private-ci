//! Typed invocations use the existing Agentd owner, canonical runner and epoch.
//! These entry points do not select a backend, grant effects or migrate state.
use super::*;

pub(super) fn runtime_error(error: DecisionCellRuntimeV2Error) -> NeuronRuntimeV2Error {
    match error {
        DecisionCellRuntimeV2Error::Runtime(error) => error,
        DecisionCellRuntimeV2Error::Contract(_) | DecisionCellRuntimeV2Error::Binding(_) => {
            NeuronRuntimeV2Error::Admission(NeuronAdmissionError::BindingMismatch)
        }
    }
}

impl AgentdNeuronHandleV2 {
    /// Prepare a complete typed request for the same canonical product runner.
    /// Full runtime binding is revalidated before reservation; preparation itself
    /// grants neither model execution nor permission to use an existing result.
    pub fn prepare_decision_cell(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
        cell: DecisionCellInvocationV2,
    ) -> Result<AgentdNeuronInvocationV2, NeuronRuntimeV2Error> {
        let mut invocation = self.prepare(run_id, runtime_body_digest, input)?;
        invocation.context = AgentdNeuronInvocationContextV2::DecisionCell(Box::new(cell));
        Ok(invocation)
    }

    /// Read exact typed operation truth without dispatch or result-use authority.
    pub fn query_decision_cell_operation(
        &self,
        cell: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, NeuronRuntimeV2Error> {
        self.owner.query_decision_cell_operation(cell, input)
    }

    /// Release the immutable typed result only under both installed artifact
    /// admission and the caller's current-use guard. No provider work occurs.
    pub fn query_decision_cell_result_guarded(
        &self,
        cell: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, NeuronRuntimeV2Error> {
        self.owner
            .query_decision_cell_result_guarded(cell, input, guard)
    }

    /// Serving/startup-safe reconciliation, preserving proven-unexecuted work.
    pub fn recover_decision_cell_operation(
        &self,
        cell: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        self.owner
            .recover_decision_cell_control(
                cell,
                input,
                AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted,
            )
            .map(AgentdNeuronRecoveryReportV2::from_status)
    }
}

impl AgentdNeuronGenerationControllerV2 {
    /// The returned invocation is accepted by the existing durable-neuron V2
    /// product runner; it holds the same execution epoch as an ordinary tick.
    pub fn prepare_decision_cell(
        &self,
        run_id: StableId,
        runtime_body_digest: Digest32,
        input: NeuronTickInputV1,
        cell: DecisionCellInvocationV2,
    ) -> Result<AgentdNeuronInvocationV2, AgentdNeuronControlErrorV2> {
        let mut invocation = self.prepare(run_id, runtime_body_digest, input)?;
        invocation.context = AgentdNeuronInvocationContextV2::DecisionCell(Box::new(cell));
        Ok(invocation)
    }

    /// Query-only recovery of the exact typed operation. Starting/Serving
    /// preserve unexecuted work; Quiescing may close only proven-unexecuted work.
    pub fn recover_existing_decision_cell_operation(
        &self,
        cell: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        let state = self.lock_state()?;
        let policy = match state.lifecycle {
            AgentdNeuronLifecycleStateV2::Starting | AgentdNeuronLifecycleStateV2::Serving => {
                AgentdNeuronRecoveryPolicyV2::PreserveUnexecuted
            }
            AgentdNeuronLifecycleStateV2::Quiescing => {
                AgentdNeuronRecoveryPolicyV2::CloseUnexecuted
            }
            AgentdNeuronLifecycleStateV2::Sealed
            | AgentdNeuronLifecycleStateV2::Reloading
            | AgentdNeuronLifecycleStateV2::Stopped
            | AgentdNeuronLifecycleStateV2::Failed => {
                return Err(AgentdNeuronControlErrorV2::InvalidTransition);
            }
        };
        state
            .active
            .owner
            .recover_decision_cell_control(cell, input, policy)
            .map(AgentdNeuronRecoveryReportV2::from_status)
    }

    /// Explicit administrative closure is available only with admission fenced
    /// in Starting/Quiescing. Unknown provider state still blocks start/seal.
    pub fn close_unexecuted_decision_cell_operation(
        &self,
        cell: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<AgentdNeuronRecoveryReportV2, AgentdNeuronControlErrorV2> {
        let state = self.lock_state()?;
        if !matches!(
            state.lifecycle,
            AgentdNeuronLifecycleStateV2::Starting | AgentdNeuronLifecycleStateV2::Quiescing
        ) {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        // Hold the lifecycle lock until closure finishes, so startup cannot
        // open admission between authorization and the serialized owner call.
        state
            .active
            .owner
            .recover_decision_cell_control(
                cell,
                input,
                AgentdNeuronRecoveryPolicyV2::CloseUnexecuted,
            )
            .map(AgentdNeuronRecoveryReportV2::from_status)
    }
}
