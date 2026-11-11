//! Artifact reads share one content contract. A host may transfer already
//! opened files when its path-selection policy must reject races and aliases.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::path::Path;
use std::sync::Arc;

use codex_hepta_types::Digest32;

use super::JointGenerationProcessConfigV1;
use super::JointGenerationProcessWorkerV1;
use crate::CellGenerationErrorV2;
use crate::cell_joint_process;
use crate::cell_joint_protocol::MAX_PUBLIC_BYTES;
use crate::cell_joint_protocol::MAX_WEIGHTS_BYTES;

/// Files selected and opened by the admitted host. Ownership is transferred;
/// path names in the config are not reopened by `open_files`.
pub struct JointGenerationProcessFilesV1 {
    pub executable: File,
    pub weights: File,
    pub public: File,
}

impl JointGenerationProcessConfigV1 {
    fn validate_digests(&self) -> Result<(), CellGenerationErrorV2> {
        if [
            self.executable_digest,
            self.source_digest,
            self.weights_digest,
            self.public_digest,
            self.device_digest,
        ]
        .contains(&[0; 32])
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(())
    }
}

impl JointGenerationProcessWorkerV1 {
    /// Original path-based constructor. The host must provide stable regular
    /// paths; this API does not claim a race-free no-follow opening policy.
    pub fn open(
        config: JointGenerationProcessConfigV1,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self, CellGenerationErrorV2> {
        config.validate_digests()?;
        let files = JointGenerationProcessFilesV1 {
            executable: File::open(&config.executable)
                .map_err(|_| CellGenerationErrorV2::Unavailable)?,
            weights: File::open(&config.weights).map_err(|_| CellGenerationErrorV2::Unavailable)?,
            public: File::open(&config.public).map_err(|_| CellGenerationErrorV2::Unavailable)?,
        };
        Self::open_files(config, files, clock)
    }

    /// Fingerprint the actual supplied files without reopening any asset path.
    /// Weights and public input become immutable in-memory bytes; the opened
    /// executable inode is retained. The host keeps the executable immutable and
    /// supplies a clock from the same epoch as its Agentd owner. This does not
    /// grant adoption, publication or authority over the supplied source digest.
    pub fn open_files(
        config: JointGenerationProcessConfigV1,
        files: JointGenerationProcessFilesV1,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self, CellGenerationErrorV2> {
        config.validate_digests()?;
        let weights = read_file(files.weights, MAX_WEIGHTS_BYTES)?;
        let public = read_file(files.public, MAX_PUBLIC_BYTES)?;
        if cell_joint_process::executable_digest(&files.executable)? != config.executable_digest
            || Digest32::of_bytes(&weights).into_array() != config.weights_digest
            || Digest32::of_bytes(&public).into_array() != config.public_digest
            || Self::observed_device_digest()? != config.device_digest
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        Ok(Self {
            executable: files.executable,
            executable_digest: config.executable_digest,
            source_digest: config.source_digest,
            weights,
            weights_digest: config.weights_digest,
            public,
            public_digest: config.public_digest,
            device_digest: config.device_digest,
            clock,
            resident: None,
        })
    }
}

pub(super) fn read_bounded(path: &Path, maximum: usize) -> Result<Vec<u8>, CellGenerationErrorV2> {
    read_file(
        File::open(path).map_err(|_| CellGenerationErrorV2::Unavailable)?,
        maximum,
    )
}

fn read_file(mut file: File, maximum: usize) -> Result<Vec<u8>, CellGenerationErrorV2> {
    let metadata = file
        .metadata()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if !metadata.is_file() {
        return Err(CellGenerationErrorV2::InvalidBinding);
    }
    if metadata.len() > maximum as u64 {
        return Err(CellGenerationErrorV2::Capacity);
    }
    file.rewind()
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| CellGenerationErrorV2::Unavailable)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(CellGenerationErrorV2::Capacity);
    }
    Ok(bytes)
}
