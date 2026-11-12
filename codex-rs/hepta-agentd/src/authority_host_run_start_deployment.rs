//! Root-held locators and original readonly descriptors for one Initial run.
//! Only protected Root metadata chooses files. Peer requests never do so.

use std::fs::File;

use super::super::generation_publication::deployment::files::MetadataFile;
use super::super::generation_publication::deployment::files::OriginalFile;
use super::*;

const DEPLOYMENT_PURPOSE: &str = "runtime.objective.original-run-start-deployment.v1";

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct RunStartDeploymentData {
    schema_version: u32,
    purpose: String,
    journal: PathBuf,
    objective_profile: PathBuf,
    authbus_trust: PathBuf,
}

/// This object has no public constructor or serialized representation. It
/// holds the same actual protected metadata and original path/FD identities
/// throughout registration and live retention. It grants no learning access.
pub(crate) struct RootInitialRunStartFilesV1 {
    metadata: MetadataFile,
    journal: OriginalFile,
    profile: OriginalFile,
    trust: OriginalFile,
}

impl RootInitialRunStartFilesV1 {
    pub(crate) fn open_original_deployment(path: &Path) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let data: RunStartDeploymentData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema_version != 1 || data.purpose != DEPLOYMENT_PURPOSE {
            return Err(io::Error::other(
                "original Root RunStart deployment required",
            ));
        }
        let files = Self {
            metadata,
            journal: OriginalFile::open_original(&data.journal)?,
            profile: OriginalFile::open_original(&data.objective_profile)?,
            trust: OriginalFile::open_original(&data.authbus_trust)?,
        };
        files.with_original_files(|_, _, _| Ok(()))?;
        Ok(files)
    }

    pub(crate) fn with_original_files<T>(
        &self,
        action: impl FnOnce(&File, &File, &File) -> io::Result<T>,
    ) -> io::Result<T> {
        crate::authority_host_service::generation_initial::original_root()?;
        self.metadata.require_metadata_unchanged()?;
        let journal = self.journal.original_descriptor()?;
        let profile = self.profile.original_descriptor()?;
        let trust = self.trust.original_descriptor()?;
        let value = action(&journal, &profile, &trust)?;
        self.journal.require_original_file()?;
        self.profile.require_original_file()?;
        self.trust.require_original_file()?;
        self.metadata.require_metadata_unchanged()?;
        Ok(value)
    }
}

impl PreparedHostAuthoritySession {
    /// Enable independent RunStart observation before serving the original
    /// Initial route. Reserve enrollment captures the actual complete prefix;
    /// Recover cannot use this input to manufacture a first acknowledgement.
    pub fn enable_initial_run_start_retention_from_deployment(
        &mut self,
        path: &Path,
    ) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        let initial = self
            .initial_publication
            .as_ref()
            .ok_or_else(|| io::Error::other("RunStart retention requires original Initial"))?;
        if initial.phase.load(Ordering::Acquire) != PREPARED || initial.run_start.is_some() {
            return Err(io::Error::other(
                "RunStart original inputs already consumed",
            ));
        }
        let files = RootInitialRunStartFilesV1::open_original_deployment(path)?;
        self.service.with_initial_publication_context(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            |_| {
                // These are custody checks only. No journal/profile/trust
                // content is observed until the durable registration arm.
                files.with_original_files(|_, _, _| Ok(()))
            },
        )?;
        let initial = self
            .initial_publication
            .as_mut()
            .ok_or_else(|| io::Error::other("original Initial runtime disappeared"))?;
        if initial.phase.load(Ordering::Acquire) != PREPARED || initial.run_start.is_some() {
            return Err(io::Error::other("original RunStart input slot changed"));
        }
        initial.run_start = Some(Arc::new(files));
        Ok(())
    }
}
