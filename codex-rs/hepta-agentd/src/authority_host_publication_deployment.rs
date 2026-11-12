//! Same-PID, one-attempt deployment of the already enabled publication route.
//! Root metadata locates original inputs; it is never a replacement authority.

use std::io;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::RootAuthorityDirectory;
use serde::Deserialize;
use serde::Serialize;

use super::ACTIVE;
use super::CLOSED;
use super::CONSUMED;
use super::PREPARED;
use super::RootGenerationPublicationEnrollmentCapabilityV1;
use super::RootGenerationPublicationRegistrationV1;

#[path = "authority_host_publication_deployment_data.rs"]
pub(crate) mod data;
#[path = "authority_host_publication_deployment_files.rs"]
pub(in crate::authority_host_runtime::session) mod files;
#[path = "authority_host_publication_input_data.rs"]
mod input_data;
pub(crate) use input_data::PublicationInputData;
#[path = "authority_host_publication_deployment_inputs.rs"]
mod inputs;
#[path = "authority_host_post_a_publication.rs"]
pub(in crate::authority_host_runtime::session) mod post_a;
pub(crate) use post_a::PreparedPublicationData;

use data::DeploymentData;
use data::LateMaterial;
use files::DirectoryPin;
use files::MetadataFile;
use files::OriginalFile;
use inputs::OriginalInputs;

static ATTEMPTS: AtomicU64 = AtomicU64::new(0);

/// Public correlation data, not a permission. The full trigger must still be
/// supplied through the original private Root directory for this one attempt.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootGenerationPublicationDeploymentSessionV1 {
    schema_version: u32,
    root_pid: u32,
    root_boot_id: String,
    root_start_ticks: u64,
    attempt: u64,
    descriptor_digest: String,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Trigger {
    session: RootGenerationPublicationDeploymentSessionV1,
    material_digest: String,
}

/// An actual enabled Root capability and its retained input files. No public
/// constructor accepts a bootstrap, caller JSON or a cloned registration slot.
pub struct RootGenerationPublicationDeploymentV1 {
    capability: RootGenerationPublicationEnrollmentCapabilityV1,
    descriptor: MetadataFile,
    data: DeploymentData,
    inputs: OriginalInputs,
    directories: Vec<DirectoryPin>,
    session: RootGenerationPublicationDeploymentSessionV1,
}

impl RootGenerationPublicationEnrollmentCapabilityV1 {
    pub fn with_original_deployment(
        self,
        descriptor_path: &Path,
    ) -> io::Result<RootGenerationPublicationDeploymentV1> {
        crate::authority_host_service::generation_publication::original_root()?;
        if self.version != super::PublicationVersion::LegacyV1
            || std::process::id() != self.root_pid
            || super::root_start()? != self.process_start_ticks
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
            || !matches!(self.phase.load(Ordering::Acquire), PREPARED | ACTIVE)
        {
            return Err(io::Error::other(
                "original Root deployment session required",
            ));
        }
        let (descriptor, bytes) = MetadataFile::open_metadata(descriptor_path)?;
        let data: DeploymentData = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1
            || data.issuer_keys.is_empty()
            || data.late_material == data.trigger
            || data.trigger == descriptor_path
            || data.late_material == descriptor_path
        {
            return Err(io::Error::other(
                "explicit versioned deployment inputs required",
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
        let inputs = OriginalInputs {
            current: RootAuthorityDirectory::open(&data.current_directory)
                .map_err(io::Error::other)?,
            previous_journal: OriginalFile::open_original(&data.previous_journal)?,
            previous_witness: OriginalFile::open_original(&data.previous_witness)?,
            target_journal: OriginalFile::open_original(&data.target_journal)?,
            target_witness: OriginalFile::open_original(&data.target_witness)?,
            withdrawal: OriginalFile::open_original(&data.withdrawal_file)?,
        };
        let attempt = ATTEMPTS
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| io::Error::other("Root deployment attempt counter exhausted"))?
            .checked_add(1)
            .ok_or_else(|| io::Error::other("Root deployment attempt overflow"))?;
        let session = RootGenerationPublicationDeploymentSessionV1 {
            schema_version: 1,
            root_pid: self.root_pid,
            root_boot_id: self.boot_id.clone(),
            root_start_ticks: self.process_start_ticks,
            attempt,
            descriptor_digest: descriptor.digest().to_string(),
        };
        descriptor.require_metadata_unchanged()?;
        Ok(RootGenerationPublicationDeploymentV1 {
            capability: self,
            descriptor,
            data,
            inputs,
            directories,
            session,
        })
    }
}

impl RootGenerationPublicationDeploymentV1 {
    /// Encode only the original target data and existing independent signature.
    /// This creates no owner or signature; Root enrollment authenticates both.
    pub fn encode_original_material(
        target: &codex_hepta_neuron::CellGenerationObserverConfigV1,
        selection: &codex_hepta_learning_artifacts::SignedArtifactSelectionV1,
    ) -> io::Result<Vec<u8>> {
        let material = LateMaterial {
            schema_version: 1,
            target: data::ObserverData::from_original_observer(target),
            selection: data::SelectionData::from_original_selection(selection)?,
        };
        let bytes = serde_json::to_vec(&material).map_err(io::Error::other)?;
        if bytes.is_empty() || bytes.len() > 65_536 {
            return Err(io::Error::other(
                "canonical publication material exceeds its bound",
            ));
        }
        Ok(bytes)
    }

    pub fn session(&self) -> &RootGenerationPublicationDeploymentSessionV1 {
        &self.session
    }

    /// Wait for this exact private Root trigger. A failure consumes this object;
    /// neither an uncertain register nor a changed file is retried.
    pub fn wait_and_register(
        self,
        stopping: &AtomicBool,
    ) -> io::Result<RootGenerationPublicationRegistrationV1> {
        let end = self.capability.operation_end()?;
        let (trigger_file, trigger) = loop {
            self.require_deployment_files()?;
            self.require_waiting_session(stopping, end)?;
            match self.capability.phase.load(Ordering::Acquire) {
                PREPARED => {}
                ACTIVE => match MetadataFile::open_metadata(&self.data.trigger) {
                    Ok((file, bytes)) => {
                        let trigger: Trigger =
                            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
                        self.require_original_trigger(&trigger)?;
                        break (file, trigger);
                    }
                    Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error),
                },
                CONSUMED | CLOSED => {
                    return Err(io::Error::other(
                        "Root deployment slot already consumed or closed",
                    ));
                }
                _ => return Err(io::Error::other("Root deployment phase invalid")),
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        let (material_file, bytes) = MetadataFile::open_metadata(&self.data.late_material)?;
        let material: LateMaterial = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&material).map_err(io::Error::other)? != bytes
            || material_file.digest().to_string() != trigger.material_digest
        {
            return Err(io::Error::other(
                "trigger does not name the original canonical late material",
            ));
        }
        let (inputs, artifacts) = self.inputs.enrollment_inputs(
            &self.data.original_input_data(),
            &material,
            self.capability.consumer_uid,
        )?;
        self.require_deployment_files()?;
        trigger_file.require_metadata_unchanged()?;
        material_file.require_metadata_unchanged()?;
        for file in &artifacts {
            file.require_original_file()?;
        }
        self.require_waiting_session(stopping, end)?;
        let capability: RootGenerationPublicationEnrollmentCapabilityV1 = self.capability;
        let result = capability.register(inputs)?;
        // The original one-shot slot has been consumed. Any post-check failure
        // is uncertain, never permission to run Reserve again.
        self.descriptor
            .require_metadata_unchanged()
            .map_err(registration_uncertain)?;
        for directory in &self.directories {
            directory
                .require_directory()
                .map_err(registration_uncertain)?;
        }
        self.inputs
            .require_original_inputs()
            .map_err(registration_uncertain)?;
        trigger_file
            .require_metadata_unchanged()
            .map_err(registration_uncertain)?;
        material_file
            .require_metadata_unchanged()
            .map_err(registration_uncertain)?;
        for file in &artifacts {
            file.require_original_file()
                .map_err(registration_uncertain)?;
        }
        if stopping.load(Ordering::Acquire) {
            return Err(io::Error::other(
                "Root deployment registration outcome uncertain after session ended",
            ));
        }
        Ok(result)
    }

    fn require_waiting_session(&self, stopping: &AtomicBool, end: Instant) -> io::Result<()> {
        if stopping.load(Ordering::Acquire) || Instant::now() >= end {
            return Err(io::Error::new(
                io::ErrorKind::Interrupted,
                "Root deployment ended before registration",
            ));
        }
        Ok(())
    }

    fn require_original_trigger(&self, trigger: &Trigger) -> io::Result<()> {
        if trigger.session != self.session {
            return Err(io::Error::other("old or different Root deployment trigger"));
        }
        if trigger
            .material_digest
            .parse::<codex_hepta_types::Digest32>()
            .map_err(io::Error::other)?
            .is_zero()
        {
            return Err(io::Error::other(
                "original canonical material digest required",
            ));
        }
        Ok(())
    }

    fn require_deployment_files(&self) -> io::Result<()> {
        self.descriptor.require_metadata_unchanged()?;
        for directory in &self.directories {
            directory.require_directory()?;
        }
        self.inputs.require_original_inputs()
    }
}

fn registration_uncertain(error: io::Error) -> io::Error {
    io::Error::other(format!(
        "Root deployment registration completed but input observation is uncertain: {error}"
    ))
}

#[cfg(test)]
#[path = "authority_host_publication_deployment_tests.rs"]
mod tests;
