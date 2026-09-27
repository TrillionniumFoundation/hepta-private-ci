//! Concrete selected-artifact checks for the existing Neuron product owner.
//!
//! The host, clock and selector are supplied by native daemon composition, never
//! request bytes. This consumes the existing signed CURRENT owner and does not
//! issue trust, select a model, execute a backend or certify supplied statistics.
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_learning_artifacts::ProvenanceModeV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_neuron::NEURON_CALIBRATION_SUMMARY_SCHEMA_V1;
use codex_hepta_neuron::NEURON_OOD_SUMMARY_SCHEMA_V1;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;

/// Three independent signed selections of immutable bytes in the same CURRENT.
/// Calibration/OOD artifact generations are their own revisions; their payloads
/// bind the runtime generation and complete execution profile separately.
#[derive(Clone)]
pub struct NeuronSelectedArtifactsV1 {
    pub model: SignedArtifactSelectionV1,
    pub calibration: SignedArtifactSelectionV1,
    pub ood: SignedArtifactSelectionV1,
}

pub struct AgentdNeuronArtifactAdmissionV1 {
    owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    selector: ArtifactSelectionVerifierV1,
    selections: NeuronSelectedArtifactsV1,
    clock: Arc<dyn AuthorityClock>,
    configuration: Digest32,
    last_time: u64,
    manifest_expiries: [u64; 3],
    closed: bool,
}

impl AgentdNeuronArtifactAdmissionV1 {
    /// Resolve all three real payloads once under the artifact owner's lock.
    /// The independently selected model manifest must describe this exact
    /// weights/runtime/device/normalization profile. No digest-only substitute
    /// for a missing payload or an unregistered V2 manifest is accepted.
    pub fn new(
        owner: Arc<Mutex<LearningArtifactOwnerHost>>,
        selector: ArtifactSelectionVerifierV1,
        selections: NeuronSelectedArtifactsV1,
        clock: Arc<dyn AuthorityClock>,
        config: &NeuronRuntimeConfigV1,
    ) -> Result<Self, NeuronAdmissionError> {
        let configuration = config
            .semantic_digest()
            .map_err(|_| NeuronAdmissionError::BindingMismatch)?;
        let mut result = Self {
            owner,
            selector,
            selections,
            clock,
            configuration,
            last_time: 0,
            manifest_expiries: [0; 3],
            closed: false,
        };
        result.validate_current(config, PayloadCheck::Required)?;
        Ok(result)
    }

    fn validate_current(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        payload_check: PayloadCheck,
    ) -> Result<(), NeuronAdmissionError> {
        if self.closed || config.semantic_digest().ok() != Some(self.configuration) {
            self.closed = true;
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        // Any failed refresh closes this installed consumer. Explicit owner
        // reconstruction with current selections is required to resume; an old
        // file snapshot or rewound wall clock cannot revive this handle.
        self.closed = true;
        let now = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        if now < self.last_time {
            return Err(NeuronAdmissionError::Revoked);
        }
        let owner = self
            .owner
            .try_lock()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        let current = owner
            .current_registry_view(now)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        let profile = config
            .execution_profile_digest_v1()
            .map_err(|_| NeuronAdmissionError::BindingMismatch)?;
        let calibration = config
            .calibration_evidence_payload_v1()
            .map_err(|_| NeuronAdmissionError::BindingMismatch)?;
        let ood = config
            .ood_evidence_payload_v1()
            .map_err(|_| NeuronAdmissionError::BindingMismatch)?;
        if Digest32::of_bytes(&calibration) != config.calibration.calibration_artifact_digest
            || Digest32::of_bytes(&ood) != config.calibration.ood_artifact_digest
            || self.selections.model.artifact_id == self.selections.calibration.artifact_id
            || self.selections.model.artifact_id == self.selections.ood.artifact_id
            || self.selections.calibration.artifact_id == self.selections.ood.artifact_id
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        let records = [
            (
                &self.selections.model,
                ArtifactKind::Model,
                config.weights_digest,
                None,
            ),
            (
                &self.selections.calibration,
                ArtifactKind::Policy,
                config.calibration.calibration_artifact_digest,
                Some(calibration.as_slice()),
            ),
            (
                &self.selections.ood,
                ArtifactKind::Policy,
                config.calibration.ood_artifact_digest,
                Some(ood.as_slice()),
            ),
        ];
        for (index, (selection, kind, content, expected_payload)) in records.into_iter().enumerate()
        {
            let verified = self
                .selector
                .verify(selection, &current, now)
                .map_err(|_| NeuronAdmissionError::Revoked)?;
            if matches!(payload_check, PayloadCheck::AlreadyLoaded) {
                // Selection verification binds the exact immutable support hash
                // checked at load. Reuse that metadata, but not a CURRENT view.
                if now > self.manifest_expiries[index] {
                    return Err(NeuronAdmissionError::Revoked);
                }
                continue;
            }
            let admitted = owner
                .read_current_selected_manifest(&self.selector, selection, now)
                .map_err(|_| NeuronAdmissionError::Revoked)?;
            let manifest = &admitted.manifest;
            if verified.manifest().kind != kind
                || manifest.bytes_digest != content
                || manifest.runtime_tuple_digest != profile
                || manifest.device_profile_digest != config.device_digest
                || manifest.normalization_digest != config.normalization_digest
                || manifest.objective_class_digest != self.selections.model.objective_digest
            {
                return Err(NeuronAdmissionError::BindingMismatch);
            }
            if expected_payload.is_none()
                && (admitted.manifest_digest != config.model_manifest_digest
                    || manifest.generation != config.generation
                    || !manifest
                        .lineage_digests
                        .contains(&self.selections.calibration.support_digest)
                    || !manifest
                        .lineage_digests
                        .contains(&self.selections.ood.support_digest))
            {
                return Err(NeuronAdmissionError::BindingMismatch);
            }
            if let Some(payload) = expected_payload {
                let schema = if selection.artifact_id == self.selections.calibration.artifact_id {
                    NEURON_CALIBRATION_SUMMARY_SCHEMA_V1
                } else {
                    NEURON_OOD_SUMMARY_SCHEMA_V1
                };
                if manifest.schema_profile_digest != Digest32::of_bytes(schema.as_bytes())
                    || manifest.provenance_mode != ProvenanceModeV1::DatasetDerived
                    || manifest.encoded_size_bytes != payload.len() as u64
                {
                    return Err(NeuronAdmissionError::BindingMismatch);
                }
            }
            // A matching independently selected content digest authenticates all
            // summary fields, not merely an arbitrary "calibration present" tag.
            let (_, bytes) = owner
                .read_current_selected_payload(&self.selector, selection, now)
                .map_err(|_| NeuronAdmissionError::Revoked)?;
            if expected_payload.is_some_and(|expected| expected != bytes) {
                return Err(NeuronAdmissionError::BindingMismatch);
            }
            self.manifest_expiries[index] = manifest.expires_at;
        }
        // File reads may consume time. Check lifetimes again at the final
        // observation while retaining the same publication lock.
        let finished = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        if finished < now
            || self
                .manifest_expiries
                .iter()
                .any(|expiry| finished > *expiry)
        {
            return Err(NeuronAdmissionError::Revoked);
        }
        let final_current = owner
            .current_registry_view(finished)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        if final_current.receipt() != current.receipt()
            || final_current.witness_digest() != current.witness_digest()
            || final_current.trust_digest() != current.trust_digest()
        {
            return Err(NeuronAdmissionError::Revoked);
        }
        for selection in [
            &self.selections.model,
            &self.selections.calibration,
            &self.selections.ood,
        ] {
            self.selector
                .verify(selection, &final_current, finished)
                .map_err(|_| NeuronAdmissionError::Revoked)?;
        }
        self.last_time = finished;
        self.closed = false;
        Ok(())
    }
}

enum PayloadCheck {
    Required,
    AlreadyLoaded,
}

impl NeuronAdmissionGuard for AgentdNeuronArtifactAdmissionV1 {
    fn check(
        &mut self,
        config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if input.objective_digest != self.selections.model.objective_digest
            || input.logical_sequence < config.calibration.valid_from_sequence
            || input.logical_sequence > config.calibration.expires_after_sequence
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.validate_current(config, PayloadCheck::AlreadyLoaded)
    }
}

impl<W, P> crate::AgentdNeuronOwner<W, P>
where
    W: codex_hepta_neuron::AnchorWitnessStore + Send + 'static,
    P: codex_hepta_neuron::NeuronInferenceControlPort + Send + 'static,
{
    /// Compose this actual durable owner with the current selected-artifact
    /// guard, rather than requiring a caller to invent a permissive guard.
    /// The existing inference owner still supplies the concrete feature port.
    pub fn into_selected_shared(
        self,
        artifacts: Arc<Mutex<LearningArtifactOwnerHost>>,
        selector: ArtifactSelectionVerifierV1,
        selections: NeuronSelectedArtifactsV1,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<crate::AgentdNeuronHandleV1, codex_hepta_neuron::NeuronRuntimeError> {
        let admission = AgentdNeuronArtifactAdmissionV1::new(
            artifacts,
            selector,
            selections,
            clock,
            self.runtime().configuration(),
        )
        .map_err(codex_hepta_neuron::NeuronRuntimeError::Admission)?;
        self.into_shared(admission)
    }
}
