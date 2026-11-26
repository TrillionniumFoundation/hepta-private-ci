use super::*;
use codex_hepta_agent_components::neuron::JournalScope;

/// Read eligibility from the original acknowledged owner while proving that
/// the retained anchor belongs to that same current generation history.
/// Implementations must not reconcile, dispatch, synthesize eligibility or
/// substitute an older operation for the current checkpoint.
pub trait PlasticityNeuronEligibilityReaderV1: Send + Sync {
    fn read(
        &self,
        required_anchor: JournalAnchor,
    ) -> Result<SparseCheckpoint, PlasticityOwnerEvidenceErrorV1>;
}

pub(super) struct SparseJournalEligibilityReaderV1 {
    pub(super) journal: Arc<Mutex<SparseJournal>>,
}
impl PlasticityNeuronEligibilityReaderV1 for SparseJournalEligibilityReaderV1 {
    fn read(
        &self,
        required_anchor: JournalAnchor,
    ) -> Result<SparseCheckpoint, PlasticityOwnerEvidenceErrorV1> {
        let journal = self
            .journal
            .lock()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?;
        if !journal
            .contains_anchor(required_anchor)
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
        {
            return Err(PlasticityOwnerEvidenceErrorV1::ContextMismatch);
        }
        journal
            .current()
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
            .cloned()
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)
    }
}

/// Current V2 eligibility reuses the already held runtime/controller. It owns
/// no store or worker and its exact identity remains pinned across reloads.
pub struct PlasticityNeuronEligibilityReaderV2 {
    host: Arc<crate::AgentdNeuronRuntimeV2Host>,
    generation: crate::neuron_runtime_v2::AgentdNeuronGenerationIdV2,
    configuration: Digest32,
    body: Digest32,
    scope: JournalScope,
}
impl PlasticityNeuronEligibilityReaderV2 {
    pub fn new(
        host: Arc<crate::AgentdNeuronRuntimeV2Host>,
        generation: crate::neuron_runtime_v2::AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: JournalScope,
    ) -> Result<Self, PlasticityOwnerEvidenceErrorV1> {
        if configuration.is_zero()
            || body.is_zero()
            || scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
        {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }
        Ok(Self {
            host,
            generation,
            configuration,
            body,
            scope,
        })
    }
}
impl PlasticityNeuronEligibilityReaderV1 for PlasticityNeuronEligibilityReaderV2 {
    fn read(
        &self,
        required_anchor: JournalAnchor,
    ) -> Result<SparseCheckpoint, PlasticityOwnerEvidenceErrorV1> {
        if required_anchor.sequence == 0 || required_anchor.checkpoint_digest.is_zero() {
            return Err(PlasticityOwnerEvidenceErrorV1::InvalidReceipt);
        }
        let checkpoint = self
            .host
            .current_sparse_checkpoint_v2(
                self.generation,
                self.configuration,
                self.body,
                self.scope,
                required_anchor,
            )
            .map_err(|_| PlasticityOwnerEvidenceErrorV1::Unavailable)?
            .ok_or(PlasticityOwnerEvidenceErrorV1::Missing)?;
        // The held original V2 owner has verified the exact retained anchor
        // in its acknowledged history, as well as the whole current frontier.
        Ok(checkpoint)
    }
}
