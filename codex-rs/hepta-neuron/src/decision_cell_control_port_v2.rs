//! Typed dispatch through the existing durable inference-control owner.
//! This adapter owns no model, state, journal or admission capability.

use codex_hepta_infer_core::DecisionCellRequestV1;

use crate::DecisionCellModelExecutionV2;
use crate::DecisionCellModelFailureV2;
use crate::DecisionCellModelPortV2;
use crate::DecisionCellModelResolutionV2;
use crate::DurableInferenceControlModelPort;
use crate::DurableNeuronInferenceControlPort;

impl<P: DurableNeuronInferenceControlPort> DecisionCellModelPortV2
    for DurableInferenceControlModelPort<'_, P>
{
    fn infer(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelExecutionV2, DecisionCellModelFailureV2> {
        self.control.execute_decision_cell(request)
    }

    fn reconcile(
        &mut self,
        request: &DecisionCellRequestV1,
    ) -> Result<DecisionCellModelResolutionV2, DecisionCellModelFailureV2> {
        self.control.reconcile_decision_cell(request)
    }
}
