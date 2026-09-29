use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Read;
#[cfg(unix)]
use std::io::Write;
#[cfg(test)]
use std::sync::atomic::AtomicU8;
#[cfg(test)]
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthPolicy;
use crate::AuthorityCheckpoint;
use crate::ExpiredReservationSweep;
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
use crate::SettlementIssuerRegistration;
use crate::SignedSettlementEvidence;
use crate::SignedTrustedTimeAttestation;
use crate::TrustedTimeSample;
use crate::operations::AuthBusRuntimeMetrics;
use crate::operations::record_owner_acquisition_failure;
use crate::owner_fence::OwnerFence;

const CHECKPOINT_SCHEMA_VERSION: u32 = 1;
const MAX_CHECKPOINT_BYTES: u64 = 4096;
const RECOVERY_BATCH: u32 = 256;

#[cfg(test)]
static CHECKPOINT_FAILPOINT: AtomicU8 = AtomicU8::new(0);

#[cfg(test)]
pub(crate) fn set_checkpoint_failpoint(stage: u8) {
    CHECKPOINT_FAILPOINT.store(stage, Ordering::SeqCst);
}

fn checkpoint_failpoint(stage: u8) -> Result<(), AuthBusAuthorityError> {
    #[cfg(test)]
    if CHECKPOINT_FAILPOINT.load(Ordering::SeqCst) == stage {
        return Err(AuthBusAuthorityError::Storage(format!(
            "injected checkpoint I/O failure at stage {stage}"
        )));
    }
    #[cfg(not(test))]
    let _ = stage;
    Ok(())
}

/// Sole owner of the durable AuthBus authority state.
///
/// All mutating operations, recovery maintenance and safety-relevant reads pass
/// through `mutation_gate`. The gate is held from checkpoint preflight through
/// SQLite commit and external checkpoint publication, so no caller can observe
/// or extend a dirty frontier concurrently.
pub struct AuthBusAuthorityHost {
    pub(crate) store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpointFile,
    mutation_gate: Mutex<()>,
    pub(crate) metrics: AuthBusRuntimeMetrics,
    _owner_fence: OwnerFence,
}

impl AuthBusAuthorityHost {
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        Self::open_internal(database_path, checkpoint_path, owner_id, false).await
    }

    /// Create the first independently retained checkpoint only when neither
    /// state domain exists. Bootstrap is never a recovery operation.
    pub async fn bootstrap(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        Self::open_internal(database_path, checkpoint_path, owner_id, true).await
    }

    async fn open_internal(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
        allow_bootstrap: bool,
    ) -> Result<Self, AuthBusAuthorityError> {
        let database_exists = database_path.exists();
        let checkpoint_exists = checkpoint_path.exists();
        if (allow_bootstrap && (database_exists || checkpoint_exists))
            || (!allow_bootstrap && (!database_exists || !checkpoint_exists))
        {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        let owner_fence = match OwnerFence::acquire(database_path, owner_id).await {
            Ok(fence) => fence,
            Err(error) => {
                record_owner_acquisition_failure(&error);
                return Err(error);
            }
        };
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let checkpoint_database_path = database_path.to_path_buf();
        let checkpoint_owner_id = owner_id.to_owned();
        let (checkpoint, external) = if checkpoint_exists {
            tokio::task::spawn_blocking(move || {
                AuthorityCheckpointFile::open(
                    checkpoint_path,
                    &checkpoint_database_path,
                    &checkpoint_owner_id,
                )
            })
            .await
            .map_err(checkpoint_task_error)??
        } else {
            if !allow_bootstrap || store.authority_checkpoint().await?.is_some() {
                return Err(AuthBusAuthorityError::RollbackDetected);
            }
            let initial = AuthorityCheckpoint {
                generation: 1,
                digest: store.authority_frontier_digest().await?,
            };
            tokio::task::spawn_blocking(move || {
                AuthorityCheckpointFile::create(
                    checkpoint_path,
                    &checkpoint_database_path,
                    &checkpoint_owner_id,
                    initial,
                )
            })
            .await
            .map_err(checkpoint_task_error)??
        };
        match store.authority_checkpoint().await? {
            None => store.initialize_authority_checkpoint(external).await?,
            Some(_) => {
                if let Some(next) = store.reconcile_authority_checkpoint(external).await? {
                    checkpoint.replace_async(external, next).await?;
                    store
                        .advance_authority_checkpoint(external.generation, next)
                        .await?;
                }
            }
        }
        // Startup work is deliberately bounded. If more work remains, normal
        // write admission stays fail-closed through recovery_required while the
        // named authority worker continues subsequent batches.
        let _ = store.reconcile_after_restart(RECOVERY_BATCH).await?;
        if let Some(time) = store.last_trusted_time().await? {
            let _ = store
                .sweep_expired_reservations(time, RECOVERY_BATCH)
                .await?;
        }
        let host = Self {
            store,
            checkpoint,
            mutation_gate: Mutex::new(()),
            metrics: AuthBusRuntimeMetrics::default(),
            _owner_fence: owner_fence,
        };
        host.sync_checkpoint().await?;
        Ok(host)
    }

    /// Reconcile the independently retained checkpoint while excluding every
    /// mutation and safety-relevant read from the authority frontier.
    pub(crate) async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let _guard = self.mutation_gate.lock().await;
        self.sync_checkpoint_locked().await
    }

    async fn sync_checkpoint_locked(&self) -> Result<(), AuthBusAuthorityError> {
        let result = async {
            let external = self.checkpoint.read_async().await?;
            if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
                self.checkpoint.replace_async(external, next).await?;
                self.store
                    .advance_authority_checkpoint(external.generation, next)
                    .await?;
            }
            Ok(())
        }
        .await;
        if let Err(error) = &result {
            self.metrics.record_checkpoint_sync_failure(error);
        }
        result
    }

    async fn mutate<T, F>(&self, operation: F) -> Result<T, AuthBusAuthorityError>
    where
        F: Future<Output = Result<T, AuthBusAuthorityError>>,
    {
        let started = Instant::now();
        let _guard = self.mutation_gate.lock().await;
        let result = match self.sync_checkpoint_locked().await {
            Ok(()) => self.finish_locked(operation.await).await,
            Err(error) => Err(AuthBusAuthorityError::AuthorityUseBlocked(
                error.to_string(),
            )),
        };
        self.metrics.record_mutation(started.elapsed(), &result);
        result
    }

    async fn read_authoritative<T, F>(&self, operation: F) -> Result<T, AuthBusAuthorityError>
    where
        F: Future<Output = Result<T, AuthBusAuthorityError>>,
    {
        let _guard = self.mutation_gate.lock().await;
        if let Err(error) = self.sync_checkpoint_locked().await {
            self.metrics.record_authority_use_block();
            return Err(AuthBusAuthorityError::AuthorityUseBlocked(
                error.to_string(),
            ));
        }
        operation.await
    }

    async fn finish_locked<T>(
        &self,
        result: Result<T, AuthBusAuthorityError>,
    ) -> Result<T, AuthBusAuthorityError> {
        match result {
            Ok(value) => match self.sync_checkpoint_locked().await {
                Ok(()) => Ok(value),
                Err(error) => Err(AuthBusAuthorityError::CheckpointReconciliationRequired(
                    error.to_string(),
                )),
            },
            Err(error) => {
                let operation_error = normalize_mutation_error(error);
                match self.sync_checkpoint_locked().await {
                    Ok(()) => Err(operation_error),
                    Err(checkpoint_error) => {
                        Err(AuthBusAuthorityError::MutationOutcomeUnknown(format!(
                            "operation returned {operation_error}; checkpoint reconciliation failed: {checkpoint_error}"
                        )))
                    }
                }
            }
        }
    }

    pub(crate) async fn run_maintenance_mutations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<(bool, ExpiredReservationSweep), AuthBusAuthorityError> {
        let started = Instant::now();
        let _guard = self.mutation_gate.lock().await;
        let result = match self.sync_checkpoint_locked().await {
            Err(error) => Err(AuthBusAuthorityError::AuthorityUseBlocked(
                error.to_string(),
            )),
            Ok(()) => {
                let operation = async {
                    let recovery_complete = self.store.reconcile_after_restart(limit).await?;
                    let sweep = self.store.sweep_expired_reservations(time, limit).await?;
                    Ok((recovery_complete, sweep))
                }
                .await;
                self.finish_locked(operation).await
            }
        };
        self.metrics.record_maintenance(started.elapsed(), &result);
        result
    }

    pub(crate) async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.mutate(self.store.enroll_issuer(purpose, spec)).await
    }

    pub(crate) async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .rotate_issuer(purpose, spec, expected_epoch, expected_revision),
        )
        .await
    }

    pub(crate) async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .revoke_issuer(purpose, issuer_id, key_epoch, expected_revision),
        )
        .await
    }

    pub(crate) async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        self.mutate(self.store.retire_issuer_epoch(
            purpose,
            issuer_id,
            key_epoch,
            expected_revision,
        ))
        .await
    }

    pub(crate) async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.mutate(self.store.observe_trusted_time_attestation(attestation))
            .await
    }

    pub(crate) async fn message_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.read_authoritative(self.store.message_issuer(issuer_id, key_epoch))
            .await
    }

    pub(crate) async fn settlement_issuer(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<SettlementIssuerRegistration, AuthBusAuthorityError> {
        self.read_authoritative(self.store.settlement_issuer(issuer_id, key_epoch))
            .await
    }

    pub(crate) async fn create_policy(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(self.store.create_policy(spec, time)).await
    }

    pub(crate) async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(self.store.replace_policy(spec, expected_revision, time))
            .await
    }

    pub(crate) async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(self.store.revoke_policy(policy_id, expected_revision, time))
            .await
    }

    pub(crate) async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        self.mutate(
            self.store
                .retire_policy(policy_id, expected_revision, retired_at_ms),
        )
        .await
    }

    pub(crate) async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .authorize(principal, action, scope_digest, policy_revision, time),
        )
        .await
    }

    pub(crate) async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.mutate(self.store.create_quota(spec, time)).await
    }

    pub(crate) async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.mutate(self.store.replace_quota(spec, expected_revision, time))
            .await
    }

    pub(crate) async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(self.store.reserve(decision, request, time))
            .await
    }

    pub(crate) async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(self.store.mark_dispatch_attempted(
            reservation_id,
            expected_revision,
            dispatch_digest,
            time,
        ))
        .await
    }

    pub(crate) async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .mark_indeterminate(reservation_id, expected_revision, time),
        )
        .await
    }

    pub(crate) async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .cancel_reservation(reservation_id, expected_revision, time),
        )
        .await
    }

    pub(crate) async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(self.store.reconcile_expired_reservation(
            reservation_id,
            expected_revision,
            time,
        ))
        .await
    }

    pub(crate) async fn sweep_expired_reservations(
        &self,
        time: TrustedTimeSample,
        limit: u32,
    ) -> Result<ExpiredReservationSweep, AuthBusAuthorityError> {
        self.mutate(self.store.sweep_expired_reservations(time, limit))
            .await
    }

    pub(crate) async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.mutate(self.store.settle(evidence, time)).await
    }

    pub(crate) async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .compact_terminal_reservations(older_than_ms, limit),
        )
        .await
    }

    pub(crate) async fn quota_snapshot(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.read_authoritative(self.store.quota_snapshot(quota_key))
            .await
    }

    pub(crate) async fn reservation(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.read_authoritative(self.store.reservation(reservation_id))
            .await
    }
}

fn checkpoint_task_error(error: tokio::task::JoinError) -> AuthBusAuthorityError {
    AuthBusAuthorityError::Storage(format!("checkpoint I/O task failed: {error}"))
}

fn normalize_mutation_error(error: AuthBusAuthorityError) -> AuthBusAuthorityError {
    match error {
        AuthBusAuthorityError::Storage(detail) => {
            AuthBusAuthorityError::MutationOutcomeUnknown(detail)
        }
        other => other,
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

#[derive(Clone)]
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
        validate_owner(owner_id)?;
        validate_path(&path, database_path)?;
        let file = Self {
            path,
            owner_id: owner_id.to_owned(),
        };
        let checkpoint = file.read()?;
        Ok((file, checkpoint))
    }

    fn create(
        path: PathBuf,
        database_path: &Path,
        owner_id: &str,
        initial: AuthorityCheckpoint,
    ) -> Result<(Self, AuthorityCheckpoint), AuthBusAuthorityError> {
        validate_owner(owner_id)?;
        validate_parent_paths(&path, database_path)?;
        if initial.generation != 1 || initial.digest.is_zero() || path.exists() {
            return Err(AuthBusAuthorityError::RollbackDetected);
        }
        create_private_checkpoint(&path, owner_id, initial)?;
        Self::open(path, database_path, owner_id)
    }

    async fn read_async(&self) -> Result<AuthorityCheckpoint, AuthBusAuthorityError> {
        let checkpoint = self.clone();
        tokio::task::spawn_blocking(move || checkpoint.read())
            .await
            .map_err(checkpoint_task_error)?
    }

    async fn replace_async(
        &self,
        expected: AuthorityCheckpoint,
        next: AuthorityCheckpoint,
    ) -> Result<(), AuthBusAuthorityError> {
        let checkpoint = self.clone();
        tokio::task::spawn_blocking(move || checkpoint.replace(expected, next))
            .await
            .map_err(checkpoint_task_error)?
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

fn validate_owner(owner_id: &str) -> Result<(), AuthBusAuthorityError> {
    if owner_id.is_empty() || owner_id.len() > 256 {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(())
}

#[cfg(unix)]
fn validate_parent_paths(path: &Path, database_path: &Path) -> Result<(), AuthBusAuthorityError> {
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
    Ok(())
}

#[cfg(not(unix))]
fn validate_parent_paths(_path: &Path, _database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

#[cfg(unix)]
fn validate_path(path: &Path, database_path: &Path) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::MetadataExt;

    validate_parent_paths(path, database_path)?;
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let directory = std::fs::metadata(parent)
        .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
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
fn create_private_checkpoint(
    path: &Path,
    owner_id: &str,
    checkpoint: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    use std::os::unix::fs::OpenOptionsExt;

    let payload = checkpoint_payload(owner_id, checkpoint)?;
    let parent = path
        .parent()
        .ok_or(AuthBusAuthorityError::UnsafeCheckpoint)?;
    let result = (|| -> Result<(), AuthBusAuthorityError> {
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
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(path);
    }
    result
}

#[cfg(not(unix))]
fn create_private_checkpoint(
    _path: &Path,
    _owner_id: &str,
    _checkpoint: AuthorityCheckpoint,
) -> Result<(), AuthBusAuthorityError> {
    Err(AuthBusAuthorityError::UnsafeCheckpoint)
}

fn checkpoint_payload(
    owner_id: &str,
    checkpoint: AuthorityCheckpoint,
) -> Result<Vec<u8>, AuthBusAuthorityError> {
    let payload = serde_json::to_vec(&CheckpointDocument {
        schema_version: CHECKPOINT_SCHEMA_VERSION,
        owner_id: owner_id.to_owned(),
        generation: checkpoint.generation,
        digest: checkpoint.digest.to_string(),
    })
    .map_err(|_| AuthBusAuthorityError::UnsafeCheckpoint)?;
    if payload.len() as u64 > MAX_CHECKPOINT_BYTES {
        return Err(AuthBusAuthorityError::UnsafeCheckpoint);
    }
    Ok(payload)
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
    let payload = checkpoint_payload(owner_id, next)?;
    let result = (|| -> Result<(), AuthBusAuthorityError> {
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&temporary)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_failpoint(1)?;
        file.write_all(&payload)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_failpoint(2)?;
        file.sync_all()
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_failpoint(3)?;
        std::fs::rename(&temporary, path)
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        checkpoint_failpoint(4)?;
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
