use std::path::Path;
use std::path::PathBuf;

use serde::Serialize;

use crate::ImportCheckpoint;
use crate::ImportFailure;
use crate::QualificationError;
use crate::digest::framed_digest;
use crate::digest::sha256;
use crate::durable::read_private_bounded;
use crate::durable::sync_directory;
use crate::durable::verify_private_directory;
use crate::durable::write_private_new;
use crate::request::canonical_json;

const MAX_CHECKPOINT_BYTES: usize = 64 * 1024;
const TERMINAL_SEAL_DOMAIN: &[u8] = b"hepta-live-product-shadow-terminal-seal:v3";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TerminalStatus {
    Complete,
    Failed,
}

impl TerminalStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Complete => "complete",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug)]
pub struct TerminalSeal {
    checkpoint_sha256: String,
    evidence_set_sha256: String,
    failures: Vec<ImportFailure>,
    run_id: String,
    run_root: PathBuf,
    seal_file_sha256: String,
    status: TerminalStatus,
    terminal_seal_sha256: String,
    transport_artifact_count: usize,
    transport_evidence_sha256: String,
    verified_count: usize,
}

impl TerminalSeal {
    pub fn create(checkpoint: ImportCheckpoint) -> Result<Self, QualificationError> {
        verify_private_directory(checkpoint.run_root())?;
        let checkpoint_path = checkpoint.run_root().join("import-checkpoint.json");
        let checkpoint_bytes = read_private_bounded(&checkpoint_path, MAX_CHECKPOINT_BYTES)?;
        if sha256(&checkpoint_bytes) != checkpoint.checkpoint_sha256() {
            return Err(QualificationError::Invalid(
                "durable import checkpoint changed before terminal sealing".to_string(),
            ));
        }
        let status = if checkpoint.is_complete() {
            TerminalStatus::Complete
        } else {
            TerminalStatus::Failed
        };
        let fields = TerminalSealFields {
            authority: false,
            checkpoint_sha256: checkpoint.checkpoint_sha256(),
            enforce: false,
            evidence_set_sha256: checkpoint.evidence_set_sha256(),
            failures: checkpoint.failures(),
            outbound: false,
            promotion: false,
            run_id: checkpoint.run_id(),
            schema: "hepta_shadow_qualification_terminal_seal_v3",
            schema_version: 3,
            status,
            terminal: true,
            transport_artifact_count: checkpoint.transport_artifact_count(),
            transport_evidence_sha256: checkpoint.transport_evidence_sha256(),
            verified_artifact_count: checkpoint.verified_count(),
        };
        let binding_bytes = canonical_json(&fields)?;
        let terminal_seal_sha256 = framed_digest(
            TERMINAL_SEAL_DOMAIN,
            [checkpoint_bytes.as_slice(), binding_bytes.as_slice()],
        );
        let document = TerminalSealDocument {
            fields,
            terminal_seal_sha256: &terminal_seal_sha256,
        };
        let seal_bytes = canonical_json(&document)?;
        write_private_new(
            &checkpoint.run_root().join("terminal-seal.json"),
            &seal_bytes,
        )?;
        sync_directory(checkpoint.run_root())?;
        Ok(Self {
            checkpoint_sha256: checkpoint.checkpoint_sha256().to_string(),
            evidence_set_sha256: checkpoint.evidence_set_sha256().to_string(),
            failures: checkpoint.failures().to_vec(),
            run_id: checkpoint.run_id().to_string(),
            run_root: checkpoint.run_root().to_path_buf(),
            seal_file_sha256: sha256(&seal_bytes),
            status,
            terminal_seal_sha256,
            transport_artifact_count: checkpoint.transport_artifact_count(),
            transport_evidence_sha256: checkpoint.transport_evidence_sha256().to_string(),
            verified_count: checkpoint.verified_count(),
        })
    }

    pub fn checkpoint_sha256(&self) -> &str {
        &self.checkpoint_sha256
    }

    pub fn evidence_set_sha256(&self) -> &str {
        &self.evidence_set_sha256
    }

    pub fn failures(&self) -> &[ImportFailure] {
        &self.failures
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn seal_file_sha256(&self) -> &str {
        &self.seal_file_sha256
    }

    pub fn status(&self) -> TerminalStatus {
        self.status
    }

    pub fn terminal_seal_sha256(&self) -> &str {
        &self.terminal_seal_sha256
    }

    pub fn transport_artifact_count(&self) -> usize {
        self.transport_artifact_count
    }

    pub fn transport_evidence_sha256(&self) -> &str {
        &self.transport_evidence_sha256
    }

    pub fn verified_count(&self) -> usize {
        self.verified_count
    }
}

#[derive(Clone, Copy, Serialize)]
struct TerminalSealFields<'a> {
    authority: bool,
    checkpoint_sha256: &'a str,
    enforce: bool,
    evidence_set_sha256: &'a str,
    failures: &'a [ImportFailure],
    outbound: bool,
    promotion: bool,
    run_id: &'a str,
    schema: &'static str,
    schema_version: u32,
    status: TerminalStatus,
    terminal: bool,
    transport_artifact_count: usize,
    transport_evidence_sha256: &'a str,
    verified_artifact_count: usize,
}

#[derive(Serialize)]
struct TerminalSealDocument<'a> {
    #[serde(flatten)]
    fields: TerminalSealFields<'a>,
    terminal_seal_sha256: &'a str,
}
