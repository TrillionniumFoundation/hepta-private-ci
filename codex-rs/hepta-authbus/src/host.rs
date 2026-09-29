use std::future::Future;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

use crate::AuthBusAdminPort;
use crate::AuthBusAuthorityError;
use crate::AuthBusAuthorityStore;
use crate::AuthBusEffectPort;
use crate::AuthBusReadPort;
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
use crate::checkpoint_file::AuthorityCheckpointFile;
use crate::checkpoint_file::AuthorityWriterLock;

const RECOVERY_BATCH: u32 = 256;

/// Exclusive owner of one AuthBus authority database and checkpoint witness.
/// Product adapters receive a bounded port rather than this complete owner.
pub struct AuthBusAuthorityHost {
    store: AuthBusAuthorityStore,
    checkpoint: AuthorityCheckpointFile,
    mutation_gate: Mutex<()>,
    _writer_lock: AuthorityWriterLock,
}

/// One-time authority-store bootstrap. It creates the initial external witness
/// before making the matching local checkpoint authoritative.
pub struct AuthBusAuthorityBootstrap;

impl AuthBusAuthorityBootstrap {
    pub async fn initialize(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<AuthBusAuthorityHost, AuthBusAuthorityError> {
        AuthBusAuthorityHost::bootstrap(database_path, checkpoint_path, owner_id).await
    }
}

impl AuthBusAuthorityHost {
    pub async fn open(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let writer_checkpoint = checkpoint_path.clone();
        let writer_database = database_path.to_path_buf();
        let writer_owner = owner_id.to_owned();
        let writer_lock = blocking(move || {
            AuthorityWriterLock::acquire(&writer_checkpoint, &writer_database, &writer_owner)
        })
        .await?;
        let store = AuthBusAuthorityStore::open(database_path).await?;
        let open_checkpoint = checkpoint_path;
        let open_database = database_path.to_path_buf();
        let open_owner = owner_id.to_owned();
        let (checkpoint, external) = blocking(move || {
            AuthorityCheckpointFile::open(open_checkpoint, &open_database, &open_owner)
        })
        .await?;
        match store.authority_checkpoint().await? {
            None => store.initialize_authority_checkpoint(external).await?,
            Some(_) => {
                if let Some(next) = store.reconcile_authority_checkpoint(external).await? {
                    let replace = checkpoint.clone();
                    blocking(move || replace.replace(external, next)).await?;
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
            mutation_gate: Mutex::new(()),
            _writer_lock: writer_lock,
        };
        host.sync_checkpoint().await?;
        Ok(host)
    }

    async fn bootstrap(
        database_path: &Path,
        checkpoint_path: PathBuf,
        owner_id: &str,
    ) -> Result<Self, AuthBusAuthorityError> {
        let writer_checkpoint = checkpoint_path.clone();
        let writer_database = database_path.to_path_buf();
        let writer_owner = owner_id.to_owned();
        let writer_lock = blocking(move || {
            AuthorityWriterLock::acquire(&writer_checkpoint, &writer_database, &writer_owner)
        })
        .await?;
        let store = AuthBusAuthorityStore::open(database_path).await?;
        if store.authority_checkpoint().await?.is_some() {
            return Err(AuthBusAuthorityError::AlreadyExists);
        }
        let initial = AuthorityCheckpoint {
            generation: 1,
            digest: store.authority_frontier_digest().await?,
        };
        let create_database = database_path.to_path_buf();
        let create_owner = owner_id.to_owned();
        let checkpoint = blocking(move || {
            AuthorityCheckpointFile::create(
                checkpoint_path,
                &create_database,
                &create_owner,
                initial,
            )
        })
        .await?;
        store.initialize_authority_checkpoint(initial).await?;
        let host = Self {
            store,
            checkpoint,
            mutation_gate: Mutex::new(()),
            _writer_lock: writer_lock,
        };
        host.sync_checkpoint().await?;
        Ok(host)
    }

    #[must_use]
    pub fn admin_port(&self) -> AuthBusAdminPort<'_> {
        AuthBusAdminPort { host: self }
    }

    #[must_use]
    pub fn effect_port(&self) -> AuthBusEffectPort<'_> {
        AuthBusEffectPort { host: self }
    }

    #[must_use]
    pub fn read_port(&self) -> AuthBusReadPort<'_> {
        AuthBusReadPort { host: self }
    }

    pub(crate) async fn sync_checkpoint(&self) -> Result<(), AuthBusAuthorityError> {
        let _guard = self.mutation_gate.lock().await;
        self.sync_checkpoint_locked().await
    }

    async fn sync_checkpoint_locked(&self) -> Result<(), AuthBusAuthorityError> {
        let read = self.checkpoint.clone();
        let external = blocking(move || read.read()).await?;
        if let Some(next) = self.store.reconcile_authority_checkpoint(external).await? {
            let replace = self.checkpoint.clone();
            blocking(move || replace.replace(external, next)).await?;
            self.store
                .advance_authority_checkpoint(external.generation, next)
                .await?;
        }
        Ok(())
    }

    async fn mutate<T>(
        &self,
        operation: impl Future<Output = Result<T, AuthBusAuthorityError>>,
    ) -> Result<T, AuthBusAuthorityError> {
        let _guard = self.mutation_gate.lock().await;
        let result = operation.await;
        self.sync_checkpoint_locked().await?;
        result
    }

    async fn observe<T>(
        &self,
        operation: impl Future<Output = Result<T, AuthBusAuthorityError>>,
    ) -> Result<T, AuthBusAuthorityError> {
        let _guard = self.mutation_gate.lock().await;
        self.sync_checkpoint_locked().await?;
        operation.await
    }

    pub(crate) async fn enroll_issuer_inner(
        &self,
        purpose: IssuerPurpose,
        spec: IssuerSpec,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.mutate(self.store.enroll_issuer(purpose, spec)).await
    }

    pub(crate) async fn rotate_issuer_inner(
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

    pub(crate) async fn revoke_issuer_inner(
        &self,
        purpose: IssuerPurpose,
        issuer_id: &StableId,
        key_epoch: Generation,
        expected_revision: u64,
    ) -> Result<IssuerRecord, AuthBusAuthorityError> {
        self.mutate(self.store.revoke_issuer(
            purpose,
            issuer_id,
            key_epoch,
            expected_revision,
        ))
        .await
    }

    pub(crate) async fn retire_issuer_epoch_inner(
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

    pub(crate) async fn observe_trusted_time_attestation_inner(
        &self,
        attestation: &SignedTrustedTimeAttestation,
    ) -> Result<TrustedTimeSample, AuthBusAuthorityError> {
        self.mutate(self.store.observe_trusted_time_attestation(attestation))
            .await
    }

    pub(crate) async fn message_issuer_inner(
        &self,
        issuer_id: &StableId,
        key_epoch: Generation,
    ) -> Result<IssuerRegistration, AuthBusAuthorityError> {
        self.observe(self.store.message_issuer(issuer_id, key_epoch))
            .await
    }

    pub(crate) async fn create_policy_inner(
        &self,
        spec: PolicySpec,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(self.store.create_policy(spec, time)).await
    }

    pub(crate) async fn replace_policy_inner(
        &self,
        spec: PolicySpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(self.store.replace_policy(spec, expected_revision, time))
            .await
    }

    pub(crate) async fn revoke_policy_inner(
        &self,
        policy_id: &StableId,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<AuthPolicy, AuthBusAuthorityError> {
        self.mutate(
            self.store
                .revoke_policy(policy_id, expected_revision, time),
        )
        .await
    }

    pub(crate) async fn retire_policy_inner(
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

    pub(crate) async fn authorize_inner(
        &self,
        principal: &StableId,
        action: &StableId,
        scope_digest: Digest32,
        policy_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<PolicyDecision, AuthBusAuthorityError> {
        self.mutate(self.store.authorize(
            principal,
            action,
            scope_digest,
            policy_revision,
            time,
        ))
        .await
    }

    pub(crate) async fn create_quota_inner(
        &self,
        spec: QuotaSpec,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.mutate(self.store.create_quota(spec, time)).await
    }

    pub(crate) async fn replace_quota_inner(
        &self,
        spec: QuotaSpec,
        expected_revision: u64,
        time: TrustedTimeSample,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.mutate(self.store.replace_quota(spec, expected_revision, time))
            .await
    }

    pub(crate) async fn reserve_inner(
        &self,
        decision: &PolicyDecision,
        request: ReservationRequest,
        time: TrustedTimeSample,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.mutate(self.store.reserve(decision, request, time)).await
    }

    pub(crate) async fn mark_dispatch_attempted_inner(
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

    pub(crate) async fn mark_indeterminate_inner(
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

    pub(crate) async fn cancel_reservation_inner(
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

    pub(crate) async fn reconcile_expired_reservation_inner(
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

    pub(crate) async fn settle_inner(
        &self,
        evidence: &SignedSettlementEvidence,
        time: TrustedTimeSample,
    ) -> Result<Settlement, AuthBusAuthorityError> {
        self.mutate(self.store.settle(evidence, time)).await
    }

    pub(crate) async fn compact_terminal_reservations_inner(
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

    pub(crate) async fn quota_snapshot_inner(
        &self,
        quota_key: &StableId,
    ) -> Result<QuotaSnapshot, AuthBusAuthorityError> {
        self.observe(self.store.quota_snapshot(quota_key)).await
    }

    pub(crate) async fn reservation_inner(
        &self,
        reservation_id: &StableId,
    ) -> Result<QuotaReservation, AuthBusAuthorityError> {
        self.observe(self.store.reservation(reservation_id)).await
    }
}

async fn blocking<T>(
    operation: impl FnOnce() -> Result<T, AuthBusAuthorityError> + Send + 'static,
) -> Result<T, AuthBusAuthorityError>
where
    T: Send + 'static,
{
    tokio::task::spawn_blocking(operation)
        .await
        .map_err(|error| AuthBusAuthorityError::Storage(format!("checkpoint task failed: {error}")))?
}

#[cfg(all(test, unix))]
#[path = "host_tests.rs"]
mod tests;
