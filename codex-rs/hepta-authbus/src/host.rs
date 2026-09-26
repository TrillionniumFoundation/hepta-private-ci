use std::path::Path;
use std::path::PathBuf;

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthPolicy;
use crate::ExpiredReservationSweepReport;
use crate::AuthorityCheckpoint;
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
use crate::owner_lock::AuthorityOwnerLock;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;
const RECOVERY_BATCH: u32 = 256;

pub struct AuthBusAuthorityHost {
    store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpointFile,
    _owner_lock: AuthorityOwnerLock,
}

impl AuthBusAuthorityHost {
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let owner_lock = AuthorityOwnerLock::acquire(database_path, owner_id)?;
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let initial = AuthorityCheckpoint {
            generation: 1,
            digest: store.authority_frontier_digest().await?,
        };
        let (checkpoint, external) = AuthorityCheckpointFile::open_or_create(
            checkpoint_path,
            database_path,
            owner_id,
            initial,
        )?;
        match store.authority_checkpoint().await? {
            None => store.initialize_authority_checkpoint(external).await?,
            Some(_) => {
                if let Some(next) = store.reconcile_authority_checkpoint(external).await? {
                    checkpoint.replace(external, next)?;
                    store
                        .advance_authority_checkpoint(external.generation, next)
                        .await?;
                }
            }
        }
        while !store.reconcile_after_restart(RECOVERY_BATCH).await? {}
        let host = Self {
            store,
            checkpoint,
            _owner_lock: owner_lock,
        };
        host.sync_checkpoint().await?;
        Ok(host)
    }

    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let external = self.checkpoint.read()?;
        if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
            self.checkpoint.replace(external, next)?;
            self.store
                .advance_authority_checkpoint(external.generation, next)
                .await?;
        }
        Ok(())
    }

    async fn finish<T>(
        &self,
        result: Result<T, AuthBusAuthorityError>,
    ) -> Result<T, AuthBusAuthorityError> {
        self.sync_checkpoint().await?;
        result
    }

    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let result = self.store.enroll_issuer(purpose, spec).await;
        self.finish(result).await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let result = self
            .store
            .rotate_issuer(purpose, spec, expected_epoch, expected_revision)
            .await;
        self.finish(result).await
    }

    pub async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let result = self
            .store
            .revoke_issuer(purpose, issuer_id, key_epoch, expected_revision)
            .await;
        self.finish(result).await
    }

    pub async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        let result = self
            .store
            .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
            .await;
        self.finish(result).await
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        let result = self
            .store
            .observe_trusted_time_attestation(attestation)
            .await;
        self.finish(result).await
    }

    pub async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.store.message_issuer(issuer_id, key_epoch).await
    }

    pub async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let result = self.store.create_policy(spec, time).await;
        self.finish(result).await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let result = self
            .store
            .replace_policy(spec, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        let result = self
            .store
            .revoke_policy(policy_id, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        let result = self
            .store
            .retire_policy(policy_id, expected_revision, retired_at_ms)
            .await;
        self.finish(result).await
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        let result = self
            .store
            .authorize(principal, action, scope_digest, policy_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let result = self.store.create_quota(spec, time).await;
        self.finish(result).await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        let result = self
            .store
            .replace_quota(spec, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let result = self.store.reserve(decision, request, time).await;
        self.finish(result).await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let result = self
            .store
            .mark_dispatch_attempted(reservation_id, expected_revision, dispatch_digest, time)
            .await;
        self.finish(result).await
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let result = self
            .store
            .mark_indeterminate(reservation_id, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let result = self
            .store
            .cancel_reservation(reservation_id, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        let result = self
            .store
            .reconcile_expired_reservation(reservation_id, expected_revision, time)
            .await;
        self.finish(result).await
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        let result = self.store.settle(evidence, time).await;
        self.finish(result).await
    }

    pub async fn sweep_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweepReport, AuthBusAuthorityError> {
        let result = self.store.sweep_expired_reservations(time, limit).await;
        self.finish(result).await
    }

    pub async fn authority_frontier_digest(&self) -> Result<Digest32, AuthBusAuthorityError> {
        self.store.authority_frontier_digest().await
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        let result = self
            .store
            .compact_terminal_reservations(older_than_ms, limit)
            .await;
        self.finish(result).await
    }

    pub async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.store.quota_snapshot(quota_key).await
    }

    pub async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.store.reservation(reservation_id).await
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct CheckpointDocument {
    schema_version: u32,
    owner_id: String,
    generation: u64,
    digest: String,
}

struct AuthorityCheckpointFile {
    path: PathBuf,
    owner_id: String,
}

impl AuthorityCheckpointFile {
    fn open_or_create(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
        initial: AuthorityCheckpoint,
    ) -> Result<(Self, AuthorityCheckpoint), AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        validate_checkpoint_parent(&path, database_path)?;
        if !path.exists() {
            if initial.generation != 1 || initial.digest.is_zero() {
                return Err(AuthBusAuthorityError::UnsafeCheckpoint);
            }
            write_private_atomic(&path, owner_id, initial)?;
        }
        validate_path(&path, database_path)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        let checkpoint = file.read()?;
        Ok((file, checkpoint))
    }

    fn read(&self) -> Result<AuthorityCheckpoint, AuthBusAuthorityError> {
        let bytes = read_private_file(&self.path)?;
        let document: CheckpointDocument =
            serde_json::from_slice(&bytes).map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if document.schema_version != CHECKPOINT_SCHEMA_VERSION
            || document.owner_id != self.owner_id
            || document.generation == 0
        {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        let digest = document
            .digest
            .parse::<Digest32>()
            .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
        if digest.is_zero() {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(AuthorityCheckpoint {
            generation: document.generation,
            digest,
        })
    }

    fn replace(
        &self,
        expected: AuthorityCheckpoint,
        next: AuthorityCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        let current = self.read()?;
        if current == next {
            return Ok(());
        }
        if current != expected
            || next.generation
                != expected
                    .generation
                    .checked_add(1)
                    .ok_or(AuthBusAuthorityError::CapacityExceeded)?
            || next.digest.is_zero()
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        write_private_atomic(&self.path, &self.owner_id, next)?;
        if self.read()? != next {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        Ok(())
    }
}

#[cfg(unix)]
fn validate_checkpoint_parent(
    path: &Path,
    database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || !database_path.is_absolute() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let db_parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let directory = std::fs::metadata(&parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if parent == db_parent || !directory.is_dir() || directory.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_checkpoint_parent(
    _path: &Path,
    _database_path: &Path,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_path(path: &Path, database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() || !database_path.is_absolute() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let db_parent = database_path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let parent = parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let db_parent = db_parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if parent == db_parent {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let directory = std::fs::metadata(&parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !directory.is_dir() || directory.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let file = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if !file.is_file()
        || file.nlink() != 1
        || file.uid() != directory.uid()
        || file.mode() & 0o077 != 0
        || file.len() > MAX_CHECKPOINT_BYTES
        || path
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?
            != path
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(not(unix))]
fn validate_path(_path: &Path, _database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn read_private_file(path: &Path) -> Result<Vec<u8>, AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    let before = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let mut file =
        File::open(path).map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let opened = file
        .metadata()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let mut bytes = Vec::new();
    std::io::Read::by_ref(&mut file)
        .take(MAX_CHECKPOINT_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let after = std::fs::symlink_metadata(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if bytes.len() as u64 > MAX_CHECKPOINT_BYTES
        || identity(&after) != identity(&before)
        || identity(
            &file
                .metadata()
                .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?,
        ) != identity(&before)
    {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_private_file(_path: &Path) -> Result<Vec<u8>, AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn write_private_atomic(
    path: &Path,
    owner_id: &str,
    next: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let temporary = parent.join(format!(
        ".{name}.{}.{}.tmp",
        std::process::id(),
        next.generation
    ));
    let payload = serde_json::to_vec(&CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        owner_id: owner_id.to_owned(),
        generation: next.generation,
        digest: next.digest.to_string(),
    })
    .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
    if payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let result = (|| -> Result<(), AuthBusAuthorityError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.write_all(&payload)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(not(unix))]
fn write_private_atomic(
    _path: &Path,
    _owner_id: &str,
    _next: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(all(test, unix))]
#[path = "host_tests.rs"]
mod tests;
