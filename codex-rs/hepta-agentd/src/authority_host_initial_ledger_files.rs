//! Root administrator's original four-file Ledger mapping, retained before A.
//! This contains data and read-only descriptors; no signing key is opened and
//! no role is selected from the daemon's sealed deployment.

use std::fs::File;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use serde::Deserialize;

use super::shared_files::MetadataFile;
use super::shared_files::OriginalFile;
use crate::HostGenerationInitialDeploymentV1;
use crate::RootInitialLearningTrustFilesV1;
use crate::production_launcher::LedgerDeploymentData;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema: u8,
    purpose: String,
    initial: HostGenerationInitialDeploymentV1,
    ledger: LedgerDeploymentData,
    learning_trust_deployment: PathBuf,
}

/// Fixed original data custody. Only the real Root enrollment supplies the
/// role authorities and durable baseline; this type cannot authorize recovery.
pub(crate) struct RootHistoricalLedgerDeploymentV1 {
    metadata: MetadataFile,
    files: [OriginalFile; 4],
    pub(crate) initial: HostGenerationInitialDeploymentV1,
    pub(crate) ledger: LedgerDeploymentData,
    pub(crate) trust: Arc<RootInitialLearningTrustFilesV1>,
}

impl RootHistoricalLedgerDeploymentV1 {
    pub(crate) fn open_original(path: &Path) -> io::Result<Self> {
        crate::authority_host_service::generation_initial::original_root()?;
        let (metadata, bytes) = MetadataFile::open_metadata(path)?;
        let data: Deployment = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema != 1 || data.purpose != "runtime.circuit.original-ledger-deployment.v1" {
            return Err(io::Error::other(
                "original first-A Ledger deployment required",
            ));
        }
        let paths = [
            &data.ledger.ledger,
            &data.ledger.ledger_witness,
            &data.ledger.signature_journal,
            &data.ledger.signature_witness.path,
        ];
        for (index, path) in paths.iter().enumerate() {
            if paths[..index].contains(path) || *path == &data.ledger.generator_key {
                return Err(io::Error::other("distinct original Ledger inputs required"));
            }
        }
        // The generator_key field is part of the shared data schema only.
        // Root never opens it; its enrolled verifier supplies the public role.
        let files = [
            OriginalFile::open_original(paths[0])?,
            OriginalFile::open_original(paths[1])?,
            OriginalFile::open_original(paths[2])?,
            OriginalFile::open_original(paths[3])?,
        ];
        let trust = Arc::new(
            RootInitialLearningTrustFilesV1::open_original_learning_trust(
                &data.learning_trust_deployment,
            )?,
        );
        let held = Self {
            metadata,
            files,
            initial: data.initial,
            ledger: data.ledger,
            trust,
        };
        held.require_original_files()?;
        Ok(held)
    }

    pub(crate) fn original_descriptors(&self) -> io::Result<[File; 4]> {
        self.require_original_files()?;
        let descriptors = [
            self.files[0].original_descriptor()?,
            self.files[1].original_descriptor()?,
            self.files[2].original_descriptor()?,
            self.files[3].original_descriptor()?,
        ];
        self.require_original_files()?;
        Ok(descriptors)
    }

    pub(crate) fn require_original_files(&self) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        self.metadata.require_metadata_unchanged()?;
        self.trust.require_original_files()?;
        for file in &self.files {
            file.require_original_file()?;
        }
        self.metadata.require_metadata_unchanged()
    }

    pub(crate) fn metadata_digest(&self) -> Digest32 {
        self.metadata.digest()
    }
}
