//! Crash-recoverable execution owner for one cell split.
//!
//! A topology proposal is an authority-free description.  This module is the
//! narrow owner boundary that turns one independently admitted split into an
//! ordered, recoverable operation.  The owner does not issue authority and
//! every public receipt carries [`AuthorityPosture::DENY_ALL`].  Effects are
//! still performed by the named domain owners supplied through the callback
//! traits below; this module records their returned operation receipts only
//! after validating the exact operation binding.
//!
//! The durable ledger is deliberately separate from the learning ledger.  It
//! is an execution ledger for one split operation: intent, artifact CAS,
//! state snapshot/migration, route publication, generation fence, ledger
//! commit and terminal completion.  A torn final frame is truncated on reopen;
//! a complete frame with a bad checksum is rejected.  Recovery never invents
//! a receipt and therefore asks the owner callback to replay the unfinished
//! step with the exact persisted predecessor receipt digest.

use std::error::Error as StdError;
use std::fmt;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const JOURNAL_MAGIC: &str = "HEPTA-CELL-SPLIT-V1";
const JOURNAL_SCHEMA_VERSION: u16 = 1;
const MAX_JOURNAL_BYTES: u64 = 8 * 1024 * 1024;
const MAX_RECORD_BYTES: usize = 32 * 1024;
const MAX_ARTIFACT_BYTES: usize = 64 * 1024 * 1024;
const MAX_STATE_SNAPSHOT_BYTES: usize = 8 * 1024 * 1024;

/// Ordered durable execution phases for one split operation.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CellSplitPhaseV1 {
    Prepared,
    ArtifactDurable,
    StateSnapshotted,
    StateMigrated,
    RoutePublished,
    GenerationFenced,
    LedgerCommitted,
    Completed,
    Quarantined,
    /// Durable intent written before executing a potentially non-idempotent
    /// migration. Recovery must reconcile the original native effect.
    MigrationInFlight,
}

impl CellSplitPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::ArtifactDurable => 1,
            Self::StateSnapshotted => 2,
            Self::StateMigrated => 3,
            Self::RoutePublished => 4,
            Self::GenerationFenced => 5,
            Self::LedgerCommitted => 6,
            Self::Completed => 7,
            Self::Quarantined => 8,
            Self::MigrationInFlight => 9,
        }
    }

    const fn terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Quarantined)
    }
}

/// Exact identity and generation binding for one split operation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitPlanV1 {
    pub operation_id: StableId,
    pub source_cell: StableId,
    pub child_cell: StableId,
    pub source_generation: Generation,
    pub child_generation: Generation,
    pub artifact_digest: Digest32,
    pub state_schema_digest: Digest32,
    /// Exact source→child partition/range map owned by the state domain.
    pub state_partition_digest: Digest32,
    /// Independent semantic/invariant verification of the migrated child.
    pub migration_verification_digest: Digest32,
    pub baseline_route_digest: Digest32,
    pub candidate_route_digest: Digest32,
    pub authority_epoch: u64,
}

impl CellSplitPlanV1 {
    /// Validate the split contract and derive the immutable intent digest.
    pub fn validate(&self) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id == self.source_cell || self.operation_id == self.child_cell {
            return Err(CellSplitExecutionErrorV1::InvalidPlan);
        }
        if self.source_cell == self.child_cell
            || self.source_generation.next().ok() != Some(self.child_generation)
            || self.authority_epoch == 0
            || self.baseline_route_digest == self.candidate_route_digest
        {
            return Err(CellSplitExecutionErrorV1::InvalidPlan);
        }
        if [
            self.artifact_digest,
            self.state_schema_digest,
            self.state_partition_digest,
            self.migration_verification_digest,
            self.baseline_route_digest,
            self.candidate_route_digest,
        ]
        .into_iter()
        .any(Digest32::is_zero)
        {
            return Err(CellSplitExecutionErrorV1::InvalidPlan);
        }
        let mut bytes = b"hepta.cell-split.intent.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.source_cell);
        push_id(&mut bytes, &self.child_cell);
        bytes.extend_from_slice(&self.source_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.child_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for digest in [
            self.artifact_digest,
            self.state_schema_digest,
            self.state_partition_digest,
            self.migration_verification_digest,
            self.baseline_route_digest,
            self.candidate_route_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Receipt returned after bytes were actually written and synced to the CAS.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitArtifactCasReceiptV1 {
    pub operation_id: StableId,
    pub artifact_digest: Digest32,
    pub bytes_len: u64,
    pub cas_path_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CellSplitArtifactCasReceiptV1 {
    fn validate_for(
        &self,
        plan: &CellSplitPlanV1,
        actual_bytes_len: usize,
    ) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.artifact_digest != plan.artifact_digest
            || self.bytes_len != actual_bytes_len as u64
            || self.cas_path_digest.is_zero()
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt("artifact CAS"));
        }
        Ok(self.digest())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.artifact-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(self.artifact_digest.as_array());
        bytes.extend_from_slice(&self.bytes_len.to_be_bytes());
        bytes.extend_from_slice(self.cas_path_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

/// Receipt containing the exact state bytes observed before migration.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitSnapshotReceiptV1 {
    pub operation_id: StableId,
    pub source_generation: Generation,
    pub schema_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub bytes: Vec<u8>,
    pub authority: AuthorityPosture,
}

impl CellSplitSnapshotReceiptV1 {
    fn validate_for(&self, plan: &CellSplitPlanV1) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.source_generation != plan.source_generation
            || self.schema_digest != plan.state_schema_digest
            || self.bytes.len() > MAX_STATE_SNAPSHOT_BYTES
            || Digest32::of_bytes(&self.bytes) != self.snapshot_digest
            || self.snapshot_digest.is_zero()
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt("state snapshot"));
        }
        Ok(self.digest())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.snapshot-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(&self.source_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.schema_digest.as_array());
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        bytes.extend_from_slice(&(self.bytes.len() as u64).to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

/// Receipt returned after the child state owner commits the migrated state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitMigrationReceiptV1 {
    pub operation_id: StableId,
    pub source_generation: Generation,
    pub child_generation: Generation,
    pub snapshot_digest: Digest32,
    pub state_partition_digest: Digest32,
    pub verification_digest: Digest32,
    pub child_state_digest: Digest32,
    pub committed: bool,
    pub authority: AuthorityPosture,
}

impl CellSplitMigrationReceiptV1 {
    fn validate_for(
        &self,
        plan: &CellSplitPlanV1,
        snapshot: &CellSplitSnapshotReceiptV1,
    ) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.source_generation != plan.source_generation
            || self.child_generation != plan.child_generation
            || self.snapshot_digest != snapshot.snapshot_digest
            || self.state_partition_digest != plan.state_partition_digest
            || self.verification_digest != plan.migration_verification_digest
            || self.child_state_digest.is_zero()
            || !self.committed
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt("state migration"));
        }
        Ok(self.digest())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.migration-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(&self.source_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.child_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        bytes.extend_from_slice(self.state_partition_digest.as_array());
        bytes.extend_from_slice(self.verification_digest.as_array());
        bytes.extend_from_slice(self.child_state_digest.as_array());
        bytes.push(u8::from(self.committed));
        Digest32::of_bytes(&bytes)
    }
}

/// A separate durable rollback receipt. A migration-commit receipt must not
/// masquerade as proof that the original state was restored.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRollbackReceiptV1 {
    pub operation_id: StableId,
    pub source_generation: Generation,
    pub child_generation: Generation,
    pub snapshot_digest: Digest32,
    pub restored_state_digest: Digest32,
    pub durable: bool,
    pub verified: bool,
    pub authority: AuthorityPosture,
}

impl CellSplitRollbackReceiptV1 {
    fn validate_for(
        &self,
        plan: &CellSplitPlanV1,
        snapshot: &CellSplitSnapshotReceiptV1,
    ) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.source_generation != plan.source_generation
            || self.child_generation != plan.child_generation
            || self.snapshot_digest != snapshot.snapshot_digest
            || self.restored_state_digest.is_zero()
            || !self.durable
            || !self.verified
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt("state rollback"));
        }
        let mut bytes = b"hepta.cell-split.rollback-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(&self.source_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.child_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.snapshot_digest.as_array());
        bytes.extend_from_slice(self.restored_state_digest.as_array());
        bytes.push(u8::from(self.durable));
        bytes.push(u8::from(self.verified));
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Receipt returned only after the CNS route is published for the child.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRouteCutoverReceiptV1 {
    pub operation_id: StableId,
    pub source_generation: Generation,
    pub child_generation: Generation,
    pub predecessor_route_digest: Digest32,
    pub published_route_digest: Digest32,
    pub published: bool,
    pub authority: AuthorityPosture,
}

impl CellSplitRouteCutoverReceiptV1 {
    fn validate_for(&self, plan: &CellSplitPlanV1) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.source_generation != plan.source_generation
            || self.child_generation != plan.child_generation
            || self.predecessor_route_digest != plan.baseline_route_digest
            || self.published_route_digest != plan.candidate_route_digest
            || !self.published
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "CNS route cutover",
            ));
        }
        Ok(self.digest())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.route-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(&self.source_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.child_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.predecessor_route_digest.as_array());
        bytes.extend_from_slice(self.published_route_digest.as_array());
        bytes.push(u8::from(self.published));
        Digest32::of_bytes(&bytes)
    }
}

/// Receipt returned by the supervisor generation fence after admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitGenerationFenceReceiptV1 {
    pub operation_id: StableId,
    pub predecessor_generation: Generation,
    pub fenced_generation: Generation,
    pub fence_digest: Digest32,
    pub admitted: bool,
    pub authority: AuthorityPosture,
}

impl CellSplitGenerationFenceReceiptV1 {
    fn validate_for(&self, plan: &CellSplitPlanV1) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.predecessor_generation != plan.source_generation
            || self.fenced_generation != plan.child_generation
            || self.fence_digest.is_zero()
            || !self.admitted
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "generation fence",
            ));
        }
        Ok(self.digest())
    }

    fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cell-split.fence-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        bytes.extend_from_slice(&self.predecessor_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.fenced_generation.get().to_be_bytes());
        bytes.extend_from_slice(self.fence_digest.as_array());
        bytes.push(u8::from(self.admitted));
        Digest32::of_bytes(&bytes)
    }
}

/// The phase receipt returned to a caller after a durable ledger append.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitLedgerReceiptV1 {
    pub operation_id: StableId,
    pub sequence: u64,
    pub phase: CellSplitPhaseV1,
    pub previous_record_digest: Digest32,
    pub record_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Recoverable owner error. Callback failures carry only bounded diagnostic
/// text; raw state and artifact bytes never enter the execution ledger.
#[derive(Debug)]
pub enum CellSplitExecutionErrorV1 {
    Io(io::ErrorKind),
    Busy,
    CorruptJournal,
    JournalTooLarge,
    RecordTooLarge,
    InvalidPlan,
    PlanMismatch,
    InvalidTransition {
        from: CellSplitPhaseV1,
        to: CellSplitPhaseV1,
    },
    InvalidReceipt(&'static str),
    ArtifactDigestMismatch,
    ArtifactTooLarge,
    /// Native migration outcome cannot be proven; do not invoke Execute again.
    MigrationReconciliationRequired,
    /// The real native owner lives in canonical operator acceptance; this
    /// supervisor reference implementation must not dispatch production effects.
    CanonicalOwnerRequired,
    Callback {
        stage: &'static str,
        message: String,
    },
}

impl fmt::Display for CellSplitExecutionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitExecutionErrorV1 {}

impl From<io::Error> for CellSplitExecutionErrorV1 {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}

/// A create-only, content-addressed artifact store used by the split owner.
/// Existing bytes are accepted only after they are read back and rehashed.
#[derive(Clone, Debug)]
pub struct FileCellSplitArtifactCasV1 {
    root: PathBuf,
}

impl FileCellSplitArtifactCasV1 {
    /// Open a CAS below a host-designated root. The root is canonicalized once
    /// and each object name is a digest, so no caller path is interpreted.
    pub fn open(root: impl AsRef<Path>) -> Result<Self, CellSplitExecutionErrorV1> {
        fs::create_dir_all(root.as_ref())?;
        let root = fs::canonicalize(root)?;
        if !root.metadata()?.is_dir() {
            return Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::NotADirectory));
        }
        Ok(Self { root })
    }

    /// Store and sync one artifact. A retry against an existing object is
    /// idempotent only when exact bytes and length still match.
    pub fn put(
        &self,
        plan: &CellSplitPlanV1,
        bytes: &[u8],
    ) -> Result<CellSplitArtifactCasReceiptV1, CellSplitExecutionErrorV1> {
        plan.validate()?;
        if bytes.len() > MAX_ARTIFACT_BYTES {
            return Err(CellSplitExecutionErrorV1::ArtifactTooLarge);
        }
        if Digest32::of_bytes(bytes) != plan.artifact_digest {
            return Err(CellSplitExecutionErrorV1::ArtifactDigestMismatch);
        }
        let path = self.root.join(plan.artifact_digest.to_string());
        let temporary = self.root.join(format!(
            ".{}.{}.tmp",
            plan.artifact_digest, plan.operation_id
        ));
        match fs::symlink_metadata(&path) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                // The final digest name is occupied by this process only
                // after an atomic create-only link. A crash during the write therefore
                // cannot leave a partial object at the CAS name.
                self.install_new_artifact(&path, &temporary, bytes, plan)?;
            }
            Ok(_) => {
                // `create_new` treats an existing symlink as an occupied
                // name. Never follow that symlink on the idempotent retry
                // path: a mutable CAS directory must not redirect a
                // content-addressed read to an arbitrary host file.
                let (mut file, existing) = read_existing_cas_object(&path)?;
                if existing != bytes {
                    return Err(CellSplitExecutionErrorV1::ArtifactDigestMismatch);
                }
                // A receipt for an existing object is still a receipt for a
                // durable object. Syncing here makes retries explicit even
                // if another process created the object.
                file.sync_all()?;
                self.root_file()?.sync_all()?;
            }
            Err(error) => return Err(error.into()),
        }
        Ok(CellSplitArtifactCasReceiptV1 {
            operation_id: plan.operation_id.clone(),
            artifact_digest: plan.artifact_digest,
            bytes_len: bytes.len() as u64,
            cas_path_digest: Digest32::of_bytes(path.to_string_lossy().as_bytes()),
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Read an already durable artifact by the digest bound in `plan`.
    /// Recovery uses this when a process stopped after the CAS write but
    /// before it could append the `ArtifactDurable` ledger frame and therefore
    /// no longer has the original artifact bytes in memory.
    pub fn get(&self, plan: &CellSplitPlanV1) -> Result<Vec<u8>, CellSplitExecutionErrorV1> {
        plan.validate()?;
        let path = self.root.join(plan.artifact_digest.to_string());
        let metadata = fs::symlink_metadata(&path)?;
        if !metadata.file_type().is_file() {
            return Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::InvalidData));
        }
        if metadata.len() > MAX_ARTIFACT_BYTES as u64 {
            return Err(CellSplitExecutionErrorV1::ArtifactTooLarge);
        }
        let mut file = open_existing_cas_object(&path)?;
        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        (&mut file)
            .take((MAX_ARTIFACT_BYTES as u64).saturating_add(1))
            .read_to_end(&mut bytes)?;
        if bytes.len() > MAX_ARTIFACT_BYTES {
            return Err(CellSplitExecutionErrorV1::ArtifactTooLarge);
        }
        if Digest32::of_bytes(&bytes) != plan.artifact_digest {
            return Err(CellSplitExecutionErrorV1::ArtifactDigestMismatch);
        }
        file.sync_all()?;
        Ok(bytes)
    }

    fn root_file(&self) -> Result<File, CellSplitExecutionErrorV1> {
        OpenOptions::new()
            .read(true)
            .open(&self.root)
            .map_err(CellSplitExecutionErrorV1::from)
    }

    fn install_new_artifact(
        &self,
        path: &Path,
        temporary: &Path,
        bytes: &[u8],
        _plan: &CellSplitPlanV1,
    ) -> Result<(), CellSplitExecutionErrorV1> {
        // The operation ledger lock makes the deterministic staging name safe
        // for one operation. A bounded retry also handles a stale staging file
        // left by a process that crashed before rename.
        for _ in 0..2 {
            match OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(temporary)
            {
                Ok(mut file) => {
                    if let Err(error) = file.write_all(bytes).and_then(|()| file.sync_all()) {
                        drop(file);
                        let _ = fs::remove_file(temporary);
                        return Err(error.into());
                    }
                    drop(file);
                    // Persist the staging directory entry before exposing it
                    // under the final content-addressed name without replacing an existing object.
                    self.root_file()?.sync_all()?;
                    match fs::hard_link(temporary, path) {
                        Ok(()) => {
                            fs::remove_file(temporary)?;
                            self.root_file()?.sync_all()?;
                            return Ok(());
                        }
                        Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                            let _ = fs::remove_file(temporary);
                            let (mut existing_file, existing) = read_existing_cas_object(path)?;
                            if existing != bytes {
                                return Err(CellSplitExecutionErrorV1::ArtifactDigestMismatch);
                            }
                            existing_file.sync_all()?;
                            fs::remove_file(temporary)?;
                            self.root_file()?.sync_all()?;
                            return Ok(());
                        }
                        Err(error) => {
                            let _ = fs::remove_file(temporary);
                            return Err(error.into());
                        }
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                    match read_existing_cas_object(temporary) {
                        Ok((mut temporary_file, existing)) if existing == bytes => {
                            temporary_file.sync_all()?;
                            drop(temporary_file);
                            match fs::hard_link(temporary, path) {
                                Ok(()) => {
                                    self.root_file()?.sync_all()?;
                                    return Ok(());
                                }
                                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {
                                    let _ = fs::remove_file(temporary);
                                    let (mut existing_file, existing) =
                                        read_existing_cas_object(path)?;
                                    if existing != bytes {
                                        return Err(
                                            CellSplitExecutionErrorV1::ArtifactDigestMismatch,
                                        );
                                    }
                                    existing_file.sync_all()?;
                                    self.root_file()?.sync_all()?;
                                    return Ok(());
                                }
                                Err(error) => return Err(error.into()),
                            }
                        }
                        Ok((_, _)) | Err(CellSplitExecutionErrorV1::ArtifactDigestMismatch) => {
                            let _ = fs::remove_file(temporary);
                        }
                        Err(CellSplitExecutionErrorV1::ArtifactTooLarge) => {
                            let _ = fs::remove_file(temporary);
                        }
                        Err(error) => return Err(error),
                    }
                }
                Err(error) => return Err(error.into()),
            }
        }
        Err(CellSplitExecutionErrorV1::Busy)
    }
}

/// Reopen an existing object without following a symlink on Unix.  `create_new`
/// protects the first writer, but the idempotent retry path must also protect
/// the read-back: a raced symlink must never redirect the CAS verification to
/// an arbitrary file outside the canonical root.
fn open_existing_cas_object(path: &Path) -> Result<File, CellSplitExecutionErrorV1> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;

        return OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(path)
            .map_err(CellSplitExecutionErrorV1::from);
    }

    #[cfg(not(unix))]
    {
        let metadata = fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() {
            return Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::InvalidData));
        }
        File::open(path).map_err(CellSplitExecutionErrorV1::from)
    }
}

fn read_existing_cas_object(path: &Path) -> Result<(File, Vec<u8>), CellSplitExecutionErrorV1> {
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.file_type().is_file() {
        return Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::InvalidData));
    }
    if metadata.len() > MAX_ARTIFACT_BYTES as u64 {
        return Err(CellSplitExecutionErrorV1::ArtifactTooLarge);
    }
    let mut file = open_existing_cas_object(path)?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    (&mut file)
        .take((MAX_ARTIFACT_BYTES as u64).saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() > MAX_ARTIFACT_BYTES {
        return Err(CellSplitExecutionErrorV1::ArtifactTooLarge);
    }
    Ok((file, bytes))
}

/// Domain owner for child-state snapshot and migration.
pub trait CellSplitStateMigrationOwnerV1 {
    fn snapshot(
        &mut self,
        plan: &CellSplitPlanV1,
    ) -> Result<CellSplitSnapshotReceiptV1, CellSplitExecutionErrorV1>;

    fn migrate(
        &mut self,
        plan: &CellSplitPlanV1,
        snapshot: &CellSplitSnapshotReceiptV1,
    ) -> Result<CellSplitMigrationReceiptV1, CellSplitExecutionErrorV1>;

    fn rollback(
        &mut self,
        plan: &CellSplitPlanV1,
        snapshot: &CellSplitSnapshotReceiptV1,
    ) -> Result<CellSplitRollbackReceiptV1, CellSplitExecutionErrorV1>;
}

/// CNS route owner. The callback must return only after the successor route is
/// durably published and the predecessor route is no longer admitted.
pub trait CellSplitCnsRouteOwnerV1 {
    fn cutover(
        &mut self,
        plan: &CellSplitPlanV1,
        migration: &CellSplitMigrationReceiptV1,
    ) -> Result<CellSplitRouteCutoverReceiptV1, CellSplitExecutionErrorV1>;
}

/// Supervisor-owned generation fence. This is intentionally separate from the
/// CNS callback so a route publication cannot stand in for writer admission.
pub trait CellSplitGenerationFenceOwnerV1 {
    fn fence(
        &mut self,
        plan: &CellSplitPlanV1,
        route: &CellSplitRouteCutoverReceiptV1,
    ) -> Result<CellSplitGenerationFenceReceiptV1, CellSplitExecutionErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
struct PersistedLedgerRecordV1 {
    schema_version: u16,
    sequence: u64,
    operation_id: String,
    plan_digest: String,
    phase: CellSplitPhaseV1,
    receipt_digest: String,
    previous_record_digest: String,
    record_digest: String,
}

/// The fsync-backed execution ledger for one split operation.
#[derive(Debug)]
pub struct CellSplitLedgerV1 {
    file: File,
    plan: CellSplitPlanV1,
    plan_digest: Digest32,
    sequence: u64,
    head_digest: Digest32,
    phase: CellSplitPhaseV1,
    last_receipt_digest: Digest32,
    /// Receipt digest of the durable `StateMigrated` frame.  Keeping this
    /// separately from the current head prevents a later recovery replay
    /// from substituting a different migration receipt after route/fence
    /// frames have already been committed.
    migration_receipt_digest: Option<Digest32>,
    durable_length: u64,
    poisoned: bool,
}

impl Drop for CellSplitLedgerV1 {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

impl CellSplitLedgerV1 {
    /// Create a new execution ledger and persist its immutable operation header.
    pub fn create(
        path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        let plan_digest = plan.validate()?;
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .open(path)?;
        acquire_lock(&file)?;
        if file.metadata()?.len() != 0 {
            return Err(CellSplitExecutionErrorV1::CorruptJournal);
        }
        let header = format!(
            "{JOURNAL_MAGIC}\t{JOURNAL_SCHEMA_VERSION}\t{}\t{}\n",
            plan.operation_id, plan_digest
        );
        file.write_all(header.as_bytes())?;
        file.sync_all()?;
        if let Some(parent) = path.parent().filter(|path| !path.as_os_str().is_empty()) {
            sync_directory(parent)?;
        }
        Ok(Self {
            file,
            plan,
            plan_digest,
            sequence: 0,
            head_digest: Digest32::ZERO,
            phase: CellSplitPhaseV1::Prepared,
            last_receipt_digest: plan_digest,
            migration_receipt_digest: None,
            durable_length: header.len() as u64,
            poisoned: false,
        })
    }

    /// Reopen and verify a ledger against the exact operation plan. Incomplete
    /// final bytes are truncated only when all complete records remain valid.
    pub fn recover(
        path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        let plan_digest = plan.validate()?;
        let mut file = OpenOptions::new().read(true).write(true).open(path)?;
        acquire_lock(&file)?;
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(CellSplitExecutionErrorV1::JournalTooLarge);
        }
        let complete_length = bytes
            .iter()
            .rposition(|byte| *byte == b'\n')
            .map_or(0, |index| index + 1);
        if complete_length == 0 {
            return Err(CellSplitExecutionErrorV1::CorruptJournal);
        }
        if complete_length != bytes.len() {
            file.set_len(complete_length as u64)?;
            file.sync_all()?;
            bytes.truncate(complete_length);
        }
        let mut lines = bytes.split(|byte| *byte == b'\n');
        let header = lines
            .next()
            .ok_or(CellSplitExecutionErrorV1::CorruptJournal)?;
        let header =
            std::str::from_utf8(header).map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?;
        let fields = header.split('\t').collect::<Vec<_>>();
        if fields.len() != 4
            || fields[0] != JOURNAL_MAGIC
            || fields[1].parse::<u16>().ok() != Some(JOURNAL_SCHEMA_VERSION)
            || fields[2] != plan.operation_id.as_str()
            || Digest32::from_str(fields[3]).ok() != Some(plan_digest)
        {
            return Err(CellSplitExecutionErrorV1::PlanMismatch);
        }
        let mut sequence = 0;
        let mut head_digest = Digest32::ZERO;
        let mut phase = CellSplitPhaseV1::Prepared;
        let mut last_receipt_digest = plan_digest;
        let mut migration_receipt_digest = None;
        for line in lines {
            if line.is_empty() {
                continue;
            }
            if line.len() > MAX_RECORD_BYTES {
                return Err(CellSplitExecutionErrorV1::RecordTooLarge);
            }
            let persisted: PersistedLedgerRecordV1 = serde_json::from_slice(line)
                .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?;
            let record = decode_record(persisted)?;
            if record.sequence != sequence + 1
                || record.operation_id != plan.operation_id
                || record.plan_digest != plan_digest
                || record.previous_record_digest != head_digest
                || record.record_digest != record_digest(&record)
                || !valid_transition(phase, record.phase)
            {
                return Err(CellSplitExecutionErrorV1::CorruptJournal);
            }
            sequence = record.sequence;
            head_digest = record.record_digest;
            phase = record.phase;
            last_receipt_digest = record.receipt_digest;
            if record.phase == CellSplitPhaseV1::StateMigrated {
                migration_receipt_digest = Some(record.receipt_digest);
            }
        }
        file.seek(SeekFrom::End(0))?;
        Ok(Self {
            file,
            plan,
            plan_digest,
            sequence,
            head_digest,
            phase,
            last_receipt_digest,
            migration_receipt_digest,
            durable_length: complete_length as u64,
            poisoned: false,
        })
    }

    /// Append one phase after validating the strict successor transition.
    pub fn append(
        &mut self,
        phase: CellSplitPhaseV1,
        receipt_digest: Digest32,
    ) -> Result<CellSplitLedgerReceiptV1, CellSplitExecutionErrorV1> {
        if self.poisoned {
            return Err(CellSplitExecutionErrorV1::CorruptJournal);
        }
        if receipt_digest.is_zero() {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt("ledger evidence"));
        }
        let previous_phase = self.latest_phase();
        if !valid_transition(previous_phase, phase) {
            return Err(CellSplitExecutionErrorV1::InvalidTransition {
                from: previous_phase,
                to: phase,
            });
        }
        let record = LedgerRecordV1 {
            sequence: self
                .sequence
                .checked_add(1)
                .ok_or(CellSplitExecutionErrorV1::CorruptJournal)?,
            operation_id: self.plan.operation_id.clone(),
            plan_digest: self.plan_digest,
            phase,
            receipt_digest,
            previous_record_digest: self.head_digest,
            record_digest: Digest32::ZERO,
        };
        let mut record = record;
        record.record_digest = record_digest(&record);
        let persisted = PersistedLedgerRecordV1::from(&record);
        let bytes = serde_json::to_vec(&persisted)
            .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?;
        if bytes.len() > MAX_RECORD_BYTES {
            return Err(CellSplitExecutionErrorV1::RecordTooLarge);
        }
        let next_length = self
            .durable_length
            .checked_add(bytes.len() as u64 + 1)
            .ok_or(CellSplitExecutionErrorV1::JournalTooLarge)?;
        if next_length > MAX_JOURNAL_BYTES {
            return Err(CellSplitExecutionErrorV1::JournalTooLarge);
        }
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.durable_length {
            return Err(CellSplitExecutionErrorV1::CorruptJournal);
        }
        self.file.write_all(&bytes)?;
        self.file.write_all(b"\n")?;
        self.file
            .sync_all()
            .map_err(|_| CellSplitExecutionErrorV1::Io(io::ErrorKind::Other))?;
        self.sequence = record.sequence;
        self.head_digest = record.record_digest;
        self.phase = phase;
        self.last_receipt_digest = receipt_digest;
        if phase == CellSplitPhaseV1::StateMigrated {
            self.migration_receipt_digest = Some(receipt_digest);
        }
        self.durable_length = next_length;
        self.poisoned = false;
        Ok(CellSplitLedgerReceiptV1 {
            operation_id: record.operation_id,
            sequence: record.sequence,
            phase,
            previous_record_digest: record.previous_record_digest,
            record_digest: record.record_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Return the current phase, or `Prepared` for a newly created ledger.
    pub fn latest_phase(&self) -> CellSplitPhaseV1 {
        self.phase
    }

    /// Return the current chain head used as a recovery fence.
    pub const fn head_digest(&self) -> Digest32 {
        self.head_digest
    }

    /// Return the plan digest bound into every frame.
    pub const fn plan_digest(&self) -> Digest32 {
        self.plan_digest
    }

    /// Return the number of durable phase frames.
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }

    /// Return the exact operation receipt digest from the latest frame.
    pub const fn last_receipt_digest(&self) -> Digest32 {
        self.last_receipt_digest
    }

    /// Return the migration receipt digest retained from the durable chain.
    pub const fn migration_receipt_digest(&self) -> Option<Digest32> {
        self.migration_receipt_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct LedgerRecordV1 {
    sequence: u64,
    operation_id: StableId,
    plan_digest: Digest32,
    phase: CellSplitPhaseV1,
    receipt_digest: Digest32,
    previous_record_digest: Digest32,
    record_digest: Digest32,
}

impl From<&LedgerRecordV1> for PersistedLedgerRecordV1 {
    fn from(value: &LedgerRecordV1) -> Self {
        Self {
            schema_version: JOURNAL_SCHEMA_VERSION,
            sequence: value.sequence,
            operation_id: value.operation_id.to_string(),
            plan_digest: value.plan_digest.to_string(),
            phase: value.phase,
            receipt_digest: value.receipt_digest.to_string(),
            previous_record_digest: value.previous_record_digest.to_string(),
            record_digest: value.record_digest.to_string(),
        }
    }
}

fn decode_record(
    value: PersistedLedgerRecordV1,
) -> Result<LedgerRecordV1, CellSplitExecutionErrorV1> {
    if value.schema_version != JOURNAL_SCHEMA_VERSION {
        return Err(CellSplitExecutionErrorV1::CorruptJournal);
    }
    let receipt_digest = Digest32::from_str(&value.receipt_digest)
        .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?;
    if receipt_digest.is_zero() {
        return Err(CellSplitExecutionErrorV1::CorruptJournal);
    }
    Ok(LedgerRecordV1 {
        sequence: value.sequence,
        operation_id: StableId::new(value.operation_id)
            .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?,
        plan_digest: Digest32::from_str(&value.plan_digest)
            .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?,
        phase: value.phase,
        receipt_digest,
        previous_record_digest: Digest32::from_str(&value.previous_record_digest)
            .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?,
        record_digest: Digest32::from_str(&value.record_digest)
            .map_err(|_| CellSplitExecutionErrorV1::CorruptJournal)?,
    })
}

fn record_digest(record: &LedgerRecordV1) -> Digest32 {
    let mut bytes = b"hepta.cell-split.ledger-record.v1\0".to_vec();
    bytes.extend_from_slice(&record.sequence.to_be_bytes());
    push_id(&mut bytes, &record.operation_id);
    bytes.extend_from_slice(record.plan_digest.as_array());
    bytes.push(record.phase.tag());
    bytes.extend_from_slice(record.receipt_digest.as_array());
    bytes.extend_from_slice(record.previous_record_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn valid_transition(from: CellSplitPhaseV1, to: CellSplitPhaseV1) -> bool {
    if to == CellSplitPhaseV1::Quarantined {
        return !from.terminal();
    }
    matches!(
        (from, to),
        (
            CellSplitPhaseV1::Prepared,
            CellSplitPhaseV1::ArtifactDurable
        ) | (
            CellSplitPhaseV1::ArtifactDurable,
            CellSplitPhaseV1::StateSnapshotted
        ) | (
            CellSplitPhaseV1::StateSnapshotted,
            CellSplitPhaseV1::StateMigrated
        ) | (
            CellSplitPhaseV1::StateSnapshotted,
            CellSplitPhaseV1::MigrationInFlight
        ) | (
            CellSplitPhaseV1::MigrationInFlight,
            CellSplitPhaseV1::StateMigrated
        ) | (
            CellSplitPhaseV1::StateMigrated,
            CellSplitPhaseV1::RoutePublished
        ) | (
            CellSplitPhaseV1::RoutePublished,
            CellSplitPhaseV1::GenerationFenced
        ) | (
            CellSplitPhaseV1::GenerationFenced,
            CellSplitPhaseV1::LedgerCommitted
        ) | (
            CellSplitPhaseV1::LedgerCommitted,
            CellSplitPhaseV1::Completed
        )
    )
}

fn acquire_lock(file: &File) -> Result<(), CellSplitExecutionErrorV1> {
    if !file.metadata()?.is_file() {
        return Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::InvalidInput));
    }
    match file.try_lock() {
        Ok(()) => Ok(()),
        Err(TryLockError::WouldBlock) => Err(CellSplitExecutionErrorV1::Busy),
        Err(TryLockError::Error(error)) => Err(error.into()),
    }
}

// A ledger header is the durable operation intent.  Syncing the file alone
// does not make a newly-created directory entry durable after a host crash on
// Unix, so create() also syncs its parent directory.  Windows does not expose
// the same directory fsync contract through std, and the file sync remains the
// strongest portable guarantee there.
#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), CellSplitExecutionErrorV1> {
    OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(CellSplitExecutionErrorV1::from)?
        .sync_all()
        .map_err(CellSplitExecutionErrorV1::from)
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), CellSplitExecutionErrorV1> {
    Ok(())
}

/// Production execution is exclusively owned by the independently reviewed
/// canonical native owner. This secondary supervisor example is test-only.
/// DENY_ALL in a returned receipt is not itself an execution permission check.
fn require_fixture_execution() -> Result<(), CellSplitExecutionErrorV1> {
    if cfg!(test) {
        Ok(())
    } else {
        Err(CellSplitExecutionErrorV1::CanonicalOwnerRequired)
    }
}

/// Only a frozen intent digest, NEVER an external operation receipt.
fn migration_intent_digest(plan_digest: Digest32, snapshot_receipt: Digest32) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.cell-split.migration-in-flight.v1\0",
        plan_digest.as_array(),
        snapshot_receipt.as_array(),
    ])
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

/// One owner that executes the strict ordered split state machine.
#[derive(Debug)]
pub struct CellSplitExecutionOwnerV1 {
    plan: CellSplitPlanV1,
    plan_digest: Digest32,
    ledger: CellSplitLedgerV1,
    phase: CellSplitPhaseV1,
    last_receipt_digest: Digest32,
    migration_receipt_digest: Option<Digest32>,
    last_migration: Option<CellSplitMigrationReceiptV1>,
    last_route: Option<CellSplitRouteCutoverReceiptV1>,
}

impl CellSplitExecutionOwnerV1 {
    /// Create and persist a new split intent. No external effect occurs here.
    pub fn create(
        ledger_path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        require_fixture_execution()?;
        let plan_digest = plan.validate()?;
        let ledger = CellSplitLedgerV1::create(ledger_path, plan.clone())?;
        Ok(Self {
            plan,
            plan_digest,
            ledger,
            phase: CellSplitPhaseV1::Prepared,
            last_receipt_digest: plan_digest,
            migration_receipt_digest: None,
            last_migration: None,
            last_route: None,
        })
    }

    /// Recover the exact owner state. The final ledger frame is the only
    /// source of phase truth; callers must replay unfinished callbacks.
    pub fn recover(
        ledger_path: impl AsRef<Path>,
        plan: CellSplitPlanV1,
    ) -> Result<Self, CellSplitExecutionErrorV1> {
        let plan_digest = plan.validate()?;
        let ledger = CellSplitLedgerV1::recover(ledger_path, plan.clone())?;
        let phase = ledger.latest_phase();
        let last_receipt_digest = ledger.last_receipt_digest();
        let migration_receipt_digest = ledger.migration_receipt_digest();
        Ok(Self {
            plan,
            plan_digest,
            ledger,
            phase,
            last_receipt_digest,
            migration_receipt_digest,
            last_migration: None,
            last_route: None,
        })
    }

    pub fn phase(&self) -> CellSplitPhaseV1 {
        self.phase
    }

    pub fn plan(&self) -> &CellSplitPlanV1 {
        &self.plan
    }

    pub fn plan_digest(&self) -> Digest32 {
        self.plan_digest
    }

    pub fn ledger_head_digest(&self) -> Digest32 {
        self.ledger.head_digest()
    }

    /// Digest of the receipt that produced the current durable phase.  This
    /// lets an external recovery coordinator locate the concrete receipt to
    /// replay without treating the digest itself as an operation receipt.
    pub fn last_receipt_digest(&self) -> Digest32 {
        self.last_receipt_digest
    }

    /// Digest of the durable migration receipt, when migration has committed.
    pub fn migration_receipt_digest(&self) -> Option<Digest32> {
        self.migration_receipt_digest
    }

    /// Run one unfinished phase. The caller must provide the real artifact
    /// bytes and the domain owners; no callback is replaced by a bare digest.
    pub fn execute_next<M, R, F>(
        &mut self,
        cas: &FileCellSplitArtifactCasV1,
        artifact_bytes: &[u8],
        migration: &mut M,
        route: &mut R,
        fence: &mut F,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1>
    where
        M: CellSplitStateMigrationOwnerV1,
        R: CellSplitCnsRouteOwnerV1,
        F: CellSplitGenerationFenceOwnerV1,
    {
        require_fixture_execution()?;
        match self.phase {
            CellSplitPhaseV1::Prepared => {
                let receipt = cas.put(&self.plan, artifact_bytes)?;
                let receipt_digest = receipt.validate_for(&self.plan, artifact_bytes.len())?;
                self.advance(CellSplitPhaseV1::ArtifactDurable, receipt_digest)?;
            }
            CellSplitPhaseV1::ArtifactDurable => {
                let snapshot = migration.snapshot(&self.plan)?;
                let receipt_digest = snapshot.validate_for(&self.plan)?;
                self.advance(CellSplitPhaseV1::StateSnapshotted, receipt_digest)?;
            }
            CellSplitPhaseV1::StateSnapshotted => {
                let snapshot = migration.snapshot(&self.plan)?;
                self.resume_with_snapshot(migration, snapshot)?;
            }
            CellSplitPhaseV1::StateMigrated => {
                // Own the replayed receipt before appending any later frame.
                // `advance` mutably borrows the owner, so retaining an
                // `as_ref()` borrow across the route/fence appends is rejected
                // by the borrow checker and would make the recovery path
                // needlessly dependent on callback lifetimes.
                let migration = self.last_migration.clone().ok_or_else(|| {
                    CellSplitExecutionErrorV1::Callback {
                        stage: "state migration replay",
                        message: "recover requires replay_with_receipts".to_string(),
                    }
                })?;
                let route_receipt = route.cutover(&self.plan, &migration)?;
                let route_digest = route_receipt.validate_for(&self.plan)?;
                self.last_route = Some(route_receipt.clone());
                self.advance(CellSplitPhaseV1::RoutePublished, route_digest)?;
                let fence_receipt = fence.fence(&self.plan, &route_receipt)?;
                let fence_digest = fence_receipt.validate_for(&self.plan)?;
                self.advance(CellSplitPhaseV1::GenerationFenced, fence_digest)?;
                let commit_digest = Digest32::of_parts(&[
                    b"hepta.cell-split.ledger-commit.v1\0",
                    self.plan.operation_id.as_str().as_bytes(),
                    migration.digest().as_array(),
                    self.ledger.head_digest().as_array(),
                ]);
                self.advance(CellSplitPhaseV1::LedgerCommitted, commit_digest)?;
                let completion_digest = Digest32::of_parts(&[
                    b"hepta.cell-split.completed.v1\0",
                    self.ledger.head_digest().as_array(),
                ]);
                self.advance(CellSplitPhaseV1::Completed, completion_digest)?;
            }
            CellSplitPhaseV1::MigrationInFlight => {
                return Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired);
            }
            CellSplitPhaseV1::RoutePublished
            | CellSplitPhaseV1::GenerationFenced
            | CellSplitPhaseV1::LedgerCommitted => {
                return Err(CellSplitExecutionErrorV1::Callback {
                    stage: "phase replay",
                    message: "recover requires replay_with_receipts".to_string(),
                });
            }
            CellSplitPhaseV1::Completed | CellSplitPhaseV1::Quarantined => {}
        }
        Ok(self.phase)
    }

    /// Execute the next phase using the artifact already committed to CAS.
    /// This is the restart-safe form of [`Self::execute_next`] for a
    /// coordinator that does not retain the candidate bytes across a process
    /// boundary.
    pub fn execute_next_from_cas<M, R, F>(
        &mut self,
        cas: &FileCellSplitArtifactCasV1,
        migration: &mut M,
        route: &mut R,
        fence: &mut F,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1>
    where
        M: CellSplitStateMigrationOwnerV1,
        R: CellSplitCnsRouteOwnerV1,
        F: CellSplitGenerationFenceOwnerV1,
    {
        if self.phase == CellSplitPhaseV1::Prepared {
            let artifact_bytes = cas.get(&self.plan)?;
            return self.execute_next(cas, &artifact_bytes, migration, route, fence);
        }
        self.execute_next(cas, &[], migration, route, fence)
    }

    /// Continue a recovered owner from a durable snapshot receipt.  A
    /// snapshot is an operation receipt, rather than a caller-supplied digest:
    /// the owner validates its bytes, schema, generation and operation binding
    /// before allowing the migration callback to run.  This is the recovery
    /// path for a process that stopped after `StateSnapshotted` and therefore
    /// cannot safely invent a new snapshot by merely reusing its digest.
    pub fn resume_with_snapshot<M>(
        &mut self,
        migration: &mut M,
        snapshot: CellSplitSnapshotReceiptV1,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1>
    where
        M: CellSplitStateMigrationOwnerV1,
    {
        require_fixture_execution()?;
        if self.phase != CellSplitPhaseV1::StateSnapshotted {
            return Err(CellSplitExecutionErrorV1::InvalidTransition {
                from: self.phase,
                to: CellSplitPhaseV1::StateMigrated,
            });
        }
        let snapshot_digest = snapshot.validate_for(&self.plan)?;
        if snapshot_digest != self.last_receipt_digest {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "replayed state snapshot",
            ));
        }
        // The native effect may commit even if its reply is lost. Persist
        // the intent BEFORE the callback. On recovery require native readback.
        self.advance(
            CellSplitPhaseV1::MigrationInFlight,
            migration_intent_digest(self.plan_digest, snapshot_digest),
        )?;
        let receipt = match migration.migrate(&self.plan, &snapshot) {
            Ok(receipt) => receipt,
            Err(error) => {
                return self.quarantine_after_migration_failure(migration, &snapshot, error);
            }
        };
        let receipt_digest = match receipt.validate_for(&self.plan, &snapshot) {
            Ok(receipt_digest) => receipt_digest,
            Err(error) => {
                return self.quarantine_after_migration_failure(migration, &snapshot, error);
            }
        };
        self.last_migration = Some(receipt);
        self.advance(CellSplitPhaseV1::StateMigrated, receipt_digest)?;
        Ok(self.phase)
    }

    fn quarantine_after_migration_failure<M>(
        &mut self,
        migration: &mut M,
        snapshot: &CellSplitSnapshotReceiptV1,
        error: CellSplitExecutionErrorV1,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1>
    where
        M: CellSplitStateMigrationOwnerV1,
    {
        // A failed/malformed rollback is NOT evidence of rollback. Leave
        // the fsynced MigrationInFlight intent unresolved and non-executable.
        let rollback = migration
            .rollback(&self.plan, snapshot)
            .map_err(|_| CellSplitExecutionErrorV1::MigrationReconciliationRequired)?;
        let rollback_digest = rollback
            .validate_for(&self.plan, snapshot)
            .map_err(|_| CellSplitExecutionErrorV1::MigrationReconciliationRequired)?;
        self.advance(CellSplitPhaseV1::Quarantined, rollback_digest)?;
        Err(error)
    }

    /// Reconcile the original native migration using an independently held
    /// state-owner readback without issuing a second migration Execute.
    /// This reference API does not verify production signatures or enable split.
    pub fn reconcile_migration_with_receipt(
        &mut self,
        snapshot: &CellSplitSnapshotReceiptV1,
        migration: &CellSplitMigrationReceiptV1,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1> {
        require_fixture_execution()?;
        if self.phase != CellSplitPhaseV1::MigrationInFlight {
            return Err(CellSplitExecutionErrorV1::InvalidTransition {
                from: self.phase,
                to: CellSplitPhaseV1::StateMigrated,
            });
        }
        let snapshot_digest = snapshot.validate_for(&self.plan)?;
        if self.last_receipt_digest != migration_intent_digest(self.plan_digest, snapshot_digest) {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "migration intent snapshot",
            ));
        }
        let receipt_digest = migration.validate_for(&self.plan, snapshot)?;
        self.advance(CellSplitPhaseV1::StateMigrated, receipt_digest)?;
        self.last_migration = Some(migration.clone());
        Ok(self.phase)
    }

    /// Require a durable native rollback receipt to reconcile a pending
    /// migration as quarantined. A snapshot digest cannot substitute.
    pub fn reconcile_rollback_with_receipt(
        &mut self,
        snapshot: &CellSplitSnapshotReceiptV1,
        rollback: &CellSplitRollbackReceiptV1,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1> {
        require_fixture_execution()?;
        if self.phase != CellSplitPhaseV1::MigrationInFlight {
            return Err(CellSplitExecutionErrorV1::InvalidTransition {
                from: self.phase,
                to: CellSplitPhaseV1::Quarantined,
            });
        }
        let snapshot_digest = snapshot.validate_for(&self.plan)?;
        if self.last_receipt_digest != migration_intent_digest(self.plan_digest, snapshot_digest) {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "migration intent snapshot",
            ));
        }
        let receipt_digest = rollback.validate_for(&self.plan, snapshot)?;
        self.advance(CellSplitPhaseV1::Quarantined, receipt_digest)?;
        Ok(self.phase)
    }

    /// Advance the route, fence and terminal ledger phases from concrete
    /// receipts retained by the caller after a process restart.
    pub fn advance_with_receipts<R, F>(
        &mut self,
        migration: &CellSplitMigrationReceiptV1,
        route: &mut R,
        fence: &mut F,
    ) -> Result<CellSplitPhaseV1, CellSplitExecutionErrorV1>
    where
        R: CellSplitCnsRouteOwnerV1,
        F: CellSplitGenerationFenceOwnerV1,
    {
        require_fixture_execution()?;
        let migration_digest = migration.validate_for_replayed(&self.plan)?;
        if self.phase == CellSplitPhaseV1::MigrationInFlight {
            return Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired);
        }
        if self.phase == CellSplitPhaseV1::StateSnapshotted {
            return Err(CellSplitExecutionErrorV1::InvalidTransition {
                from: self.phase,
                to: CellSplitPhaseV1::RoutePublished,
            });
        }
        if let Some(expected) = self.migration_receipt_digest {
            if expected != migration_digest {
                return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                    "replayed state migration",
                ));
            }
        }
        if self.phase == CellSplitPhaseV1::StateMigrated {
            self.last_migration = Some(migration.clone());
            let route_receipt = route.cutover(&self.plan, migration)?;
            let route_digest = route_receipt.validate_for(&self.plan)?;
            self.last_route = Some(route_receipt);
            self.advance(CellSplitPhaseV1::RoutePublished, route_digest)?;
        }
        if self.phase == CellSplitPhaseV1::RoutePublished {
            let route_receipt = match self.last_route.as_ref() {
                Some(receipt) => receipt.clone(),
                None => {
                    let receipt = route.cutover(&self.plan, migration)?;
                    let route_digest = receipt.validate_for(&self.plan)?;
                    if route_digest != self.last_receipt_digest {
                        return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                            "replayed CNS route",
                        ));
                    }
                    self.last_route = Some(receipt.clone());
                    receipt
                }
            };
            let fence_receipt = fence.fence(&self.plan, &route_receipt)?;
            let fence_digest = fence_receipt.validate_for(&self.plan)?;
            self.advance(CellSplitPhaseV1::GenerationFenced, fence_digest)?;
        }
        if self.phase == CellSplitPhaseV1::GenerationFenced {
            let commit_digest = Digest32::of_parts(&[
                b"hepta.cell-split.ledger-commit.v1\0",
                self.plan.operation_id.as_str().as_bytes(),
                migration_digest.as_array(),
                self.ledger.head_digest().as_array(),
            ]);
            self.advance(CellSplitPhaseV1::LedgerCommitted, commit_digest)?;
        }
        if self.phase == CellSplitPhaseV1::LedgerCommitted {
            let completion_digest = Digest32::of_parts(&[
                b"hepta.cell-split.completed.v1\0",
                self.ledger.head_digest().as_array(),
            ]);
            self.advance(CellSplitPhaseV1::Completed, completion_digest)?;
        }
        Ok(self.phase)
    }

    fn advance(
        &mut self,
        phase: CellSplitPhaseV1,
        receipt_digest: Digest32,
    ) -> Result<CellSplitLedgerReceiptV1, CellSplitExecutionErrorV1> {
        let receipt = self.ledger.append(phase, receipt_digest)?;
        self.phase = phase;
        self.last_receipt_digest = receipt_digest;
        if phase == CellSplitPhaseV1::StateMigrated {
            self.migration_receipt_digest = Some(receipt_digest);
        }
        Ok(receipt)
    }
}

impl CellSplitMigrationReceiptV1 {
    fn validate_for_replayed(
        &self,
        plan: &CellSplitPlanV1,
    ) -> Result<Digest32, CellSplitExecutionErrorV1> {
        if self.operation_id != plan.operation_id
            || self.source_generation != plan.source_generation
            || self.child_generation != plan.child_generation
            || self.snapshot_digest.is_zero()
            || self.state_partition_digest != plan.state_partition_digest
            || self.verification_digest != plan.migration_verification_digest
            || self.child_state_digest.is_zero()
            || !self.committed
            || self.authority != AuthorityPosture::DENY_ALL
        {
            return Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "replayed state migration",
            ));
        }
        Ok(self.digest())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;
    use tempfile::TempDir;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("id {value}: {error}"))
    }

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn plan(bytes: &[u8]) -> CellSplitPlanV1 {
        CellSplitPlanV1 {
            operation_id: id("split:op:1"),
            source_cell: id("cell:source"),
            child_cell: id("cell:child"),
            source_generation: Generation::new(1)
                .unwrap_or_else(|error| panic!("generation: {error}")),
            child_generation: Generation::new(2)
                .unwrap_or_else(|error| panic!("generation: {error}")),
            artifact_digest: digest(bytes),
            state_schema_digest: digest(b"schema"),
            state_partition_digest: digest(b"partition"),
            migration_verification_digest: digest(b"verification"),
            baseline_route_digest: digest(b"old-route"),
            candidate_route_digest: digest(b"new-route"),
            authority_epoch: 1,
        }
    }

    #[derive(Debug)]
    struct Migration {
        snapshots: AtomicUsize,
        migrations: AtomicUsize,
        rollbacks: AtomicUsize,
    }

    impl CellSplitStateMigrationOwnerV1 for Migration {
        fn snapshot(
            &mut self,
            plan: &CellSplitPlanV1,
        ) -> Result<CellSplitSnapshotReceiptV1, CellSplitExecutionErrorV1> {
            self.snapshots.fetch_add(1, Ordering::SeqCst);
            let bytes = b"real-child-state".to_vec();
            Ok(CellSplitSnapshotReceiptV1 {
                operation_id: plan.operation_id.clone(),
                source_generation: plan.source_generation,
                schema_digest: plan.state_schema_digest,
                snapshot_digest: digest(&bytes),
                bytes,
                authority: AuthorityPosture::DENY_ALL,
            })
        }

        fn migrate(
            &mut self,
            plan: &CellSplitPlanV1,
            snapshot: &CellSplitSnapshotReceiptV1,
        ) -> Result<CellSplitMigrationReceiptV1, CellSplitExecutionErrorV1> {
            self.migrations.fetch_add(1, Ordering::SeqCst);
            Ok(CellSplitMigrationReceiptV1 {
                operation_id: plan.operation_id.clone(),
                source_generation: plan.source_generation,
                child_generation: plan.child_generation,
                snapshot_digest: snapshot.snapshot_digest,
                state_partition_digest: plan.state_partition_digest,
                verification_digest: plan.migration_verification_digest,
                child_state_digest: digest(b"migrated-state"),
                committed: true,
                authority: AuthorityPosture::DENY_ALL,
            })
        }

        fn rollback(
            &mut self,
            plan: &CellSplitPlanV1,
            snapshot: &CellSplitSnapshotReceiptV1,
        ) -> Result<CellSplitRollbackReceiptV1, CellSplitExecutionErrorV1> {
            self.rollbacks.fetch_add(1, Ordering::SeqCst);
            Ok(CellSplitRollbackReceiptV1 {
                operation_id: plan.operation_id.clone(),
                source_generation: plan.source_generation,
                child_generation: plan.child_generation,
                snapshot_digest: snapshot.snapshot_digest,
                restored_state_digest: digest(b"rolled-back-state"),
                durable: true,
                verified: true,
                authority: AuthorityPosture::DENY_ALL,
            })
        }
    }

    #[derive(Debug, Default)]
    struct Route;
    impl CellSplitCnsRouteOwnerV1 for Route {
        fn cutover(
            &mut self,
            plan: &CellSplitPlanV1,
            _migration: &CellSplitMigrationReceiptV1,
        ) -> Result<CellSplitRouteCutoverReceiptV1, CellSplitExecutionErrorV1> {
            Ok(CellSplitRouteCutoverReceiptV1 {
                operation_id: plan.operation_id.clone(),
                source_generation: plan.source_generation,
                child_generation: plan.child_generation,
                predecessor_route_digest: plan.baseline_route_digest,
                published_route_digest: plan.candidate_route_digest,
                published: true,
                authority: AuthorityPosture::DENY_ALL,
            })
        }
    }

    #[derive(Debug, Default)]
    struct Fence;
    impl CellSplitGenerationFenceOwnerV1 for Fence {
        fn fence(
            &mut self,
            plan: &CellSplitPlanV1,
            _route: &CellSplitRouteCutoverReceiptV1,
        ) -> Result<CellSplitGenerationFenceReceiptV1, CellSplitExecutionErrorV1> {
            Ok(CellSplitGenerationFenceReceiptV1 {
                operation_id: plan.operation_id.clone(),
                predecessor_generation: plan.source_generation,
                fenced_generation: plan.child_generation,
                fence_digest: digest(b"fenced"),
                admitted: true,
                authority: AuthorityPosture::DENY_ALL,
            })
        }
    }

    #[test]
    fn file_cas_and_owner_complete_with_durable_receipts() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let ledger_path = directory.path().join("split.ledger");
        let mut owner = CellSplitExecutionOwnerV1::create(&ledger_path, plan.clone())
            .unwrap_or_else(|error| panic!("owner: {error:?}"));
        let mut migration = Migration {
            snapshots: AtomicUsize::new(0),
            migrations: AtomicUsize::new(0),
            rollbacks: AtomicUsize::new(0),
        };
        let mut route = Route;
        let mut fence = Fence;
        while !matches!(owner.phase(), CellSplitPhaseV1::Completed) {
            owner
                .execute_next(&cas, bytes, &mut migration, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("execute: {error:?}"));
        }
        assert_eq!(owner.phase(), CellSplitPhaseV1::Completed);
        assert!(owner.ledger_head_digest() != Digest32::ZERO);
        assert_eq!(migration.migrations.load(Ordering::SeqCst), 1);

        drop(owner);
        let recovered = CellSplitExecutionOwnerV1::recover(&ledger_path, plan)
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        assert_eq!(recovered.phase(), CellSplitPhaseV1::Completed);
    }

    #[test]
    fn recovery_binds_later_phases_to_persisted_migration_receipt() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let ledger_path = directory.path().join("split.ledger");
        let mut owner = CellSplitExecutionOwnerV1::create(&ledger_path, plan.clone())
            .unwrap_or_else(|error| panic!("owner: {error:?}"));
        let mut migration_owner = Migration {
            snapshots: AtomicUsize::new(0),
            migrations: AtomicUsize::new(0),
            rollbacks: AtomicUsize::new(0),
        };
        let mut route = Route;
        let mut fence = Fence;
        for _ in 0..3 {
            owner
                .execute_next(&cas, bytes, &mut migration_owner, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("execute: {error:?}"));
        }
        assert_eq!(owner.phase(), CellSplitPhaseV1::StateMigrated);
        drop(owner);

        let mut recovered = CellSplitExecutionOwnerV1::recover(&ledger_path, plan.clone())
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        let mut wrong = CellSplitMigrationReceiptV1 {
            operation_id: plan.operation_id.clone(),
            source_generation: plan.source_generation,
            child_generation: plan.child_generation,
            snapshot_digest: digest(b"real-child-state"),
            state_partition_digest: plan.state_partition_digest,
            verification_digest: plan.migration_verification_digest,
            child_state_digest: digest(b"different-state"),
            committed: true,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(matches!(
            recovered.advance_with_receipts(&wrong, &mut route, &mut fence),
            Err(CellSplitExecutionErrorV1::InvalidReceipt(
                "replayed state migration"
            ))
        ));
        wrong.child_state_digest = digest(b"migrated-state");
        assert_eq!(
            recovered
                .advance_with_receipts(&wrong, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("replay: {error:?}")),
            CellSplitPhaseV1::Completed
        );
    }

    #[test]
    fn recovered_snapshot_requires_the_concrete_receipt_before_migration() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let ledger_path = directory.path().join("split.ledger");
        let mut owner = CellSplitExecutionOwnerV1::create(&ledger_path, plan.clone())
            .unwrap_or_else(|error| panic!("owner: {error:?}"));
        let mut migration = Migration {
            snapshots: AtomicUsize::new(0),
            migrations: AtomicUsize::new(0),
            rollbacks: AtomicUsize::new(0),
        };
        let mut route = Route;
        let mut fence = Fence;
        owner
            .execute_next(&cas, bytes, &mut migration, &mut route, &mut fence)
            .unwrap_or_else(|error| panic!("artifact: {error:?}"));
        owner
            .execute_next(&cas, bytes, &mut migration, &mut route, &mut fence)
            .unwrap_or_else(|error| panic!("snapshot: {error:?}"));
        assert_eq!(owner.phase(), CellSplitPhaseV1::StateSnapshotted);

        // The snapshot is a concrete callback receipt retained by the state
        // owner. A restarted owner can resume migration without inventing a
        // fresh state snapshot from its digest alone.
        let snapshot_bytes = b"real-child-state".to_vec();
        let snapshot = CellSplitSnapshotReceiptV1 {
            operation_id: plan.operation_id.clone(),
            source_generation: plan.source_generation,
            schema_digest: plan.state_schema_digest,
            snapshot_digest: digest(&snapshot_bytes),
            bytes: snapshot_bytes,
            authority: AuthorityPosture::DENY_ALL,
        };
        drop(owner);
        let mut recovered = CellSplitExecutionOwnerV1::recover(&ledger_path, plan)
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        recovered
            .resume_with_snapshot(&mut migration, snapshot)
            .unwrap_or_else(|error| panic!("resume migration: {error:?}"));
        while !matches!(recovered.phase(), CellSplitPhaseV1::Completed) {
            recovered
                .execute_next(&cas, bytes, &mut migration, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("complete: {error:?}"));
        }
        assert_eq!(migration.migrations.load(Ordering::SeqCst), 1);
    }

    #[cfg(unix)]
    #[test]
    fn cas_rejects_existing_symlink_object() {
        use std::os::unix::fs::symlink;

        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let cas_root = directory.path().join("cas");
        let cas = FileCellSplitArtifactCasV1::open(&cas_root)
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let outside = directory.path().join("outside");
        fs::write(&outside, bytes).unwrap_or_else(|error| panic!("outside: {error}"));
        symlink(&outside, cas_root.join(plan.artifact_digest.to_string()))
            .unwrap_or_else(|error| panic!("symlink: {error}"));
        assert!(matches!(
            cas.put(&plan, bytes),
            Err(CellSplitExecutionErrorV1::Io(io::ErrorKind::InvalidData))
        ));
    }

    #[test]
    fn cas_recovers_a_torn_staging_object_before_publish() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let cas_root = directory.path().join("cas");
        let cas = FileCellSplitArtifactCasV1::open(&cas_root)
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let temporary = cas_root.join(format!(
            ".{}.{}.tmp",
            plan.artifact_digest, plan.operation_id
        ));
        fs::write(&temporary, b"torn-before-rename")
            .unwrap_or_else(|error| panic!("temporary: {error}"));
        cas.put(&plan, bytes)
            .unwrap_or_else(|error| panic!("put after torn staging: {error:?}"));
        assert_eq!(
            cas.get(&plan)
                .unwrap_or_else(|error| panic!("get: {error:?}")),
            bytes.to_vec()
        );
        assert!(!temporary.exists());
    }

    #[test]
    fn recovery_rejects_a_validly_hashed_but_out_of_order_phase() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let plan = plan(b"candidate-artifact");
        let path = directory.path().join("split.ledger");
        let ledger = CellSplitLedgerV1::create(&path, plan.clone())
            .unwrap_or_else(|error| panic!("create: {error:?}"));
        drop(ledger);
        let plan_digest = plan
            .validate()
            .unwrap_or_else(|error| panic!("plan: {error:?}"));
        let mut record = LedgerRecordV1 {
            sequence: 1,
            operation_id: plan.operation_id.clone(),
            plan_digest,
            phase: CellSplitPhaseV1::Completed,
            receipt_digest: digest(b"receipt"),
            previous_record_digest: Digest32::ZERO,
            record_digest: Digest32::ZERO,
        };
        record.record_digest = record_digest(&record);
        let encoded = serde_json::to_vec(&PersistedLedgerRecordV1::from(&record))
            .unwrap_or_else(|error| panic!("encode: {error}"));
        let mut file = OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap_or_else(|error| panic!("open: {error}"));
        file.write_all(&encoded)
            .and_then(|()| file.write_all(b"\n"))
            .unwrap_or_else(|error| panic!("append: {error}"));
        drop(file);
        assert!(matches!(
            CellSplitLedgerV1::recover(&path, plan),
            Err(CellSplitExecutionErrorV1::CorruptJournal)
        ));
    }

    #[test]
    fn torn_tail_is_truncated_but_bad_complete_record_is_rejected() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let path = directory.path().join("split.ledger");
        let mut ledger = CellSplitLedgerV1::create(&path, plan.clone())
            .unwrap_or_else(|error| panic!("create: {error:?}"));
        ledger
            .append(CellSplitPhaseV1::ArtifactDurable, digest(b"cas-receipt"))
            .unwrap_or_else(|error| panic!("append: {error:?}"));
        drop(ledger);
        let mut file = OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap_or_else(|error| panic!("open: {error}"));
        file.write_all(b"{\"truncated\":true}")
            .unwrap_or_else(|error| panic!("tail: {error}"));
        drop(file);
        let recovered = CellSplitLedgerV1::recover(&path, plan.clone())
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        assert_eq!(recovered.sequence(), 1);
        drop(recovered);
        let mut file = OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap_or_else(|error| panic!("open: {error}"));
        file.write_all(b"{}\n")
            .unwrap_or_else(|error| panic!("record: {error}"));
        drop(file);
        assert!(matches!(
            CellSplitLedgerV1::recover(&path, plan),
            Err(CellSplitExecutionErrorV1::CorruptJournal)
        ));
    }

    #[derive(Clone, Copy, Debug)]
    enum RollbackMode {
        Unavailable,
        Malformed,
        Verified,
    }

    #[derive(Debug)]
    struct LostMigrationReply {
        inner: Migration,
        rollback_mode: RollbackMode,
    }

    impl CellSplitStateMigrationOwnerV1 for LostMigrationReply {
        fn snapshot(
            &mut self,
            plan: &CellSplitPlanV1,
        ) -> Result<CellSplitSnapshotReceiptV1, CellSplitExecutionErrorV1> {
            self.inner.snapshot(plan)
        }

        fn migrate(
            &mut self,
            _plan: &CellSplitPlanV1,
            _snapshot: &CellSplitSnapshotReceiptV1,
        ) -> Result<CellSplitMigrationReceiptV1, CellSplitExecutionErrorV1> {
            // The native owner may have committed before the response was lost.
            self.inner.migrations.fetch_add(1, Ordering::SeqCst);
            Err(CellSplitExecutionErrorV1::Callback {
                stage: "migration",
                message: "original native effect may have committed".to_string(),
            })
        }

        fn rollback(
            &mut self,
            plan: &CellSplitPlanV1,
            snapshot: &CellSplitSnapshotReceiptV1,
        ) -> Result<CellSplitRollbackReceiptV1, CellSplitExecutionErrorV1> {
            if matches!(self.rollback_mode, RollbackMode::Unavailable) {
                self.inner.rollbacks.fetch_add(1, Ordering::SeqCst);
                return Err(CellSplitExecutionErrorV1::Callback {
                    stage: "rollback",
                    message: "durable rollback readback unavailable".to_string(),
                });
            }
            let mut receipt = self.inner.rollback(plan, snapshot)?;
            if matches!(self.rollback_mode, RollbackMode::Malformed) {
                receipt.verified = false;
            }
            Ok(receipt)
        }
    }

    fn lost_reply_owner(mode: RollbackMode) -> LostMigrationReply {
        LostMigrationReply {
            inner: Migration {
                snapshots: AtomicUsize::new(0),
                migrations: AtomicUsize::new(0),
                rollbacks: AtomicUsize::new(0),
            },
            rollback_mode: mode,
        }
    }

    fn native_snapshot(plan: &CellSplitPlanV1) -> CellSplitSnapshotReceiptV1 {
        let bytes = b"real-child-state".to_vec();
        CellSplitSnapshotReceiptV1 {
            operation_id: plan.operation_id.clone(),
            source_generation: plan.source_generation,
            schema_digest: plan.state_schema_digest,
            snapshot_digest: digest(&bytes),
            bytes,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn missing_or_malformed_rollback_never_invents_quarantine_or_reexecutes_migration() {
        for mode in [RollbackMode::Unavailable, RollbackMode::Malformed] {
            let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
            let bytes = b"candidate-artifact";
            let plan = plan(bytes);
            let path = directory.path().join("split.ledger");
            let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
                .unwrap_or_else(|error| panic!("cas: {error:?}"));
            let mut owner = CellSplitExecutionOwnerV1::create(&path, plan.clone())
                .unwrap_or_else(|error| panic!("owner: {error:?}"));
            let mut original = lost_reply_owner(mode);
            let mut route = Route;
            let mut fence = Fence;
            for _ in 0..2 {
                owner
                    .execute_next(&cas, bytes, &mut original, &mut route, &mut fence)
                    .unwrap_or_else(|error| panic!("prepare: {error:?}"));
            }
            assert_eq!(owner.phase(), CellSplitPhaseV1::StateSnapshotted);
            let snapshot = native_snapshot(&plan);
            assert!(matches!(
                owner.resume_with_snapshot(&mut original, snapshot.clone()),
                Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired)
            ));
            assert_eq!(owner.phase(), CellSplitPhaseV1::MigrationInFlight);
            assert_eq!(original.inner.migrations.load(Ordering::SeqCst), 1);
            assert_eq!(original.inner.rollbacks.load(Ordering::SeqCst), 1);
            drop(owner);

            let mut recovered = CellSplitExecutionOwnerV1::recover(&path, plan.clone())
                .unwrap_or_else(|error| panic!("recover: {error:?}"));
            assert_eq!(recovered.phase(), CellSplitPhaseV1::MigrationInFlight);
            assert!(matches!(
                recovered.execute_next(&cas, bytes, &mut original, &mut route, &mut fence),
                Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired)
            ));
            assert_eq!(original.inner.migrations.load(Ordering::SeqCst), 1);
            let readback = CellSplitMigrationReceiptV1 {
                operation_id: plan.operation_id.clone(),
                source_generation: plan.source_generation,
                child_generation: plan.child_generation,
                snapshot_digest: snapshot.snapshot_digest,
                state_partition_digest: plan.state_partition_digest,
                verification_digest: plan.migration_verification_digest,
                child_state_digest: digest(b"native-committed-child"),
                committed: true,
                authority: AuthorityPosture::DENY_ALL,
            };
            assert!(matches!(
                recovered.advance_with_receipts(&readback, &mut route, &mut fence),
                Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired)
            ));
            let mut wrong_snapshot = snapshot.clone();
            wrong_snapshot.bytes = b"different-state".to_vec();
            wrong_snapshot.snapshot_digest = digest(&wrong_snapshot.bytes);
            assert!(matches!(
                recovered.reconcile_migration_with_receipt(&wrong_snapshot, &readback),
                Err(CellSplitExecutionErrorV1::InvalidReceipt(
                    "migration intent snapshot"
                ))
            ));
            assert_eq!(recovered.phase(), CellSplitPhaseV1::MigrationInFlight);
            assert_eq!(
                recovered
                    .reconcile_migration_with_receipt(&snapshot, &readback)
                    .unwrap_or_else(|error| panic!("verified readback: {error:?}")),
                CellSplitPhaseV1::StateMigrated
            );
            assert_eq!(original.inner.migrations.load(Ordering::SeqCst), 1);
            drop(recovered);
            let reopened = CellSplitExecutionOwnerV1::recover(&path, plan)
                .unwrap_or_else(|error| panic!("final reopen: {error:?}"));
            assert_eq!(reopened.phase(), CellSplitPhaseV1::StateMigrated);
        }
    }

    #[test]
    fn only_a_distinct_verified_rollback_receipt_can_quarantine_pending_migration() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let path = directory.path().join("split.ledger");
        let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let mut owner = CellSplitExecutionOwnerV1::create(&path, plan.clone())
            .unwrap_or_else(|error| panic!("owner: {error:?}"));
        let mut original = lost_reply_owner(RollbackMode::Unavailable);
        let mut route = Route;
        let mut fence = Fence;
        for _ in 0..2 {
            owner
                .execute_next(&cas, bytes, &mut original, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("prepare: {error:?}"));
        }
        let snapshot = native_snapshot(&plan);
        assert!(matches!(
            owner.resume_with_snapshot(&mut original, snapshot.clone()),
            Err(CellSplitExecutionErrorV1::MigrationReconciliationRequired)
        ));
        drop(owner);
        let mut recovered = CellSplitExecutionOwnerV1::recover(&path, plan.clone())
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        let mut verified = CellSplitRollbackReceiptV1 {
            operation_id: plan.operation_id.clone(),
            source_generation: plan.source_generation,
            child_generation: plan.child_generation,
            snapshot_digest: snapshot.snapshot_digest,
            restored_state_digest: digest(b"native-restored-state"),
            durable: true,
            verified: true,
            authority: AuthorityPosture::DENY_ALL,
        };
        verified.verified = false;
        assert!(matches!(
            recovered.reconcile_rollback_with_receipt(&snapshot, &verified),
            Err(CellSplitExecutionErrorV1::InvalidReceipt("state rollback"))
        ));
        assert_eq!(recovered.phase(), CellSplitPhaseV1::MigrationInFlight);
        verified.verified = true;
        let expected = verified
            .validate_for(&plan, &snapshot)
            .unwrap_or_else(|error| panic!("rollback receipt: {error:?}"));
        assert_eq!(
            recovered
                .reconcile_rollback_with_receipt(&snapshot, &verified)
                .unwrap_or_else(|error| panic!("verified rollback: {error:?}")),
            CellSplitPhaseV1::Quarantined
        );
        assert_eq!(recovered.last_receipt_digest(), expected);
        assert_ne!(recovered.last_receipt_digest(), snapshot.digest());
        drop(recovered);
        let reopened = CellSplitExecutionOwnerV1::recover(&path, plan)
            .unwrap_or_else(|error| panic!("reopen: {error:?}"));
        assert_eq!(reopened.phase(), CellSplitPhaseV1::Quarantined);
    }

    #[test]
    fn verified_rollback_callback_uses_rollback_receipt_instead_of_snapshot_digest() {
        let directory = TempDir::new().unwrap_or_else(|error| panic!("tempdir: {error}"));
        let bytes = b"candidate-artifact";
        let plan = plan(bytes);
        let path = directory.path().join("split.ledger");
        let cas = FileCellSplitArtifactCasV1::open(directory.path().join("cas"))
            .unwrap_or_else(|error| panic!("cas: {error:?}"));
        let mut owner = CellSplitExecutionOwnerV1::create(&path, plan.clone())
            .unwrap_or_else(|error| panic!("owner: {error:?}"));
        let mut original = lost_reply_owner(RollbackMode::Verified);
        let mut route = Route;
        let mut fence = Fence;
        for _ in 0..2 {
            owner
                .execute_next(&cas, bytes, &mut original, &mut route, &mut fence)
                .unwrap_or_else(|error| panic!("prepare: {error:?}"));
        }
        let snapshot = native_snapshot(&plan);
        assert!(matches!(
            owner.resume_with_snapshot(&mut original, snapshot.clone()),
            Err(CellSplitExecutionErrorV1::Callback {
                stage: "migration",
                ..
            })
        ));
        assert_eq!(owner.phase(), CellSplitPhaseV1::Quarantined);
        assert_ne!(owner.last_receipt_digest(), snapshot.digest());
        assert_eq!(original.inner.migrations.load(Ordering::SeqCst), 1);
        assert_eq!(original.inner.rollbacks.load(Ordering::SeqCst), 1);
        drop(owner);
        let recovered = CellSplitExecutionOwnerV1::recover(&path, plan)
            .unwrap_or_else(|error| panic!("recover: {error:?}"));
        assert_eq!(recovered.phase(), CellSplitPhaseV1::Quarantined);
    }
}
