use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

const GENERATION_SCHEMA_VERSION: u32 = 1;
const MAX_POINTER_BYTES: u64 = 8 * 1024;
const MAX_MANIFEST_BYTES: usize = 64 * 1024;
const MAX_SNAPSHOT_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ARCHIVE_BYTES: u64 = 2 * 1024 * 1024 * 1024;

pub type JournalDigest32 = [u8; 32];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JournalFailpoint {
    BeforeArchiveWrite,
    AfterArchiveFsync,
    AfterArchiveRename,
    AfterCheckpointFsync,
    AfterCheckpointRename,
    BeforePointerRename,
    AfterPointerRename,
    AfterDirectoryFsync,
}

pub trait JournalFailpointController {
    fn hit(&mut self, point: JournalFailpoint) -> Result<(), JournalGenerationError>;
}

#[derive(Default)]
pub struct NoJournalFailpoints;

impl JournalFailpointController for NoJournalFailpoints {
    fn hit(&mut self, _point: JournalFailpoint) -> Result<(), JournalGenerationError> {
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum JournalGenerationError {
    InvalidConfiguration,
    InvalidGeneration,
    InvalidPointer,
    InvalidManifest,
    CorruptCheckpoint,
    CorruptArchive,
    CapacityExceeded,
    PreviousGenerationMismatch,
    NotFound,
    CrashInjected(JournalFailpoint),
    Io(String),
    Encoding,
}

impl fmt::Display for JournalGenerationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for JournalGenerationError {}

impl From<std::io::Error> for JournalGenerationError {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.to_string())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct JournalGenerationManifestV1 {
    pub schema_version: u32,
    pub generation: u64,
    pub previous_manifest_sha256: Option<JournalDigest32>,
    pub snapshot_sha256: JournalDigest32,
    pub snapshot_bytes: u64,
    pub archive_sha256: JournalDigest32,
    pub archive_bytes: u64,
    pub created_at_unix_ms: u64,
}

impl JournalGenerationManifestV1 {
    pub fn digest(&self) -> Result<JournalDigest32, JournalGenerationError> {
        self.validate()?;
        digest_serialized(
            b"hepta.inference.control.journal-generation.v1\0",
            self,
        )
    }

    fn validate(&self) -> Result<(), JournalGenerationError> {
        if self.schema_version != GENERATION_SCHEMA_VERSION
            || self.generation == 0
            || self.snapshot_sha256 == [0; 32]
            || self.archive_sha256 == [0; 32]
            || self.snapshot_bytes > MAX_SNAPSHOT_BYTES
            || self.archive_bytes > MAX_ARCHIVE_BYTES
            || self.created_at_unix_ms == 0
        {
            return Err(JournalGenerationError::InvalidManifest);
        }
        if self.generation == 1 && self.previous_manifest_sha256.is_some() {
            return Err(JournalGenerationError::InvalidManifest);
        }
        if self.generation > 1
            && self
                .previous_manifest_sha256
                .is_none_or(|digest| digest == [0; 32])
        {
            return Err(JournalGenerationError::InvalidManifest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CurrentPointerV1 {
    schema_version: u32,
    generation: u64,
    checkpoint_file: String,
    manifest_sha256: JournalDigest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedJournalGeneration {
    pub manifest: JournalGenerationManifestV1,
    pub manifest_sha256: JournalDigest32,
    pub checkpoint_path: PathBuf,
    pub archive_path: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecoveredJournalGeneration {
    pub manifest: JournalGenerationManifestV1,
    pub manifest_sha256: JournalDigest32,
    pub snapshot: Vec<u8>,
    pub archive_path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct JournalGenerationStore {
    directory: PathBuf,
    namespace: String,
}
