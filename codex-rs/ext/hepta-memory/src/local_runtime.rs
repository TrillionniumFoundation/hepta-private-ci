//! Explicit local-development orchestration for a rehydration read.
//!
//! H14 deliberately stops at a read-only boundary.  The seam verifies the
//! current Agent-local lease/event/outbox chains, binds the compact executor
//! to that exact fence, and then calls the H13 pure host read.  It returns a
//! typed plan only: it does not admit an event, append a witness, reconcile a
//! checkpoint, write the KG, route a request, or invoke a provider/effect.
//!
//! The function is intentionally not a lifecycle contributor and is not
//! registered by `install`.  A future runtime caller must make the explicit
//! write/reconcile step visible after inspecting this plan.

use codex_extension_api::ExtensionData;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::LocalCompactExecutor;
use codex_hepta_memory::LocalLeaseOutbox;
use codex_hepta_memory::LocalLeaseOutboxError;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::LocalRehydrationHostError;
use crate::LocalRehydrationHostInput;
use crate::LocalRehydrationHostRead;
use crate::read_local_rehydration_for_turn;

/// Schema version for the explicit H14 orchestration plan.
pub const LOCAL_REHYDRATION_RUNTIME_SCHEMA_VERSION: u32 = 1;
/// The plan is local-development metadata, never a production runtime grant.
pub const LOCAL_REHYDRATION_RUNTIME_NAMESPACE: &str = "local_development_only";
pub const LOCAL_REHYDRATION_RUNTIME_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_REHYDRATION_RUNTIME_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_REHYDRATION_RUNTIME_ROUTING_AUTHORITY: bool = false;
pub const LOCAL_REHYDRATION_RUNTIME_PROVIDER_EFFECTS: bool = false;
pub const LOCAL_REHYDRATION_RUNTIME_PRODUCTION_CALLER: bool = false;

const BINDING_DOMAIN: &[u8] = b"hepta-memory:local-rehydration-runtime:v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalRehydrationRuntimeDisposition {
    /// The committed checkpoint has no witness.  A caller may choose an
    /// explicit local rehydrate operation after separately applying policy.
    NotStarted,
    /// A local append-only witness is already present and may be replayed as
    /// metadata.  This value does not claim that any external effect exists.
    Complete,
}

#[derive(Debug)]
pub enum LocalRehydrationRuntimeError {
    Host(LocalRehydrationHostError),
    Lease(LocalLeaseOutboxError),
    FenceMismatch(String),
    Invalid(String),
}

impl std::fmt::Display for LocalRehydrationRuntimeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Host(error) => write!(formatter, "local runtime host read failed: {error}"),
            Self::Lease(error) => write!(
                formatter,
                "local runtime lease verification failed: {error}"
            ),
            Self::FenceMismatch(detail) => {
                write!(formatter, "local runtime fence mismatch: {detail}")
            }
            Self::Invalid(detail) => write!(formatter, "invalid local runtime plan: {detail}"),
        }
    }
}

impl std::error::Error for LocalRehydrationRuntimeError {}

impl From<LocalRehydrationHostError> for LocalRehydrationRuntimeError {
    fn from(error: LocalRehydrationHostError) -> Self {
        Self::Host(error)
    }
}

impl From<LocalLeaseOutboxError> for LocalRehydrationRuntimeError {
    fn from(error: LocalLeaseOutboxError) -> Self {
        Self::Lease(error)
    }
}

/// A read-only H14 orchestration result bound to the verified local fence.
///
/// The fencing token is represented only by a digest.  The raw token remains
/// inside the lease handle and is never serialized into this plan.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRehydrationRuntimePlan {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id_sha256: Sha256Digest,
    pub lease_generation: u64,
    pub fencing_token_sha256: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub compact_generation: u64,
    pub disposition: LocalRehydrationRuntimeDisposition,
    pub host_read: LocalRehydrationHostRead,
    pub binding_sha256: Sha256Digest,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub routing_authority: bool,
    pub provider_effects: bool,
    pub production_caller: bool,
}

impl LocalRehydrationRuntimePlan {
    /// Revalidates the plan and its negative authority boundary.
    pub fn validate(&self) -> Result<(), LocalRehydrationRuntimeError> {
        if self.schema_version != LOCAL_REHYDRATION_RUNTIME_SCHEMA_VERSION
            || self.namespace != LOCAL_REHYDRATION_RUNTIME_NAMESPACE
        {
            return Err(LocalRehydrationRuntimeError::Invalid(
                "unsupported schema or namespace".to_string(),
            ));
        }
        if self.external_effects
            || self.kg_write_authority
            || self.routing_authority
            || self.provider_effects
            || self.production_caller
        {
            return Err(LocalRehydrationRuntimeError::Invalid(
                "orchestration plan crosses the local-development boundary".to_string(),
            ));
        }
        self.host_read.validate()?;
        if self.lease_generation == 0
            || self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.compact_generation == 0
        {
            return Err(LocalRehydrationRuntimeError::Invalid(
                "fence epochs and generation must be non-zero".to_string(),
            ));
        }
        if self.lease_generation != self.compact_generation {
            return Err(LocalRehydrationRuntimeError::FenceMismatch(
                "lease and compact generations differ".to_string(),
            ));
        }
        let expected_disposition = match self.host_read.read.plan.status {
            codex_hepta_memory::RehydrationStatus::NotStarted => {
                LocalRehydrationRuntimeDisposition::NotStarted
            }
            codex_hepta_memory::RehydrationStatus::Complete => {
                LocalRehydrationRuntimeDisposition::Complete
            }
            status => {
                return Err(LocalRehydrationRuntimeError::Invalid(format!(
                    "unsupported rehydration status {status:?}"
                )));
            }
        };
        if self.disposition != expected_disposition {
            return Err(LocalRehydrationRuntimeError::Invalid(
                "disposition does not match host read".to_string(),
            ));
        }
        if self.binding_sha256
            != binding_digest(
                &self.lease_id_sha256,
                &self.fencing_token_sha256,
                self.lease_generation,
                self.authority_epoch,
                self.owner_epoch,
                self.compact_generation,
                &self.host_read.binding_sha256,
                self.disposition,
            )
        {
            return Err(LocalRehydrationRuntimeError::Invalid(
                "orchestration binding digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    pub fn is_local_read_only(&self) -> bool {
        self.namespace == LOCAL_REHYDRATION_RUNTIME_NAMESPACE
            && !self.external_effects
            && !self.kg_write_authority
            && !self.routing_authority
            && !self.provider_effects
            && !self.production_caller
    }
}

/// Verifies the local lease/event/outbox fence and obtains an explicit H13
/// read.  This function performs no writes; notably it does not call
/// `rehydrate`, `admit`, `reconcile`, or `release`.
pub async fn prepare_local_rehydration_runtime(
    turn_store: &ExtensionData,
    lease: &LocalLeaseOutbox,
    executor: &LocalCompactExecutor,
    input: LocalRehydrationHostInput<'_>,
) -> Result<LocalRehydrationRuntimePlan, LocalRehydrationRuntimeError> {
    let fence = executor.fence();
    if lease.generation() != fence.generation {
        return Err(LocalRehydrationRuntimeError::FenceMismatch(
            "lease generation does not match compact generation".to_string(),
        ));
    }
    if lease.fencing_token() != fence.fencing_token {
        return Err(LocalRehydrationRuntimeError::FenceMismatch(
            "lease fencing token does not match compact fencing token".to_string(),
        ));
    }
    if input.checkpoint.lease.snapshot.fence != *fence {
        return Err(LocalRehydrationRuntimeError::FenceMismatch(
            "checkpoint fence does not match compact executor fence".to_string(),
        ));
    }

    // Verify before and after the read.  A terminal lease transition racing
    // the read therefore fails closed rather than returning an apparently
    // current plan from a stale owner.
    lease.verify_current().await?;
    let host_read = read_local_rehydration_for_turn(turn_store, executor, input).await?;
    lease.verify_current().await?;

    let disposition = match host_read.read.plan.status {
        codex_hepta_memory::RehydrationStatus::NotStarted => {
            LocalRehydrationRuntimeDisposition::NotStarted
        }
        codex_hepta_memory::RehydrationStatus::Complete => {
            LocalRehydrationRuntimeDisposition::Complete
        }
        status => {
            return Err(LocalRehydrationRuntimeError::Invalid(format!(
                "unsupported rehydration status {status:?}"
            )));
        }
    };
    let lease_id_sha256 = identity_digest(b"lease", lease.lease_id());
    let fencing_token_sha256 = identity_digest(b"fencing-token", lease.fencing_token());
    let mut plan = LocalRehydrationRuntimePlan {
        schema_version: LOCAL_REHYDRATION_RUNTIME_SCHEMA_VERSION,
        namespace: LOCAL_REHYDRATION_RUNTIME_NAMESPACE.to_string(),
        lease_id_sha256,
        lease_generation: lease.generation(),
        fencing_token_sha256,
        authority_epoch: fence.authority_epoch,
        owner_epoch: fence.owner_epoch,
        compact_generation: fence.generation,
        disposition,
        host_read,
        binding_sha256: Sha256Digest::for_bytes(b"pending"),
        external_effects: LOCAL_REHYDRATION_RUNTIME_EXTERNAL_EFFECTS,
        kg_write_authority: LOCAL_REHYDRATION_RUNTIME_KG_WRITE_AUTHORITY,
        routing_authority: LOCAL_REHYDRATION_RUNTIME_ROUTING_AUTHORITY,
        provider_effects: LOCAL_REHYDRATION_RUNTIME_PROVIDER_EFFECTS,
        production_caller: LOCAL_REHYDRATION_RUNTIME_PRODUCTION_CALLER,
    };
    plan.binding_sha256 = binding_digest(
        &plan.lease_id_sha256,
        &plan.fencing_token_sha256,
        plan.lease_generation,
        plan.authority_epoch,
        plan.owner_epoch,
        plan.compact_generation,
        &plan.host_read.binding_sha256,
        plan.disposition,
    );
    plan.validate()?;
    Ok(plan)
}

fn identity_digest(kind: &[u8], value: &str) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    hash_part(&mut hasher, kind);
    hash_part(&mut hasher, value.as_bytes());
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn binding_digest(
    lease_id: &Sha256Digest,
    fencing_token: &Sha256Digest,
    lease_generation: u64,
    authority_epoch: u64,
    owner_epoch: u64,
    compact_generation: u64,
    host_read: &Sha256Digest,
    disposition: LocalRehydrationRuntimeDisposition,
) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    for digest in [lease_id, fencing_token, host_read] {
        hash_part(&mut hasher, digest.as_str().as_bytes());
    }
    for value in [
        lease_generation,
        authority_epoch,
        owner_epoch,
        compact_generation,
    ] {
        hash_part(&mut hasher, value.to_string().as_bytes());
    }
    hash_part(
        &mut hasher,
        match disposition {
            LocalRehydrationRuntimeDisposition::NotStarted => b"not_started",
            LocalRehydrationRuntimeDisposition::Complete => b"complete",
        },
    );
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn hash_part(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

#[cfg(test)]
mod tests {
    use std::fs;

    use codex_extension_api::ExtensionData;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::Sha256Digest;
    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::CompactCheckpoint;
    use codex_hepta_memory::CompactFence;
    use codex_hepta_memory::CompactLease;
    use codex_hepta_memory::CompactLossReport;
    use codex_hepta_memory::CompactParentSnapshot;
    use codex_hepta_memory::CompactSummaryReceipt;
    use codex_hepta_memory::RehydrationStatus;
    use codex_hepta_memory::checkpoint_digest;
    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    fn fence(token: &str) -> CompactFence {
        CompactFence::new(3, 4, 1, token).expect("fence")
    }

    fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
        CompactCheckpoint::new(
            "ctxcp:h14",
            CompactLease::from_snapshot(
                CompactParentSnapshot::new(
                    "ctx:h14",
                    1,
                    2,
                    3,
                    Sha256Digest::for_bytes(b"state:h14"),
                    fence,
                )
                .expect("parent"),
            ),
            Vec::new(),
            CompactSummaryReceipt::new(
                Sha256Digest::for_bytes(b"summary:h14"),
                Sha256Digest::for_bytes(b"model:h14"),
                Sha256Digest::for_bytes(b"policy:h14"),
            ),
            CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss"),
            0,
        )
        .expect("checkpoint")
    }

    async fn opened_store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000914").expect("owner");
        CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("store")
    }

    async fn prepared() -> (
        TempDir,
        ExtensionData,
        codex_hepta_memory::LocalLeaseOutbox,
        LocalCompactExecutor,
        CompactCheckpoint,
    ) {
        let temp = TempDir::new().expect("temp");
        let store = opened_store(&temp).await;
        let current_fence = fence("h14-fence");
        let checkpoint = checkpoint(current_fence.clone());
        let lease = match store
            .acquire_local_lease("lease:h14", 1, "h14-fence")
            .await
            .expect("lease")
        {
            codex_hepta_memory::LocalLeaseAcquire::Acquired(lease)
            | codex_hepta_memory::LocalLeaseAcquire::Replay(lease) => lease,
        };
        lease
            .admit(
                "occurrence:h14",
                "local.rehydration.read.v1",
                "{\"external_effect\":false}",
            )
            .await
            .expect("local admission");
        let executor = store
            .open_local_compact_executor("journal:h14", current_fence)
            .await
            .expect("executor");
        let current = checkpoint.lease.snapshot.clone();
        executor
            .append_intent("op:h14", &checkpoint, &current)
            .await
            .expect("intent");
        let digest = checkpoint_digest(&checkpoint).expect("digest");
        executor
            .commit_checkpoint("op:h14", &digest)
            .await
            .expect("commit");
        (
            temp,
            ExtensionData::new("turn:h14"),
            lease,
            executor,
            checkpoint,
        )
    }

    #[tokio::test]
    async fn orchestration_is_read_only_and_binds_lease_and_checkpoint() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        let before_counts = lease.snapshot_counts().await.expect("before counts");
        let before_snapshot = executor.snapshot().await.expect("before snapshot");
        let plan = prepare_local_rehydration_runtime(
            &turn_store,
            &lease,
            &executor,
            LocalRehydrationHostInput::new("turn:h14", "op:h14", &checkpoint, 0),
        )
        .await
        .expect("runtime plan");

        assert_eq!(
            plan.disposition,
            LocalRehydrationRuntimeDisposition::NotStarted
        );
        assert!(plan.is_local_read_only());
        assert_eq!(
            plan.host_read.read.plan.status,
            RehydrationStatus::NotStarted
        );
        assert!(turn_store.get::<LocalRehydrationRuntimePlan>().is_none());
        assert_eq!(
            lease.snapshot_counts().await.expect("after counts"),
            before_counts
        );
        assert_eq!(
            executor.snapshot().await.expect("after snapshot"),
            before_snapshot
        );
    }

    #[tokio::test]
    async fn orchestration_observes_explicit_witness_without_writing() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        executor
            .rehydrate("op:h14", &checkpoint, 0)
            .await
            .expect("explicit rehydrate");
        let before_counts = lease.snapshot_counts().await.expect("before counts");
        let before_snapshot = executor.snapshot().await.expect("before snapshot");
        let plan = prepare_local_rehydration_runtime(
            &turn_store,
            &lease,
            &executor,
            LocalRehydrationHostInput::new("turn:h14", "op:h14", &checkpoint, 0),
        )
        .await
        .expect("runtime plan");

        assert_eq!(
            plan.disposition,
            LocalRehydrationRuntimeDisposition::Complete
        );
        assert_eq!(plan.host_read.read.plan.status, RehydrationStatus::Complete);
        assert_eq!(
            lease.snapshot_counts().await.expect("after counts"),
            before_counts
        );
        assert_eq!(
            executor.snapshot().await.expect("after snapshot"),
            before_snapshot
        );
    }

    #[tokio::test]
    async fn orchestration_rejects_stale_lease_or_checkpoint_fence() {
        let (temp, turn_store, _lease, executor, current_checkpoint) = prepared().await;
        let store = opened_store(&temp).await;
        let stale = match store
            .acquire_local_lease("lease:h14-stale", 1, "other-fence")
            .await
            .expect("stale lease")
        {
            codex_hepta_memory::LocalLeaseAcquire::Acquired(lease)
            | codex_hepta_memory::LocalLeaseAcquire::Replay(lease) => lease,
        };
        let error = prepare_local_rehydration_runtime(
            &turn_store,
            &stale,
            &executor,
            LocalRehydrationHostInput::new("turn:h14", "op:h14", &current_checkpoint, 0),
        )
        .await
        .expect_err("stale fence must fail closed");
        assert!(matches!(
            error,
            LocalRehydrationRuntimeError::FenceMismatch(_)
        ));

        let wrong_checkpoint = checkpoint(fence("wrong-fence"));
        let lease = match store
            .acquire_local_lease("lease:h14-wrong-checkpoint", 1, "h14-fence")
            .await
            .expect("matching lease")
        {
            codex_hepta_memory::LocalLeaseAcquire::Acquired(lease)
            | codex_hepta_memory::LocalLeaseAcquire::Replay(lease) => lease,
        };
        let error = prepare_local_rehydration_runtime(
            &turn_store,
            &lease,
            &executor,
            LocalRehydrationHostInput::new("turn:h14", "op:h14", &wrong_checkpoint, 0),
        )
        .await
        .expect_err("checkpoint fence must fail closed");
        assert!(matches!(
            error,
            LocalRehydrationRuntimeError::FenceMismatch(_)
        ));
    }

    #[tokio::test]
    async fn tampered_runtime_plan_fails_validation() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        let mut plan = prepare_local_rehydration_runtime(
            &turn_store,
            &lease,
            &executor,
            LocalRehydrationHostInput::new("turn:h14", "op:h14", &checkpoint, 0),
        )
        .await
        .expect("runtime plan");
        plan.binding_sha256 = Sha256Digest::for_bytes(b"tampered");
        assert!(plan.validate().is_err());
    }
}
