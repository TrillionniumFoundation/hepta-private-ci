use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

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
use tokio::sync::RwLock;

use crate::AuthenticatedMessage;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthPolicy;
use crate::AuthorityCheckpoint;
use crate::Error;
use crate::ExpiredReservationSweep;
use crate::IssuerPurpose;
use crate::IssuerRecord;
use crate::IssuerRetirement;
use crate::IssuerSpec;
use crate::PolicyDecision;
use crate::PolicySpec;
use crate::QuotaReservation;
use crate::QuotaSnapshot;
use crate::QuotaSpec;
use crate::ReservationRequest;
use crate::Settlement;
use crate::SignedMessage;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;
use crate::VerifiedIssuerHandle;
use crate::owner_lock::AuthorityOwnerLock;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;
const RECOVERY_BATCH: u32 = 256;

/// The only public AuthBus writer and verifier.
///
/// A process-lifetime kernel lock fences every SQLite/checkpoint transition. A
/// second gate serializes issuer lifecycle writes against signed admission so a
/// verified handle remains valid until its consuming transaction completes.
pub struct AuthBusAuthorityHost {
    store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpointFile,
    issuer_gate: Arc<RwLock<()>>,
    _owner_lock: AuthorityOwnerLock,
}

impl AuthBusAuthorityHost {
    /// Open an already provisioned authority database and external checkpoint.
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let owner_lock = AuthorityOwnerLock::acquire(database_path, owner_id)?;
        Self::open_locked(database_path, checkpoint_path, owner_id, owner_lock).await
    }

    /// Create private direct-child storage and an initial external checkpoint
    /// only when both database and checkpoint are absent. Existing authority
    /// state without its witness always fails closed.
    pub async fn open_or_bootstrap(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        prepare_private_parent(database_path)?;
        prepare_private_parent(&checkpoint_path)?;
        let db_parent = database_path
            .parent()
            .ok_or(AuthBusAuthorityError::OwnerLockUnavailable)?
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let checkpoint_parent = checkpoint_path
            .parent()
            .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if db_parent == checkpoint_parent {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        let owner_lock = AuthorityOwnerLock::acquire(database_path, owner_id)?;
        match (database_path.exists(), checkpoint_path.exists()) {
            (false, false) => bootstrap_checkpoint(&checkpoint_path, database_path, owner_id)?,
            (true, false) => return Err(AuthBusAuthorityError::UnsafeCheckpoint),
            _ => {}
        }
        Self::open_locked(database_path, checkpoint_path, owner_id, owner_lock).await
    }

    async fn open_locked(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
        owner_lock: AuthorityOwnerLock,
    ) -> Result<Self, AuthBusAuthorityError> {
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let (checkpoint, external) =
            AuthorityCheckpointFile::open(checkpoint_path, database_path, owner_id)?;
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
            issuer_gate: Arc::new(RwLock::new(())),
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
        let _issuer_write = self.issuer_gate.write().await;
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
        let _issuer_write = self.issuer_gate.write().await;
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
        let _issuer_write = self.issuer_gate.write().await;
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
        let _issuer_write = self.issuer_gate.write().await;
        let result = self
            .store
            .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
            .await;
        self.finish(result).await
    }

    pub async fn issuer_record(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        let _issuer_read = self.issuer_gate.read().await;
        self.store
            .issuer_record(purpose, issuer_id, key_epoch)
            .await
    }

    /// Resolve one exact message issuer from the persistent registry and retain
    /// the lifecycle fence in an opaque capability. Callers cannot construct or
    /// alter this handle.
    pub async fn verify_message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<VerifiedIssuerHandle, AuthBusAuthorityError> {
        self.verify_issuer(IssuerPurpose::Message, issuer_id, key_epoch)
            .await
    }

    async fn verify_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<VerifiedIssuerHandle, AuthBusAuthorityError> {
        let registry_guard = Arc::clone(&self.issuer_gate).read_owned().await;
        let record = self
            .store
            .issuer_record(purpose, issuer_id, key_epoch)
            .await?;
        Ok(VerifiedIssuerHandle::from_record(record, registry_guard))
    }

    /// Verify a signed message only after resolving its claimed issuer and epoch
    /// from the persistent Message registry. The returned value keeps the
    /// registry fence until the durable caller transaction drops it.
    pub async fn authenticate_message(
        &self,
        message: &SignedMessage,
        expected_scope: Digest32,
        expected_payload: Digest32,
        now_ms: u64,
    ) -> Result<AuthenticatedMessage, Error> {
        let issuer = self
            .verify_message_issuer(&message.claims.issuer_id, message.claims.key_epoch)
            .await
            .map_err(map_message_registry_error)?;
        message.authenticate(issuer, expected_scope, expected_payload, now_ms)
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        let _issuer_read = self.issuer_gate.read().await;
        let result = self
            .store
            .observe_trusted_time_attestation(attestation)
            .await;
        self.finish(result).await
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

    pub async fn reconcile_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        let result = self
            .store
            .reconcile_expired_reservations(time, limit)
            .await;
        self.finish(result).await
    }

    /// Settlement claims select the issuer identity. The host resolves the exact
    /// Settlement-purpose epoch from the persistent registry and keeps it fenced
    /// through the quota/terminal-state transaction.
    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        let issuer = self
            .verify_issuer(
                IssuerPurpose::Settlement,
                &evidence.claims.issuer_id,
                evidence.claims.key_epoch,
            )
            .await?;
        let result = self.store.settle(&issuer, evidence, time).await;
        self.finish(result).await
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

fn map_message_registry_error(error: AuthBusAuthorityError) -> Error {
    match error {
        AuthBusAuthorityError::IssuerMissing | AuthBusAuthorityError::NotFound => {
            Error::IssuerMismatch
        }
        _ => Error::RegistryUnavailable,
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
    fn open(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
    ) -> Result<(Self, AuthorityCheckpoint), AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
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
fn prepare_private_parent(path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;

    if !path.is_absolute() {
        return Err(AuthBusAuthorityError::OwnerLockUnavailable);
    }
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::OwnerLockUnavailable)?;
    if !parent.exists() {
        let ancestor = parent
            .parent()
            .ok_or(AuthBusAuthorityError::OwnerLockUnavailable)?;
        let ancestor = ancestor
            .canonicalize()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let ancestor_metadata = std::fs::metadata(&ancestor)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        if !ancestor_metadata.is_dir() || ancestor_metadata.mode() & 0o077 != 0 {
            return Err(AuthBusAuthorityError::OwnerLockUnavailable);
        }
        std::fs::create_dir(parent)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700))
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        File::open(&ancestor)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    }
    let canonical = parent
        .canonicalize()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let metadata = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    if canonical != parent || !metadata.is_dir() || metadata.mode() & 0o077 != 0 {
        return Err(AuthBusAuthorityError::OwnerLockUnavailable);
    }
    Ok(())
}

#[cfg(not(unix))]
fn prepare_private_parent(_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::OwnerLockUnavailable)
}

#[cfg(unix)]
fn bootstrap_checkpoint(
    path: &Path,
    database_path: &Path,
    owner_id: &str,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    if owner_id.is_empty() || owner_id.len() > 256 || path.exists() || database_path.exists() {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let database = database_path
        .to_str()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let mut binding = b"hepta.authbus.bootstrap-checkpoint.v1\0".to_vec();
    binding.extend_from_slice(owner_id.as_bytes());
    binding.push(0);
    binding.extend_from_slice(database.as_bytes());
    let document = CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        owner_id: owner_id.to_owned(),
        generation: 1,
        digest: Digest32::of_bytes(&binding).to_string(),
    };
    let payload =
        serde_json::to_vec(&document).map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
    if payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.write_all(&payload)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    file.sync_all()
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
    Ok(())
}

#[cfg(not(unix))]
fn bootstrap_checkpoint(
    _path: &Path,
    _database_path: &Path,
    _owner_id: &str,
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
    let identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
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

#[cfg(test)]
static CHECKPOINT_FAULT: std::sync::atomic::AtomicU8 = std::sync::atomic::AtomicU8::new(0);

#[cfg(test)]
pub(crate) fn inject_checkpoint_fault_once(stage: u8) {
    CHECKPOINT_FAULT.store(stage, std::sync::atomic::Ordering::SeqCst);
}

#[cfg(test)]
fn checkpoint_fault(stage: u8) -> Result<(), AuthBusAuthorityError> {
    if CHECKPOINT_FAULT
        .compare_exchange(
            stage,
            0,
            std::sync::atomic::Ordering::SeqCst,
            std::sync::atomic::Ordering::SeqCst,
        )
        .is_ok()
    {
        return Err(AuthBusAuthorityError::Storage(format!(
            "injected checkpoint failure at stage {stage}"
        )));
    }
    Ok(())
}

#[cfg(not(test))]
fn checkpoint_fault(_stage: u8) -> Result<(), AuthBusAuthorityError> {
    Ok(())
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
        checkpoint_fault(1)?;
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        file.write_all(&payload)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_fault(2)?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_fault(3)?;
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_fault(4)?;
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
