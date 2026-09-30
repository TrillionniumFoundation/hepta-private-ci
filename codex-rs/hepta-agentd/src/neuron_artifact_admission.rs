//! Authenticated selected-artifact admission for the Agentd Neuron owner.
//!
//! The selector, CURRENT owner, filesystem root and clock are host-owned inputs.
//! Request bytes cannot choose artifacts, roots, trust, or freshness.  V1
//! registry fields are used deliberately: model support binds the model manifest,
//! calibration/OOD content binds the exact registered evidence payload, their
//! support fields bind host-pinned independent lineage, and compatibility binds
//! the complete frozen Neuron execution profile.

use std::fs;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agent_components::contracts::AuthorityClock;
use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
use codex_hepta_agent_components::learning_artifacts::ArtifactManifest;
use codex_hepta_agent_components::learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_agent_components::learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_agent_components::learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_agent_components::learning_artifacts::load_selected_candidate;
use codex_hepta_agent_components::neuron::NeuronAdmissionError;
use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronRuntimeConfigV1;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::types::Digest32;

/// Three independently signed immutable selections from one authenticated
/// CURRENT, plus the lineage digests pinned by daemon bootstrap configuration.
#[derive(Clone)]
pub struct NeuronSelectedArtifactsV1 {
    pub model: SignedArtifactSelectionV1,
    pub calibration: SignedArtifactSelectionV1,
    pub ood: SignedArtifactSelectionV1,
    pub calibration_lineage_digest: Digest32,
    pub ood_lineage_digest: Digest32,
}

pub struct AgentdNeuronArtifactAdmissionV1 {
    owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    artifact_root: PathBuf,
    selector: ArtifactSelectionVerifierV1,
    selections: NeuronSelectedArtifactsV1,
    clock: Arc<dyn AuthorityClock>,
    configuration: Digest32,
    last_time: u64,
    selection_expiries: [u64; 3],
    closed: bool,
}

impl AgentdNeuronArtifactAdmissionV1 {
    /// Admit an initial runtime only from three genuine first-generation
    /// selections. An evaluation comparator is not a runtime predecessor.
    /// This retains CURRENT, exact payload, expiry and independent-selector
    /// checks; empty runtime state is never a substitute for qualified artifacts.
    pub fn validate_initial_generation(
        &mut self,
        configuration: &NeuronRuntimeConfigV1,
    ) -> Result<(), NeuronAdmissionError> {
        if configuration.generation.get() != 1
            || [
                &self.selections.model,
                &self.selections.calibration,
                &self.selections.ood,
            ]
            .iter()
            .any(|selection| {
                selection.artifact_generation.get() != 1 || selection.predecessor_id.is_some()
            })
        {
            self.closed = true;
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        self.validate_current(configuration, PayloadCheck::Required)
    }

    /// Resolve and authenticate all three real payloads while holding the named
    /// artifact owner.  A copied byte-identical immutable payload is harmless;
    /// selection and revocation authority still come only from the verified
    /// CURRENT view and independent selector signature.
    pub fn new(
        owner: Arc<Mutex<LearningArtifactOwnerHost>>,
        artifact_root: impl AsRef<Path>,
        selector: ArtifactSelectionVerifierV1,
        selections: NeuronSelectedArtifactsV1,
        clock: Arc<dyn AuthorityClock>,
        config: &NeuronRuntimeConfigV1,
    ) -> Result<Self, NeuronAdmissionError> {
        let artifact_root = fs::canonicalize(artifact_root.as_ref())
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        for directory in ["payloads", "registries"] {
            let path = artifact_root.join(directory);
            let metadata =
                fs::symlink_metadata(&path).map_err(|_| NeuronAdmissionError::Unavailable)?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                return Err(NeuronAdmissionError::BindingMismatch);
            }
        }
        if selections.calibration_lineage_digest.is_zero()
            || selections.ood_lineage_digest.is_zero()
            || selections.calibration_lineage_digest == selections.ood_lineage_digest
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        let configuration = config
            .semantic_digest()
            .map_err(|_| NeuronAdmissionError::BindingMismatch)?;
        let selection_expiries = [
            selections.model.expires_at,
            selections.calibration.expires_at,
            selections.ood.expires_at,
        ];
        let mut result = Self {
            owner,
            artifact_root,
            selector,
            selections,
            clock,
            configuration,
            last_time: 0,
            selection_expiries,
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
        // Any failed refresh permanently closes this installed consumer.  A
        // caller must reconstruct the owner with fresh selections; rewinding a
        // clock, CURRENT directory or backup cannot revive the old handle.
        self.closed = true;
        let now = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        if now < self.last_time || self.selection_expiries.iter().any(|expiry| now > *expiry) {
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
            || self.selections.calibration.objective_digest
                != self.selections.model.objective_digest
            || self.selections.ood.objective_digest != self.selections.model.objective_digest
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }

        self.verify_one(
            &owner,
            &current,
            now,
            &self.selections.model,
            ArtifactKind::Model,
            config.generation,
            config.weights_digest,
            config.model_manifest_digest,
            profile,
            None,
            payload_check,
        )?;
        self.verify_one(
            &owner,
            &current,
            now,
            &self.selections.calibration,
            ArtifactKind::Policy,
            config.generation,
            config.calibration.calibration_artifact_digest,
            self.selections.calibration_lineage_digest,
            profile,
            Some(calibration.as_slice()),
            payload_check,
        )?;
        self.verify_one(
            &owner,
            &current,
            now,
            &self.selections.ood,
            ArtifactKind::Policy,
            config.generation,
            config.calibration.ood_artifact_digest,
            self.selections.ood_lineage_digest,
            profile,
            Some(ood.as_slice()),
            payload_check,
        )?;

        let finished = self
            .clock
            .now_unix_ms()
            .map_err(|_| NeuronAdmissionError::Unavailable)?;
        if finished < now
            || self
                .selection_expiries
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
        drop(owner);
        self.last_time = finished;
        self.closed = false;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn verify_one(
        &self,
        owner: &LearningArtifactOwnerHost,
        current: &VerifiedCurrentRegistryViewV1,
        now: u64,
        selection: &SignedArtifactSelectionV1,
        expected_kind: ArtifactKind,
        expected_generation: codex_hepta_agent_components::types::Generation,
        expected_content: Digest32,
        expected_support: Digest32,
        expected_compatibility: Digest32,
        expected_payload: Option<&[u8]>,
        payload_check: PayloadCheck,
    ) -> Result<(), NeuronAdmissionError> {
        let verified = self
            .selector
            .verify(selection, current, now)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        if selection.artifact_kind != expected_kind
            || selection.artifact_generation != expected_generation
            || selection.content_digest != expected_content
            || selection.support_digest != expected_support
            || selection.compatibility_digest != expected_compatibility
            || selection.encoded_size_bytes == 0
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        if payload_check == PayloadCheck::AlreadyLoaded {
            return Ok(());
        }

        let receipt = current.receipt();
        let snapshot_name = format!("{}-{}.snapshot", receipt.head_digest, receipt.file_digest);
        let payload_name = format!("{}-{}.bin", selection.artifact_id, selection.content_digest);
        let snapshot = self.open_regular_beneath("registries", &snapshot_name)?;
        let payload = self.open_regular_beneath("payloads", &payload_name)?;
        let mut loaded = load_selected_candidate(snapshot, payload, verified)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        let manifest = loaded.spec().manifest.clone();
        self.validate_loaded_manifest(
            selection,
            &manifest,
            expected_kind,
            expected_generation,
            expected_content,
            expected_support,
            expected_compatibility,
        )?;
        let refresh = owner
            .current_registry_view(now)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        let bytes = loaded
            .with_current(refresh, <[u8]>::to_vec)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        if expected_payload.is_some_and(|expected| expected != bytes.as_slice()) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn validate_loaded_manifest(
        &self,
        selection: &SignedArtifactSelectionV1,
        manifest: &ArtifactManifest,
        expected_kind: ArtifactKind,
        expected_generation: codex_hepta_agent_components::types::Generation,
        expected_content: Digest32,
        expected_support: Digest32,
        expected_compatibility: Digest32,
    ) -> Result<(), NeuronAdmissionError> {
        if manifest.artifact_id != selection.artifact_id
            || manifest.kind != expected_kind
            || manifest.generation != expected_generation
            || manifest.content_digest != expected_content
            || manifest.objective_digest != self.selections.model.objective_digest
            || manifest.support_digest != expected_support
            || manifest.compatibility_digest != expected_compatibility
            || manifest.encoded_size_bytes != selection.encoded_size_bytes
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        Ok(())
    }

    fn open_regular_beneath(
        &self,
        directory: &str,
        file_name: &str,
    ) -> Result<File, NeuronAdmissionError> {
        let base = self.artifact_root.join(directory);
        let canonical_base =
            fs::canonicalize(&base).map_err(|_| NeuronAdmissionError::Unavailable)?;
        if canonical_base.parent() != Some(self.artifact_root.as_path()) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        let path = base.join(file_name);
        let metadata =
            fs::symlink_metadata(&path).map_err(|_| NeuronAdmissionError::Unavailable)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        let canonical = fs::canonicalize(&path).map_err(|_| NeuronAdmissionError::Unavailable)?;
        if canonical.parent() != Some(canonical_base.as_path()) {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        File::open(canonical).map_err(|_| NeuronAdmissionError::Unavailable)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
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
        if input.objective_digest != self.selections.model.objective_digest {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        // Calibration sequence expiry is intentionally left to tick_guarded so
        // the product returns the explicit CalibrationExpired no-update outcome.
        self.validate_current(config, PayloadCheck::AlreadyLoaded)
    }
}

impl<W, P> crate::AgentdNeuronOwner<W, P>
where
    W: codex_hepta_agent_components::neuron::AnchorWitnessStore + Send + 'static,
    P: codex_hepta_agent_components::neuron::NeuronInferenceControlPort + Send + 'static,
{
    /// Compose the durable owner with authenticated CURRENT selection admission.
    /// The root is daemon configuration, not request input.
    pub fn into_selected_shared(
        self,
        artifacts: Arc<Mutex<LearningArtifactOwnerHost>>,
        artifact_root: impl AsRef<Path>,
        selector: ArtifactSelectionVerifierV1,
        selections: NeuronSelectedArtifactsV1,
        clock: Arc<dyn AuthorityClock>,
    ) -> Result<crate::AgentdNeuronHandleV1, codex_hepta_agent_components::neuron::NeuronRuntimeError>
    {
        let admission = AgentdNeuronArtifactAdmissionV1::new(
            artifacts,
            artifact_root,
            selector,
            selections,
            clock,
            self.runtime().configuration(),
        )
        .map_err(codex_hepta_agent_components::neuron::NeuronRuntimeError::Admission)?;
        self.into_shared(admission)
    }
}
