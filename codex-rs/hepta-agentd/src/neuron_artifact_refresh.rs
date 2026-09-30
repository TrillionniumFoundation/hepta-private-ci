//! A bounded authenticated ingress for independently reissued selections.
//! No issuer key or selection policy exists in the consuming model owner.
use super::*;

#[derive(Clone)]
pub struct AgentdNeuronSelectionRefreshIngressV1 {
    owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    artifact_root: PathBuf,
    selector: ArtifactSelectionVerifierV1,
    clock: Arc<dyn AuthorityClock>,
    configuration: NeuronRuntimeConfigV1,
    original: NeuronSelectedArtifactsV1,
    minimum_time: u64,
    pending: Arc<Mutex<Option<NeuronSelectedArtifactsV1>>>,
}

impl AgentdNeuronSelectionRefreshIngressV1 {
    /// Authenticate an exact externally signed refresh against actual CURRENT
    /// and original payloads before occupying the single pending slot. The
    /// returned digest identifies a pending input, never a durable selection,
    /// activation or proof that the physical runtime has consumed it.
    pub fn submit_current_selections(
        &self,
        selections: NeuronSelectedArtifactsV1,
    ) -> Result<Digest32, NeuronAdmissionError> {
        validate_same_artifacts(&self.original, &selections)?;
        let current = AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&self.owner),
            &self.artifact_root,
            self.selector.clone(),
            selections,
            Arc::clone(&self.clock),
            &self.configuration,
        )?;
        if current.last_time < self.minimum_time {
            return Err(NeuronAdmissionError::Revoked);
        }
        let digest = refresh_digest(&current.selections);
        let mut pending = self
            .pending
            .try_lock()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        match pending.as_ref() {
            Some(original) if original != &current.selections => {
                Err(NeuronAdmissionError::Unavailable)
            }
            Some(_) => Ok(digest),
            None => {
                *pending = Some(current.selections);
                Ok(digest)
            }
        }
    }
}

impl AgentdNeuronArtifactAdmissionV1 {
    /// Give only the installed authenticated Selector transport this ingress.
    /// It carries public trust and original tuple pins, never signing material.
    pub fn selection_refresh_ingress(&self) -> AgentdNeuronSelectionRefreshIngressV1 {
        AgentdNeuronSelectionRefreshIngressV1 {
            owner: Arc::clone(&self.owner),
            artifact_root: self.artifact_root.clone(),
            selector: self.selector.clone(),
            clock: Arc::clone(&self.clock),
            configuration: self.runtime_configuration.clone(),
            original: self.selections.clone(),
            minimum_time: self.last_time,
            pending: Arc::clone(&self.pending_refresh),
        }
    }

    pub(super) fn consume_selection_refresh(
        &mut self,
        config: &NeuronRuntimeConfigV1,
    ) -> Result<bool, NeuronAdmissionError> {
        let pending = self
            .pending_refresh
            .try_lock()
            .map_err(|_| NeuronAdmissionError::Unavailable)?
            .take();
        let Some(selections) = pending else {
            return Ok(false);
        };
        // Reconstruct the admission gate from freshly verified original
        // payloads. A closed old gate never reopens from a registry extension
        // or a previously valid signature. CURRENT may change after submit.
        let reconstructed = (|| {
            validate_same_artifacts(&self.selections, &selections)?;
            let next = Self::new(
                Arc::clone(&self.owner),
                &self.artifact_root,
                self.selector.clone(),
                selections,
                Arc::clone(&self.clock),
                config,
            )?;
            if next.last_time < self.last_time {
                return Err(NeuronAdmissionError::Revoked);
            }
            Ok(next)
        })();
        match reconstructed {
            Ok(next) => {
                self.selections = next.selections;
                self.selection_expiries = next.selection_expiries;
                self.last_time = next.last_time;
                self.closed = false;
                Ok(true)
            }
            Err(error) => {
                self.closed = true;
                Err(error)
            }
        }
    }
}

fn validate_same_artifacts(
    previous: &NeuronSelectedArtifactsV1,
    next: &NeuronSelectedArtifactsV1,
) -> Result<(), NeuronAdmissionError> {
    if previous.model_artifact_manifest != next.model_artifact_manifest
        || previous.calibration_lineage_digest != next.calibration_lineage_digest
        || previous.ood_lineage_digest != next.ood_lineage_digest
    {
        return Err(NeuronAdmissionError::BindingMismatch);
    }
    for (original, refreshed) in [
        (&previous.model, &next.model),
        (&previous.calibration, &next.calibration),
        (&previous.ood, &next.ood),
    ] {
        if original.artifact_id != refreshed.artifact_id
            || original.registry_id != refreshed.registry_id
            || original.withdrawal_scope_digest != refreshed.withdrawal_scope_digest
            || original.artifact_kind != refreshed.artifact_kind
            || original.artifact_generation != refreshed.artifact_generation
            || original.predecessor_id != refreshed.predecessor_id
            || original.content_digest != refreshed.content_digest
            || original.objective_digest != refreshed.objective_digest
            || original.support_digest != refreshed.support_digest
            || original.compatibility_digest != refreshed.compatibility_digest
            || original.encoded_size_bytes != refreshed.encoded_size_bytes
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
    }
    Ok(())
}

fn refresh_digest(selections: &NeuronSelectedArtifactsV1) -> Digest32 {
    let mut bytes = b"hepta.neuron.authenticated-selection-refresh.v1\0".to_vec();
    for selection in [&selections.model, &selections.calibration, &selections.ood] {
        bytes.extend_from_slice(&selection.signing_bytes());
        bytes.extend_from_slice(&selection.signature);
    }
    bytes.extend_from_slice(selections.calibration_lineage_digest.as_array());
    bytes.extend_from_slice(selections.ood_lineage_digest.as_array());
    Digest32::of_bytes(&bytes)
}

