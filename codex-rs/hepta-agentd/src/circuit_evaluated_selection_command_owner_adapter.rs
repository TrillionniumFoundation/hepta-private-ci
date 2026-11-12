//! Consuming adapter from the existing evaluated Selector to its command host.
//! Source reads use the upstream evaluated read protocol and original T/B.

use super::*;

impl<W: AnchorWitnessStore> OriginalCircuitSelectionReceiptOwnerV1<W> {
    pub(crate) fn original_evaluated_command_context(&self) -> Option<&OriginalCircuitEvaluatedRetentionContextV1> {
        match &self.profile {
            Profile::TrainingNoUpdate => None,
            Profile::Evaluated(context) => Some(context),
        }
    }

    pub fn into_evaluated_command_owner(
        self,
        live: OriginalCircuitLearningReadClientV1,
        trainer: OriginalCellQ24TrainingCommandClientV1,
        evaluator: OriginalCellEvaluationCommandClientV1,
    ) -> Result<crate::OriginalCircuitSelectionCommandOwnerV1<W>, crate::OriginalCircuitSelectionCommandErrorV1>
    where W: Send + 'static,
    {
        crate::OriginalCircuitSelectionCommandOwnerV1::from_original_evaluated_receipt_owner(
            self, live, trainer, evaluator)
    }
}

impl OriginalCircuitEvaluatedSelectionReceiptV1 {
    /// Only a verified response from the original Selector command constructs
    /// this transport continuation. Raw snapshot/signature data are not inputs.
    pub(crate) fn from_original_command_response(
        original: &crate::OriginalCircuitSelectionCommandReceiptV1,
    ) -> Result<Self, Error> {
        let context = original.evaluated_context()
            .ok_or(OwnerError::Binding("original evaluated Selector command receipt"))?;
        let value = Self {
            context: context.clone_for_original_receipt(), snapshot: original.snapshot().clone(),
            receipt: original.receipt().clone(), attestation: original.attestation().clone(),
        };
        value.original_receipt_predecessors(now()?)?;
        Ok(value)
    }
}
