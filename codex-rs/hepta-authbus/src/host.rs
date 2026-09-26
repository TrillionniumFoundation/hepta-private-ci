use std::future::Future;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::Semaphore;

use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthPolicy;
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
use crate::authority_store::storage;
use crate::host_checkpoint::AuthorityCheckpointFile;
use crate::host_checkpoint::checkpoint_path_exists;
use crate::host_checkpoint::validate_checkpoint_location;
use crate::host_lock::OwnerLockFile;
use crate::host_lock::open_private_owner_lock;
use crate::host_lock::try_owner_lock;

const RECOVERY_BATCH: u32 = 256;

pub struct AuthBusAuthorityHost {
    store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpointFile,
    /// Serializes the complete local-mutation -> external publication -> local
    /// promotion protocol across tasks in this host. The file itself carries
    /// the same exclusion across host instances and processes.
    owner_file: OwnerLockFile,
    database_file: OwnerLockFile,
    mutation_gate: Semaphore,
}

impl AuthBusAuthorityHost {
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        Self::open_inner(database_path, checkpoint_path, owner_id, false).await
    }

    /// Create the first independently retained authority checkpoint, or finish
    /// a bootstrap interrupted after either SQLite creation or witness
    /// publication. An existing witness follows the normal `open` recovery
    /// path. A database without a witness is accepted only while every
    /// authoritative table is still pristine.
    pub async fn bootstrap(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        Self::open_inner(database_path, checkpoint_path, owner_id, true).await
    }

    async fn open_inner(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
        allow_bootstrap: bool,
    ) -> Result<Self, AuthBusAuthorityError> {
        if owner_id.is_empty() || owner_id.len() > 256 {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        validate_checkpoint_location(&checkpoint_path, database_path)?;
        // The stable lock file is separate from the atomically replaced witness:
        // locking the witness inode itself would stop protecting the path after
        // rename. Acquire it before opening or migrating the SQLite owner.
        let database_file = open_private_owner_lock(database_path)?;
        let database_guard = try_owner_lock(&database_file)?;
        let owner_file = open_private_owner_lock(&checkpoint_path)?;
        let process_guard = try_owner_lock(&owner_file)?;
        let checkpoint_exists = checkpoint_path_exists(&checkpoint_path)?;
        if !checkpoint_exists && !allow_bootstrap {
            return Err(AuthBusAuthorityError::UnsafeCheckpoint);
        }
        let existing_checkpoint = if checkpoint_exists {
            Some(AuthorityCheckpointFile::open(
                checkpoint_path.clone(),
                database_path,
                owner_id,
            )?)
        } else {
            None
        };
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let checkpoint = match existing_checkpoint {
            Some((checkpoint, _)) => checkpoint,
            None => {
                if !authority_store_is_pristine(&store).await? {
                    return Err(AuthBusAuthorityError::UnsafeCheckpoint);
                }
                let initial = AuthorityCheckpoint {
                    generation: 1,
                    digest: store.authority_frontier_digest().await?,
                };
                AuthorityCheckpointFile::create(checkpoint_path, database_path, owner_id, initial)?
            }
        };
        let external = checkpoint.confirm_durable()?;
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
        sync_checkpoint_parts(&store, &checkpoint).await?;
        database_file.validate_current()?;
        owner_file.validate_current()?;
        drop(process_guard);
        drop(database_guard);
        Ok(Self {
            store,
            checkpoint,
            owner_file,
            database_file,
            mutation_gate: Semaphore::new(1),
        })
    }

    pub async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let _task_guard = self
            .mutation_gate
            .acquire()
            .await
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let _database_guard = try_owner_lock(&self.database_file)?;
        let _process_guard = try_owner_lock(&self.owner_file)?;
        self.sync_checkpoint_locked().await
    }

    async fn sync_checkpoint_locked(&self) -> Result<(), AuthBusAuthorityError> {
        self.database_file.validate_current()?;
        self.owner_file.validate_current()?;
        sync_checkpoint_parts(&self.store, &self.checkpoint).await?;
        self.database_file.validate_current()?;
        self.owner_file.validate_current()
    }

    /// Serialize the complete preflight-recovery -> local mutation -> external
    /// publication -> local promotion protocol across tasks, host instances and
    /// processes. Cancellation after a committed local mutation releases the OS
    /// lock and leaves a dirty frontier that the next holder must publish before
    /// appending new state.
    async fn run_mutation<T, F, Fut>(&self, operation: F) -> Result<T, AuthBusAuthorityError>
    where
        F: FnOnce(AuthBusAuthorityStore) -> Fut,
        Fut: Future<Output = Result<T, AuthBusAuthorityError>>,
    {
        let _task_guard = self
            .mutation_gate
            .acquire()
            .await
            .map_err(|error| AuthBusAuthorityError::Storage(error.to_string()))?;
        let _database_guard = try_owner_lock(&self.database_file)?;
        let _process_guard = try_owner_lock(&self.owner_file)?;
        self.sync_checkpoint_locked().await?;
        let result = operation(self.store.clone()).await;
        self.sync_checkpoint_locked().await?;
        result
    }

    pub async fn enroll_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.run_mutation(|store| async move { store.enroll_issuer(purpose, spec).await })
            .await
    }

    pub async fn rotate_issuer(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
        expected_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .rotate_issuer(purpose, spec, expected_epoch, expected_revision)
                .await
        })
        .await
    }

    pub async fn revoke_issuer(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .revoke_issuer(purpose, issuer_id, key_epoch, expected_revision)
                .await
        })
        .await
    }

    pub async fn retire_issuer_epoch(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRetirement, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .retire_issuer_epoch(purpose, issuer_id, key_epoch, expected_revision)
                .await
        })
        .await
    }

    pub async fn observe_trusted_time_attestation(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store.observe_trusted_time_attestation(attestation).await
        })
        .await
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
        self.run_mutation(|store| async move { store.create_policy(spec, time).await })
            .await
    }

    pub async fn replace_policy(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store.replace_policy(spec, expected_revision, time).await
        })
        .await
    }

    pub async fn revoke_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .revoke_policy(policy_id, expected_revision, time)
                .await
        })
        .await
    }

    pub async fn retire_policy(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        retired_at_ms: u64,
    ) -> Result<(), AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .retire_policy(policy_id, expected_revision, retired_at_ms)
                .await
        })
        .await
    }

    pub async fn authorize(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .authorize(principal, action, scope_digest, policy_revision, time)
                .await
        })
        .await
    }

    pub async fn create_quota(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.run_mutation(|store| async move { store.create_quota(spec, time).await })
            .await
    }

    pub async fn replace_quota(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store.replace_quota(spec, expected_revision, time).await
        })
        .await
    }

    pub async fn reserve(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.run_mutation(|store| async move { store.reserve(decision, request, time).await })
            .await
    }

    pub async fn mark_dispatch_attempted(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        dispatch_digest: Digest32,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .mark_dispatch_attempted(reservation_id, expected_revision, dispatch_digest, time)
                .await
        })
        .await
    }

    pub async fn mark_indeterminate(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .mark_indeterminate(reservation_id, expected_revision, time)
                .await
        })
        .await
    }

    pub async fn cancel_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .cancel_reservation(reservation_id, expected_revision, time)
                .await
        })
        .await
    }

    pub async fn reconcile_expired_reservation(
        &self,
        reservation_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .reconcile_expired_reservation(reservation_id, expected_revision, time)
                .await
        })
        .await
    }

    pub async fn settle(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.run_mutation(|store| async move { store.settle(evidence, time).await })
            .await
    }

    pub async fn compact_terminal_reservations(
        &self,
        older_than_ms: u64,
        limit: u32,
    ) -> Result<u32, AuthBusAuthorityError> {
        self.run_mutation(|store| async move {
            store
                .compact_terminal_reservations(older_than_ms, limit)
                .await
        })
        .await
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

async fn sync_checkpoint_parts(
    store: &AuthBusAuthorityStore,
    checkpoint: &AuthorityCheckpointFile,
) -> Result<(), AuthBusAuthorityError> {
    let external = checkpoint.confirm_durable()?;
    if let Some(next) = store.reconcile_authority_checkpoint(external).await? {
        checkpoint.replace(external, next)?;
        store
            .advance_authority_checkpoint(external.generation, next)
            .await?;
    }
    Ok(())
}

async fn authority_store_is_pristine(
    store: &AuthBusAuthorityStore,
) -> Result<bool, AuthBusAuthorityError> {
    let occupied: i64 = sqlx::query_scalar(
        "SELECT
           EXISTS(SELECT 1 FROM authbus_trusted_time) +
           EXISTS(SELECT 1 FROM authbus_policy) +
           EXISTS(SELECT 1 FROM authbus_quota_registry) +
           EXISTS(SELECT 1 FROM authbus_quota_reservation) +
           EXISTS(SELECT 1 FROM authbus_policy_history) +
           EXISTS(SELECT 1 FROM authbus_policy_archive) +
           EXISTS(SELECT 1 FROM authbus_quota_reservation_archive) +
           EXISTS(SELECT 1 FROM authbus_issuer_registry) +
           EXISTS(SELECT 1 FROM authbus_authority_checkpoint) +
           (SELECT dirty FROM authbus_authority_checkpoint_dirty WHERE singleton = 1) +
           (SELECT recovery_required FROM authbus_recovery_state WHERE singleton = 1)",
    )
    .fetch_one(&store.pool)
    .await
    .map_err(storage)?;
    Ok(occupied == 0)
}

#[cfg(all(test, unix))]
#[path = "host_tests.rs"]
mod tests;
