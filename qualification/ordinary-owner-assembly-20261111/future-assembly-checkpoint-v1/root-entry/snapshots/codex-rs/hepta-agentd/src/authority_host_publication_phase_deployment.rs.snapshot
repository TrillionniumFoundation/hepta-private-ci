//! One phase's retained Current descriptor and late original material.
//! No capability or mutable owner is reconstructed from these Root files.

use super::data::DeploymentData;
use super::data::LateMaterial;
use super::data::Mode;
use super::files;
use super::files::DirectoryPin;
use super::files::MetadataFile;
use super::files::OriginalFile;
use super::inputs::OriginalInputs;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_types::Digest32;
use std::io;
use std::path::Path;
use std::sync::Arc;

pub(in crate::authority_host_runtime::session) struct OriginalCurrentPhaseFiles {
    descriptor: MetadataFile,
    data: DeploymentData,
    directories: Vec<DirectoryPin>,
}

/// Retained only until the actual one-shot registration and its post-checks.
// The actual command receives clones of these original descriptors.
pub(in crate::authority_host_runtime::session) struct OriginalCurrentPhaseObservation {
    inputs: OriginalInputs,
    material: MetadataFile,
    artifacts: Vec<OriginalFile>,
}

impl OriginalCurrentPhaseFiles {
    pub(in crate::authority_host_runtime::session) fn open_current_phase_descriptor(
        path: &Path,
        current_path: &Path,
        consumer_root: &Path,
    ) -> io::Result<Self> {
        crate::authority_host_service::generation_publication::original_root()?;
        let (descriptor, bytes) = MetadataFile::open_metadata(path)?;
        let data: DeploymentData = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1
            || data.issuer_keys.is_empty()
            || !matches!(data.mode, Mode::Reserve)
            || data.current_directory != current_path
            || data.consumer_state_root != consumer_root
            || data.late_material == data.trigger
            || data.trigger == path
            || data.late_material == path
        {
            return Err(io::Error::other(
                "same original phase Current locations and Reserve mode required",
            ));
        }
        let directories = vec![
            DirectoryPin::capture_root(files::parent(&data.trigger)?)?,
            DirectoryPin::capture_root(files::parent(&data.late_material)?)?,
            DirectoryPin::capture_root(&data.current_directory)?,
            DirectoryPin::capture_private(&data.artifact_root)?,
            DirectoryPin::capture_private(&data.consumer_state_root)?,
        ];
        files::require_absolute(&data.trigger)?;
        files::require_absolute(&data.late_material)?;
        let original = Self { descriptor, data, directories };
        original.require_current_phase_files()?;
        Ok(original)
    }

    pub(in crate::authority_host_runtime::session) fn current_phase_descriptor_digest(
        &self,
    ) -> Digest32 {
        self.descriptor.digest()
    }

    pub(in crate::authority_host_runtime::session) fn current_phase_trigger(&self) -> &Path {
        &self.data.trigger
    }

    pub(in crate::authority_host_runtime::session) fn current_phase_material(&self) -> &Path {
        &self.data.late_material
    }

    pub(in crate::authority_host_runtime::session) fn require_current_phase_files(
        &self,
    ) -> io::Result<()> {
        self.descriptor.require_metadata_unchanged()?;
        for directory in &self.directories {
            directory.require_directory()?;
        }
        Ok(())
    }

    pub(in crate::authority_host_runtime::session) fn original_current_phase_inputs(
        &self,
        current: &Arc<RootAuthorityDirectory>,
        consumer_uid: u32,
        material_digest: Digest32,
        observed_material: &[u8],
    ) -> io::Result<(crate::RootGenerationPublicationEnrollmentV1, OriginalCurrentPhaseObservation)> {
        self.require_current_phase_files()?;
        let (material_file, bytes) = MetadataFile::open_metadata(&self.data.late_material)?;
        let material: LateMaterial = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&material).map_err(io::Error::other)? != bytes
            || material_file.digest() != material_digest
            || bytes != observed_material
        {
            return Err(io::Error::other(
                "phase trigger does not bind the original canonical Current material",
            ));
        }
        // Target journals need not exist at startup. They are opened once here,
        // after the host has supplied the actual selected target, and pinned
        // through the real registration acknowledgement.
        let original = OriginalInputs {
            current: Arc::clone(current),
            previous_journal: OriginalFile::open_original(&self.data.previous_journal)?,
            previous_witness: OriginalFile::open_original(&self.data.previous_witness)?,
            target_journal: OriginalFile::open_original(&self.data.target_journal)?,
            target_witness: OriginalFile::open_original(&self.data.target_witness)?,
            withdrawal: OriginalFile::open_original(&self.data.withdrawal_file)?,
        };
        let (inputs, artifacts) = original.enrollment_inputs(
            &self.data, &material, consumer_uid,
        )?;
        let observation = OriginalCurrentPhaseObservation {
            inputs: original, material: material_file, artifacts,
        };
        self.require_current_phase_observation(&observation)?;
        Ok((inputs, observation))
    }

    pub(in crate::authority_host_runtime::session) fn require_current_phase_observation(
        &self,
        observation: &OriginalCurrentPhaseObservation,
    ) -> io::Result<()> {
        self.require_current_phase_files()?;
        observation.inputs.require_original_inputs()?;
        observation.material.require_metadata_unchanged()?;
        for artifact in &observation.artifacts {
            artifact.require_original_file()?;
        }
        Ok(())
    }
}
