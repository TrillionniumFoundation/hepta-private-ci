//! Typed lifecycle facades over the existing V2 operation owner.
//! No new reservation, dispatch, journal, result writer or authority is added.

use super::*;
use crate::NeuronOperationStatusV2;

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Reconcile the exact typed operation without new-work admission or result use.
    /// The provider may observe prior work, but this path never calls `infer`.
    /// Proven-unexecuted work remains available for a later guarded invocation.
    pub fn recover_decision_cell_operation(
        &mut self,
        model: &mut impl DecisionCellModelPortV2,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, DecisionCellRuntimeV2Error> {
        let (config, body, body_digest) = self.decision_cell_context();
        let mut adapter =
            DecisionCellNeuronAdapterV2::new(model, invocation, config, body, body_digest, input)?;
        let input_digest = decision_cell_input_digest_v2(invocation, input)?;
        self.recover_operation_with_input_digest(&mut adapter, input, input_digest)
            .map_err(DecisionCellRuntimeV2Error::Runtime)
    }

    /// Quiesce-only closure of typed work proven not to have executed.
    /// The caller owns lifecycle authorization. Unknown outcomes remain pending;
    /// observed results are durably committed, never rewritten as denied work.
    pub fn close_unexecuted_decision_cell_operation(
        &mut self,
        model: &mut impl DecisionCellModelPortV2,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronOperationStatusV2, DecisionCellRuntimeV2Error> {
        let (config, body, body_digest) = self.decision_cell_context();
        let mut adapter =
            DecisionCellNeuronAdapterV2::new(model, invocation, config, body, body_digest, input)?;
        let input_digest = decision_cell_input_digest_v2(invocation, input)?;
        self.close_unexecuted_operation_with_input_digest(&mut adapter, input, input_digest)
            .map_err(DecisionCellRuntimeV2Error::Runtime)
    }

    /// Release immutable typed result bytes only after a current-use guard check.
    /// This has no model port and neither invokes nor reconciles provider work.
    /// Administrative truth remains available through `query_decision_cell_operation`.
    pub fn query_decision_cell_result_guarded(
        &mut self,
        invocation: &DecisionCellInvocationV2,
        input: &NeuronTickInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<Option<NeuronRuntimeCommitV2>, DecisionCellRuntimeV2Error> {
        let (config, body, body_digest) = self.decision_cell_context();
        invocation.validate(config, body, body_digest, input)?;
        let input_digest = decision_cell_input_digest_v2(invocation, input)?;
        self.query_result_with_input_digest_guarded(input, input_digest, guard)
            .map_err(DecisionCellRuntimeV2Error::Runtime)
    }
}
