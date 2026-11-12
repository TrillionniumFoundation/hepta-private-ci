//! One original Initial deployment in the same Root process. The Root file
//! freezes existing inputs; a trigger only asks the real capability to validate
//! and register them after the actual five-lane consumer has opened schema3.

use super::ACTIVE;
use super::CLOSED;
use super::CONSUMED;
use super::PREPARED;
use super::RootGenerationInitialEnrollmentCapabilityV1;
use super::RootGenerationInitialRegistrationV1;
use crate::HostGenerationInitialDeploymentV1;
use crate::authority_host_service::generation_initial::PURPOSE;
use codex_hepta_contracts::RootAuthorityDirectory;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use super::super::generation_publication::deployment::data as shared_data;
use super::super::generation_publication::deployment::files as shared_files;
use shared_files::DirectoryPin;
use shared_files::MetadataFile;
use shared_files::OriginalFile;

#[path = "authority_host_initial_deployment_data.rs"]
mod data;
#[path = "authority_host_initial_deployment_inputs.rs"]
mod inputs;
use data::InitialDeploymentData;
use inputs::InitialOriginalFiles;

static INITIAL_ATTEMPTS: AtomicU64 = AtomicU64::new(0);

/// Correlation data for this exact Root process and Initial purpose only.
#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootGenerationInitialDeploymentSessionV1 {
    purpose: String,
    schema_version: u32,
    root_pid: u32,
    root_boot_id: String,
    root_start_ticks: u64,
    attempt: u64,
    descriptor_digest: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct InitialTrigger {
    session: RootGenerationInitialDeploymentSessionV1,
}

/// Retained original files and data. It contains no registration capability.
/// The actual original Initial capability must later consume this object.
pub struct RootGenerationInitialDeploymentFilesV1 {
    descriptor: MetadataFile,
    data: InitialDeploymentData,
    inputs: InitialOriginalFiles,
    directories: Vec<DirectoryPin>,
    deployment: HostGenerationInitialDeploymentV1,
}

/// One enabled Root Initial cap and its original fixed deployment. It is not
/// Clone, Default or deserializable and cannot change mode after a failure.
pub struct RootGenerationInitialDeploymentV1 {
    capability: RootGenerationInitialEnrollmentCapabilityV1,
    files: RootGenerationInitialDeploymentFilesV1,
    session: RootGenerationInitialDeploymentSessionV1,
}

impl RootGenerationInitialDeploymentFilesV1 {
    pub fn open_original_initial_deployment(path: &Path) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        let (descriptor, bytes) = MetadataFile::open_metadata(path)?;
        let data: InitialDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1 || data.issuer_keys.is_empty() || data.trigger == path {
            return Err(io::Error::other(
                "explicit original Initial deployment required",
            ));
        }
        shared_files::require_absolute(&data.trigger)?;
        let directories = vec![
            DirectoryPin::capture_root(shared_files::parent(&data.trigger)?)?,
            DirectoryPin::capture_root(&data.current_directory)?,
            DirectoryPin::capture_private(&data.artifact_root)?,
            DirectoryPin::capture_private(&data.consumer_state_root)?,
        ];
        let inputs = InitialOriginalFiles {
            current: RootAuthorityDirectory::open(&data.current_directory)
                .map_err(io::Error::other)?,
            target_journal: OriginalFile::open_original(&data.target_journal)?,
            target_witness: OriginalFile::open_original(&data.target_witness)?,
            withdrawal: OriginalFile::open_original(&data.withdrawal_file)?,
        };
        let deployment = HostGenerationInitialDeploymentV1::new(
            data.operation.clone(),
            &data.target.original_observer_config()?,
        )?;
        let files = Self {
            descriptor,
            data,
            inputs,
            directories,
            deployment,
        };
        files.require_original_initial_files()?;
        Ok(files)
    }

    /// A frozen description only. Original enable/enrollment still validate
    /// the same target; this data is not a claim that a journal has genesis.
    pub fn deployment(&self) -> &HostGenerationInitialDeploymentV1 {
        &self.deployment
    }

    fn require_original_initial_files(&self) -> io::Result<()> {
        self.descriptor.require_metadata_unchanged()?;
        for directory in &self.directories {
            directory.require_directory()?;
        }
        self.inputs.require_initial_files()
    }
}

impl RootGenerationInitialEnrollmentCapabilityV1 {
    pub fn with_original_initial_deployment(
        self,
        files: RootGenerationInitialDeploymentFilesV1,
    ) -> io::Result<RootGenerationInitialDeploymentV1> {
        crate::authority_host_service::generation_initial::original_root()?;
        if std::process::id() != self.root_pid
            || super::root_start()? != self.process_start_ticks
            || std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
            || !matches!(self.phase.load(Ordering::Acquire), PREPARED | ACTIVE)
        {
            return Err(io::Error::other(
                "same original Initial Root session required",
            ));
        }
        files.require_original_initial_files()?;
        let attempt = INITIAL_ATTEMPTS
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| io::Error::other("Initial deployment attempt counter exhausted"))?
            .checked_add(1)
            .ok_or_else(|| io::Error::other("Initial deployment attempt overflow"))?;
        let session = RootGenerationInitialDeploymentSessionV1 {
            purpose: PURPOSE.into(),
            schema_version: 1,
            root_pid: self.root_pid,
            root_boot_id: self.boot_id.clone(),
            root_start_ticks: self.process_start_ticks,
            attempt,
            descriptor_digest: files.descriptor.digest().to_string(),
        };
        Ok(RootGenerationInitialDeploymentV1 {
            capability: self,
            files,
            session,
        })
    }
}

impl RootGenerationInitialDeploymentV1 {
    pub fn session(&self) -> &RootGenerationInitialDeploymentSessionV1 {
        &self.session
    }

    /// Listener-ready is not nonce-owner-ready. A trusted Root host triggers
    /// only after actual consumer activation; missing schema3 remains refusal.
    pub fn wait_and_register_initial(
        self,
        stopping: &AtomicBool,
    ) -> io::Result<RootGenerationInitialRegistrationV1> {
        let end = Instant::now()
            .checked_add(self.capability.lifetime)
            .ok_or_else(|| io::Error::other("Initial deployment deadline overflow"))?;
        let trigger_file = loop {
            self.files.require_original_initial_files()?;
            self.require_initial_wait(stopping, end)?;
            match self.capability.phase.load(Ordering::Acquire) {
                PREPARED => {}
                ACTIVE => match MetadataFile::open_metadata(&self.files.data.trigger) {
                    Ok((file, bytes)) => {
                        let trigger: InitialTrigger =
                            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
                        self.require_initial_trigger(&trigger)?;
                        break file;
                    }
                    Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error),
                },
                CONSUMED | CLOSED => {
                    return Err(io::Error::other("Initial deployment consumed or closed"));
                }
                _ => return Err(io::Error::other("Initial deployment phase invalid")),
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        let original_inputs: &InitialOriginalFiles = &self.files.inputs;
        let (inputs, artifacts) = original_inputs
            .initial_enrollment_inputs(&self.files.data, self.capability.consumer_uid)?;
        self.files.require_original_initial_files()?;
        trigger_file.require_metadata_unchanged()?;
        for file in &artifacts {
            file.require_original_file()?;
        }
        self.require_initial_wait(stopping, end)?;
        let capability: RootGenerationInitialEnrollmentCapabilityV1 = self.capability;
        let result = capability.register(inputs)?;
        self.files
            .require_original_initial_files()
            .map_err(initial_registration_uncertain)?;
        trigger_file
            .require_metadata_unchanged()
            .map_err(initial_registration_uncertain)?;
        for file in &artifacts {
            file.require_original_file()
                .map_err(initial_registration_uncertain)?;
        }
        if stopping.load(Ordering::Acquire) {
            return Err(io::Error::other(
                "Initial registration outcome uncertain after session ended",
            ));
        }
        Ok(result)
    }

    fn require_initial_wait(&self, stopping: &AtomicBool, end: Instant) -> io::Result<()> {
        if stopping.load(Ordering::Acquire) || Instant::now() >= end {
            return Err(io::Error::new(
                io::ErrorKind::Interrupted,
                "Initial deployment ended before registration",
            ));
        }
        Ok(())
    }

    fn require_initial_trigger(&self, trigger: &InitialTrigger) -> io::Result<()> {
        if trigger.session != self.session || trigger.session.purpose != PURPOSE {
            return Err(io::Error::other(
                "different purpose or old Initial deployment trigger",
            ));
        }
        Ok(())
    }
}

fn initial_registration_uncertain(error: io::Error) -> io::Error {
    io::Error::other(format!(
        "Initial registration completed but observation is uncertain: {error}"
    ))
}

#[cfg(test)]
#[path = "authority_host_initial_deployment_tests.rs"]
mod tests;
