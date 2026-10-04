//! Explicit dataset/frozen-Neuron purpose blocks in the original descriptor.
use super::*;
use crate::PlasticityDatasetWindowEvidenceV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowFreezePlanWireV3;
use codex_hepta_agent_components::learning_ledger::DatasetWindowSnapshotWireV3;
use codex_hepta_agent_components::learning_ledger::LedgerSnapshot;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DatasetWindowDescriptorV3 {
    pub(super) plan: DatasetWindowFreezePlanWireV3,
    pub(super) window: DatasetWindowSnapshotWireV3,
    pub(super) evaluator: ReviewEvidenceWireV1,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FrozenNeuronDescriptorV3 {
    pub(super) checkpoint_response: ContextSource,
    pub(super) goal_material: ContextSource,
}
impl DatasetWindowDescriptorV3 {
    pub(super) fn evidence(
        &self,
        dataset: &DatasetSnapshotReceiptV3,
        current: &LedgerSnapshot,
        verifier: LearningEvidenceVerifierV1,
        now: u64,
    ) -> Result<PlasticityDatasetWindowEvidenceV3, AgentdError> {
        let decode = |e| AgentdError::Invalid(format!("whole dataset Window: {e}"));
        let evidence = PlasticityDatasetWindowEvidenceV3 {
            plan: self.plan.native().map_err(decode)?,
            window: self.window.native().map_err(decode)?,
            evaluator: self.evaluator.native().map_err(decode)?,
            verifier,
        };
        if &evidence.window.receipt != dataset {
            return invalid("context dataset differs from complete signed Window");
        }
        evidence
            .validate_current(current, now)
            .map_err(|e| AgentdError::Invalid(e.to_string()))?;
        Ok(evidence)
    }
}
