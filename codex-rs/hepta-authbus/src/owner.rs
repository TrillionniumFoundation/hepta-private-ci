use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

#[cfg(unix)]
use std::os::unix::fs::MetadataExt;
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Serialize;
use tokio::sync::Mutex;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityHost;
use crate::AuthBusAuthorityStore;
use crate::AuthPolicy;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRegistration;
use crate::IssuerRetirement;
use crate::IssuerSpec;
use crate::PolicyDecision;
use crate::PolicySpec;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::Settlement;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const WRITER_LEASE_SCHEMA_VERSION: u32 = 1;
const MAX_CONTROL_FILE_BYTES: u64 = 4096;

macro_rules! serialized_mutation {
    ($port:expr, $call:expr) => {{
        let _guard = $port.owner.writer.lock().await;
        $port.owner.lease.assert_current()?;
        let result = $call.await;
        $port.owner.lease.assert_current()?;
        result
    }};
}

/// The only public constructor for the durable AuthBus authority owner.
///
/// The lower-level SQLite store and checkpoint host stay crate-private. Every
/// mutation is serialized through this owner, holds a process-external writer
/// lease, and completes checkpoint publication before returning.
pub struct AuthBusAuthorityOwner {
    pub(crate) host: AuthBusAuthorityHost,
    writer: Mutex<()>,
    lease: AuthorityWriterLease,
}

impl AuthBusAuthorityOwner {
    /// Open an already-bootstrapped authority owner.
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let lease = AuthorityWriterLease::acquire(&checkpoint_path, database_path, owner_id)?;
        let host = match AuthBusAuthorityHost::open(database_path, checkpoint_path, owner_id).await {
            Ok(host) => host,
            Err(error) => {
                drop(lease);
                return Err(error);
            }
        };
        if let Err(error) = validate_database_files(database_path) {
            drop(host);
            drop(lease);
            return Err(error);
        }
        Ok(Self {
            host,
            writer: Mutex::new(()),
            lease,
        })
    }

    /// Bootstrap a brand-new database and its independently retained checkpoint.
    ///
    /// This intentionally refuses to adopt an existing database. Restore and
    /// migration workflows must verify an existing witness rather than minting a
    /// new generation for unknown state.
    pub async fn bootstrap_new(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner_id(owner_id)?;
        validate_separate_private_parents(database_path, &checkpoint_path)?;
        if database_path.exists() || checkpoint_path.exists() {
            return Err(AuthBusAuthorityError::AlreadyExists);
        }

        prepare_new_database_file(database_path)?;
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let frontier = store.authority_frontier_digest().await?;
        drop(store);
        write_initial_checkpoint(
            &checkpoint_path,
            owner_id,
            crate::AuthorityCheckpoint {
                generation: 1,
                digest: frontier,
            },
        )?;
        Self::open(database_path, checkpoint_path, owner_id).await
    }

    #[must_use]
    pub fn admin(&self) -> AuthBusAdminPort<'_> {
        AuthBusAdminPort { owner: self }
    }

    #[must_use]
    pub fn effects(&self) -> AuthBusEffectPort<'_> {
        AuthBusEffectPort { owner: self }
    }

    #[must_use]
    pub fn read(&self) -> AuthBusReadPort<'_> {
        AuthBusReadPort { owner: self }
    }
}

#[derive(Clone, Copy)]
pub struct AuthBusAdminPort<'a> {
    owner: &'a AuthBusAuthorityOwner,
}

impl AuthBusAdminPort<'_> {
    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.enroll_issuer(purpose, spec))
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .rotate_issuer(purpose, spec, expected_epoch, expected_revision)
        )
    }

    pub async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .revoke_issuer(purpose, issuer_id, key_epoch, expected_revision)
        )
    }

    pub async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner.host.retire_issuer_epoch(
                purpose,
                issuer_id,
                key_epoch,
                expected_revision
            )
        )
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.create_policy(spec, time))
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .replace_policy(spec, expected_revision, time)
        )
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .revoke_policy(policy_id, expected_revision, time)
        )
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .retire_policy(policy_id, expected_revision, retired_at_ms)
        )
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.create_quota(spec, time))
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner.host.replace_quota(spec, expected_revision, time)
        )
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .compact_terminal_reservations(older_than_ms, limit)
        )
    }

    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.sync_checkpoint())
    }
}

#[derive(Clone, Copy)]
pub struct AuthBusEffectPort<'a> {
    owner: &'a AuthBusAuthorityOwner,
}

impl AuthBusEffectPort<'_> {
    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner.host.observe_trusted_time_attestation(attestation)
        )
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .authorize(principal, action, scope_digest, policy_revision, time)
        )
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.reserve(decision, request, time))
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner.host.mark_dispatch_attempted(
                reservation_id,
                expected_revision,
                dispatch_digest,
                time
            )
        )
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .mark_indeterminate(reservation_id, expected_revision, time)
        )
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner
                .host
                .cancel_reservation(reservation_id, expected_revision, time)
        )
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        serialized_mutation!(
            self,
            self.owner.host.reconcile_expired_reservation(
                reservation_id,
                expected_revision,
                time
            )
        )
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        serialized_mutation!(self, self.owner.host.settle(evidence, time))
    }
}

#[derive(Clone, Copy)]
pub struct AuthBusReadPort<'a> {
    owner: &'a AuthBusAuthorityOwner,
}

impl AuthBusReadPort<'_> {
    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.owner.lease.assert_current()?;
        self.owner.host.message_issuer(issuer_id, key_epoch).await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.owner.lease.assert_current()?;
        self.owner.host.quota_snapshot(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.owner.lease.assert_current()?;
        self.owner.host.reservation(reservation_id).await
    }
}

#[derive(Serialize)]
struct CheckpointDocument<'a> {
    schema_version: u32,
    owner_id: &'a str,
    generation: u64,
    digest: String,
}

#[derive(Serialize)]
struct WriterLeaseDocument<'a> {
    schema_version: u32,
    owner_id: &'a str,
    process_id: u32,
    database_path_digest: String,
    checkpoint_path_digest: String,
}

struct AuthorityWriterLease {
    file: File,
    path: PathBuf,
    payload: Vec<u8>,
}

impl AuthorityWriterLease {
    fn acquire(
        checkpoint_path: &Path,
        database_path: &Path,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        validate_owner_id(owner_id)?;
        validate_separate_private_parents(database_path, checkpoint_path)?;
        let path = writer_lock_path(checkpoint_path)?;
        let document = WriterLeaseDocument {
            schema_version: WRITER_LEASE_SCHEMA_VERSION,
            owner_id,
            process_id: std::process::id(),
            database_path_digest: Digest32::of_bytes(
                database_path.to_string_lossy().as_bytes(),
            )
            .to_string(),
            checkpoint_path_digest: Digest32::of_bytes(
                checkpoint_path.to_string_lossy().as_bytes(),
            )
            .to_string(),
        };
        let payload =
            serde_json::to_vec(&document).map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if payload.len() as u64 > MAX_CONTROL_FILE_BYTES {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }

        let mut file = create_writer_lock(&path)?;

        file.write_all(&payload)
            .and_then(|()| file.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        sync_parent(&path)?;
        let lease = Self {
            file,
            path,
            payload,
        };
        if let Err(error) = lease.assert_current() {
            let _ = std::fs::remove_file(&lease.path);
            return Err(error);
        }
        Ok(lease)
    }

    #[cfg(unix)]
    fn assert_current(&self) -> Result<(), AuthBusAuthorityError> {
        let path_metadata = std::fs::symlink_metadata(&self.path)
            .map_err(|_| AuthBusAuthorityError::WriterLeaseLost)?;
        let file_metadata = self
            .file
            .metadata()
            .map_err(|_| AuthBusAuthorityError::WriterLeaseLost)?;
        let identity = |metadata: &std::fs::Metadata| {
            (
                metadata.dev(),
                metadata.ino(),
                metadata.uid(),
                metadata.nlink(),
                metadata.mode(),
            )
        };
        if !path_metadata.is_file()
            || path_metadata.nlink() != 1
            || path_metadata.mode() & 0o077 != 0
            || identity(&path_metadata) != identity(&file_metadata)
            || path_metadata.len() > MAX_CONTROL_FILE_BYTES
            || self
                .path
                .canonicalize()
                .map_err(|_| AuthBusAuthorityError::WriterLeaseLost)?
                != self.path
        {
            return Err(AuthBusAuthorityError::WriterLeaseLost);
        }
        let mut bytes = Vec::new();
        File::open(&self.path)
            .and_then(|mut file| {
                std::io::Read::by_ref(&mut file)
                    .take(MAX_CONTROL_FILE_BYTES + 1)
                    .read_to_end(&mut bytes)
            })
            .map_err(|_| AuthBusAuthorityError::WriterLeaseLost)?;
        if bytes != self.payload {
            return Err(AuthBusAuthorityError::WriterLeaseLost);
        }
        Ok(())
    }

    #[cfg(not(unix))]
    fn assert_current(&self) -> Result<(), AuthBusAuthorityError> {
        Err(AuthBusAuthorityError::WriterLeaseLost)
    }
}

impl Drop for AuthorityWriterLease {
    fn drop(&mut self) {
        if self.assert_current().is_ok() {
            let _ = std::fs::remove_file(&self.path);
            let _ = sync_parent(&self.path);
        }
    }
}

#[cfg(unix)]
fn create_writer_lock(path: &Path) -> Result<File, AuthBusAuthorityError> {
    match OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(path)
    {
        Ok(file) => Ok(file),
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
            Err(AuthBusAuthorityError::WriterLeaseHeld)
        }
        Err(error) => Err(AuthBusAuthorityError::Storage(error.to_string())),
    }
}

#[cfg(not(unix))]
fn create_writer_lock(_path: &Path) -> Result<File, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn validate_owner_id(owner_id: &str) -> Result<(), AuthBusAuthorityError> {
    if owner_id.is_empty() || owner_id.len() > 256 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(unix)]
fn validate_separate_private_parents(
    database_path: &Path,
    checkpoint_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    if !database_path.is_absolute() || !checkpoint_path.is_absolute() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let database_parent = private_parent(database_path)?;
    let checkpoint_parent = private_parent(checkpoint_path)?;
    if database_parent == checkpoint_parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_separate_private_parents(
    _database_path: &Path,
    _checkpoint_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn private_parent(path: &Path) -> Result<PathBuf, AuthBusAuthorityError> {
    let raw_parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let parent = raw_parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if parent != raw_parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let metadata = std::fs::metadata(&parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(parent)
}

#[cfg(unix)]
fn prepare_new_database_file(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.sync_all()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    sync_parent(path)
}

#[cfg(not(unix))]
fn prepare_new_database_file(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_database_files(database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    validate_private_regular_file(database_path)?;
    let raw = database_path.to_string_lossy();
    for suffix in ["-wal", "-shm"] {
        let path = PathBuf::from(format!("{raw}{suffix}"));
        if path.exists() {
            validate_private_regular_file(&path)?;
        }
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_database_files(_database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_private_regular_file(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let parent = private_parent(path)?;
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let parent_metadata = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != parent_metadata.uid()
        || metadata.mode() & 0o077 != 0
        || path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

fn writer_lock_path(checkpoint_path: &Path) -> Result<PathBuf, AuthBusAuthorityError> {
    let parent = checkpoint_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let name = checkpoint_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    Ok(parent.join(format!(".{name}.writer.lock")))
}

#[cfg(unix)]
fn write_initial_checkpoint(
    path: &Path,
    owner_id: &str,
    checkpoint: crate::AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    if checkpoint.generation == 0 || checkpoint.digest.is_zero() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let payload = serde_json::to_vec(&CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        owner_id,
        generation: checkpoint.generation,
        digest: checkpoint.digest.to_string(),
    })
    .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
    if payload.len() as u64 > MAX_CONTROL_FILE_BYTES {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                AuthBusAuthorityError::AlreadyExists
            } else {
                AuthBusAuthorityError::Storage(error.to_string())
            }
        })?;
    let result = file
        .write_all(&payload)
        .and_then(|()| file.sync_all())
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()));
    if result.is_err() {
        let _ = std::fs::remove_file(path);
        return result;
    }
    sync_parent(path)
}

#[cfg(not(unix))]
fn write_initial_checkpoint(
    _path: &Path,
    _owner_id: &str,
    _checkpoint: crate::AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn sync_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))
}

#[cfg(all(test, unix))]
#[path = "owner_tests.rs"]
mod tests;
