//! Explicit host-owned local rehydration witness write.
//!
//! H16 observes a replay lifecycle without writing.  This module adds the
//! next explicit seam: a host that already owns the turn store, lease,
//! checkpoint, and compact executor may request the core's single-transaction
//! witness writer.  It is not registered as a lifecycle contributor and does
//! not create retries, schedulers, routing, KG writes, or provider effects.

use codex_extension_api::ExtensionData;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CompactCheckpoint;
use codex_hepta_memory::LocalAtomicWitnessError;
use codex_hepta_memory::LocalCompactExecutor;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicy;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicyError;
use codex_hepta_memory::LocalLeaseOutbox;
use codex_hepta_memory::LocalRehydrationWitnessReceipt;
use serde::Deserialize;
use serde::Serialize;

use crate::LocalRehydrationReplayDisposition;
use crate::LocalRehydrationReplayError;
use crate::LocalRehydrationReplayLifecycleInput;
use crate::observe_local_rehydration_replay;

pub const LOCAL_REHYDRATION_WITNESS_SCHEMA_VERSION: u32 = 1;
pub const LOCAL_REHYDRATION_WITNESS_NAMESPACE: &str = "local_development_only";
pub const LOCAL_REHYDRATION_WITNESS_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_REHYDRATION_WITNESS_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_REHYDRATION_WITNESS_PRODUCTION_CALLER: bool = false;
pub const LOCAL_REHYDRATION_WITNESS_LIFECYCLE_REGISTERED: bool = false;

#[derive(Debug)]
pub enum LocalRehydrationWitnessLifecycleError {
    Policy(LocalDevelopmentLifecyclePolicyError),
    Replay(LocalRehydrationReplayError),
    Writer(LocalAtomicWitnessError),
    TurnBindingMismatch,
    Invalid(String),
}

impl std::fmt::Display for LocalRehydrationWitnessLifecycleError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Policy(error) => write!(formatter, "local witness policy rejected: {error}"),
            Self::Replay(error) => write!(
                formatter,
                "local witness replay observation failed: {error}"
            ),
            Self::Writer(error) => write!(formatter, "local witness writer failed: {error}"),
            Self::TurnBindingMismatch => {
                formatter.write_str("local witness turn binding does not match")
            }
            Self::Invalid(detail) => {
                write!(formatter, "invalid local witness lifecycle input: {detail}")
            }
        }
    }
}

impl std::error::Error for LocalRehydrationWitnessLifecycleError {}

impl From<LocalDevelopmentLifecyclePolicyError> for LocalRehydrationWitnessLifecycleError {
    fn from(error: LocalDevelopmentLifecyclePolicyError) -> Self {
        Self::Policy(error)
    }
}

impl From<LocalRehydrationReplayError> for LocalRehydrationWitnessLifecycleError {
    fn from(error: LocalRehydrationReplayError) -> Self {
        Self::Replay(error)
    }
}

impl From<LocalAtomicWitnessError> for LocalRehydrationWitnessLifecycleError {
    fn from(error: LocalAtomicWitnessError) -> Self {
        Self::Writer(error)
    }
}

/// Explicit host-owned inputs for one local witness write.
pub struct LocalRehydrationWitnessLifecycleInput<'a> {
    pub policy: LocalDevelopmentLifecyclePolicy,
    pub turn_id: &'a str,
    pub turn_store: &'a ExtensionData,
    pub operation_id: &'a str,
    pub expected_revision: u64,
    pub checkpoint: &'a CompactCheckpoint,
    pub lease: &'a LocalLeaseOutbox,
    pub executor: &'a LocalCompactExecutor,
}

impl<'a> LocalRehydrationWitnessLifecycleInput<'a> {
    pub fn new(
        turn_id: &'a str,
        turn_store: &'a ExtensionData,
        operation_id: &'a str,
        expected_revision: u64,
        checkpoint: &'a CompactCheckpoint,
        lease: &'a LocalLeaseOutbox,
        executor: &'a LocalCompactExecutor,
    ) -> Self {
        Self::with_policy(
            LocalDevelopmentLifecyclePolicy::qualification_only(),
            turn_id,
            turn_store,
            operation_id,
            expected_revision,
            checkpoint,
            lease,
            executor,
        )
    }

    /// Construct an input with an embedding-supplied policy gate.
    pub fn with_policy(
        policy: LocalDevelopmentLifecyclePolicy,
        turn_id: &'a str,
        turn_store: &'a ExtensionData,
        operation_id: &'a str,
        expected_revision: u64,
        checkpoint: &'a CompactCheckpoint,
        lease: &'a LocalLeaseOutbox,
        executor: &'a LocalCompactExecutor,
    ) -> Self {
        Self {
            policy,
            turn_id,
            turn_store,
            operation_id,
            expected_revision,
            checkpoint,
            lease,
            executor,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalRehydrationWitnessLifecycleResult {
    pub schema_version: u32,
    pub namespace: String,
    pub turn_id_sha256: Sha256Digest,
    pub observed_disposition: LocalRehydrationReplayDisposition,
    pub witness: LocalRehydrationWitnessReceipt,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub lifecycle_registered: bool,
    pub policy_gate_bound: bool,
}

impl LocalRehydrationWitnessLifecycleResult {
    pub fn validate(&self) -> Result<(), LocalRehydrationWitnessLifecycleError> {
        if self.schema_version != LOCAL_REHYDRATION_WITNESS_SCHEMA_VERSION
            || self.namespace != LOCAL_REHYDRATION_WITNESS_NAMESPACE
        {
            return Err(LocalRehydrationWitnessLifecycleError::Invalid(
                "unsupported schema or namespace".to_string(),
            ));
        }
        if self.external_effects
            || self.kg_write_authority
            || self.production_caller
            || self.lifecycle_registered
            || !self.policy_gate_bound
        {
            return Err(LocalRehydrationWitnessLifecycleError::Invalid(
                "witness lifecycle result crosses the local boundary".to_string(),
            ));
        }
        Sha256Digest::parse(self.turn_id_sha256.as_str().to_string()).map_err(|_| {
            LocalRehydrationWitnessLifecycleError::Invalid(
                "turn identity must be a lowercase SHA-256 digest".to_string(),
            )
        })?;
        self.witness
            .validate()
            .map_err(|error| LocalRehydrationWitnessLifecycleError::Invalid(error.to_string()))
    }
}

/// Observe H16 and then invoke the core's lease/compact atomic writer.  The
/// observer is advisory; the writer repeats all authoritative checks in its
/// own `BEGIN IMMEDIATE` transaction, so a stale observation cannot authorize
/// a write.
pub async fn write_local_rehydration_witness_at_lifecycle(
    input: LocalRehydrationWitnessLifecycleInput<'_>,
) -> Result<LocalRehydrationWitnessLifecycleResult, LocalRehydrationWitnessLifecycleError> {
    input.policy.validate()?;
    if input.turn_id.trim().is_empty()
        || input.turn_id.starts_with("auto-compact-")
        || input.turn_id != input.turn_store.level_id()
    {
        return Err(LocalRehydrationWitnessLifecycleError::TurnBindingMismatch);
    }
    let observed = observe_local_rehydration_replay(LocalRehydrationReplayLifecycleInput::new(
        input.turn_id,
        input.turn_store,
        input.operation_id,
        input.expected_revision,
        input.checkpoint,
        input.lease,
        input.executor,
    ))
    .await?;
    let write = codex_hepta_memory::write_local_rehydration_witness(
        input.lease,
        input.executor,
        input.operation_id,
        input.checkpoint,
        input.expected_revision,
    )
    .await?;
    if observed.disposition == LocalRehydrationReplayDisposition::Complete && !write.is_replay() {
        return Err(LocalRehydrationWitnessLifecycleError::Invalid(
            "complete observation was followed by a non-replay witness append".to_string(),
        ));
    }
    let receipt = write.receipt();
    if receipt.journal_id != input.executor.journal_id()
        || receipt.operation_id != input.operation_id
        || receipt.checkpoint_sha256 != observed.checkpoint_sha256
        || receipt.lease_id_sha256 != observed.lease_id_sha256
        || receipt.fencing_token_sha256 != observed.fencing_token_sha256
        || receipt.generation != observed.generation
    {
        return Err(LocalRehydrationWitnessLifecycleError::Invalid(
            "writer receipt does not match the observed turn/checkpoint/fence binding".to_string(),
        ));
    }
    let result = LocalRehydrationWitnessLifecycleResult {
        schema_version: LOCAL_REHYDRATION_WITNESS_SCHEMA_VERSION,
        namespace: LOCAL_REHYDRATION_WITNESS_NAMESPACE.to_string(),
        // Preserve H13/H14's domain-separated turn identity so the lifecycle
        // result is directly cross-checkable with the read observation.
        turn_id_sha256: observed.turn_id_sha256.clone(),
        observed_disposition: observed.disposition,
        witness: receipt.clone(),
        external_effects: LOCAL_REHYDRATION_WITNESS_EXTERNAL_EFFECTS,
        kg_write_authority: LOCAL_REHYDRATION_WITNESS_KG_WRITE_AUTHORITY,
        production_caller: LOCAL_REHYDRATION_WITNESS_PRODUCTION_CALLER,
        lifecycle_registered: LOCAL_REHYDRATION_WITNESS_LIFECYCLE_REGISTERED,
        policy_gate_bound: true,
    };
    result.validate()?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

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
    use codex_hepta_memory::LocalLeaseAcquire;
    use codex_hepta_memory::LocalRehydrationWitnessWrite;
    use codex_hepta_memory::checkpoint_digest;
    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    fn fence() -> CompactFence {
        CompactFence::new(3, 4, 1, "e16-extension-fence").expect("fence")
    }

    fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
        CompactCheckpoint::new(
            "checkpoint:e16-extension",
            CompactLease::from_snapshot(
                CompactParentSnapshot::new(
                    "ctx:e16-extension",
                    1,
                    2,
                    3,
                    Sha256Digest::for_bytes(b"state:e16-extension"),
                    fence,
                )
                .expect("parent snapshot"),
            ),
            Vec::new(),
            CompactSummaryReceipt::new(
                Sha256Digest::for_bytes(b"summary:e16-extension"),
                Sha256Digest::for_bytes(b"model:e16-extension"),
                Sha256Digest::for_bytes(b"policy:e16-extension"),
            ),
            CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss report"),
            0,
        )
        .expect("checkpoint")
    }

    async fn opened_store(temp: &TempDir) -> CognitiveStore {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000916").expect("owner");
        CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("store")
    }

    async fn prepared() -> (
        TempDir,
        ExtensionData,
        codex_hepta_memory::LocalLeaseOutbox,
        codex_hepta_memory::LocalCompactExecutor,
        CompactCheckpoint,
    ) {
        let temp = TempDir::new().expect("temp");
        let store = opened_store(&temp).await;
        let current_fence = fence();
        let checkpoint = checkpoint(current_fence.clone());
        let lease_expires_at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs()
            + 3600;
        let lease = match store
            .acquire_local_lease_bound(
                "lease:e16-extension",
                current_fence.authority_epoch,
                current_fence.owner_epoch,
                1,
                "e16-extension-fence",
                lease_expires_at,
            )
            .await
            .expect("lease")
        {
            LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
        };
        lease
            .admit(
                "occurrence:e16-extension",
                "local.rehydration.witness.v1",
                "{\"external_effect\":false}",
            )
            .await
            .expect("local admission");
        let executor = store
            .open_local_compact_executor_bound("journal:e16-extension", current_fence, &lease)
            .await
            .expect("executor");
        let current = checkpoint.lease.snapshot.clone();
        executor
            .append_intent("operation:e16-extension", &checkpoint, &current)
            .await
            .expect("intent");
        let digest = checkpoint_digest(&checkpoint).expect("checkpoint digest");
        executor
            .commit_checkpoint("operation:e16-extension", &digest)
            .await
            .expect("commit");
        (
            temp,
            ExtensionData::new("turn:e16-extension"),
            lease,
            executor,
            checkpoint,
        )
    }

    #[tokio::test]
    async fn explicit_host_writer_appends_then_replays() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        let input = || {
            LocalRehydrationWitnessLifecycleInput::new(
                "turn:e16-extension",
                &turn_store,
                "operation:e16-extension",
                0,
                &checkpoint,
                &lease,
                &executor,
            )
        };

        let first = write_local_rehydration_witness_at_lifecycle(input())
            .await
            .expect("first host write");
        assert_eq!(
            first.observed_disposition,
            LocalRehydrationReplayDisposition::NotStarted
        );
        assert!(!first.witness.replayed);
        assert!(first.validate().is_ok());
        assert!(first.policy_gate_bound);
        first.validate().expect("first result validates");
        assert!(
            turn_store
                .get::<LocalRehydrationWitnessLifecycleResult>()
                .is_none()
        );

        let second = write_local_rehydration_witness_at_lifecycle(input())
            .await
            .expect("replay host write");
        assert_eq!(
            second.observed_disposition,
            LocalRehydrationReplayDisposition::Complete
        );
        assert!(second.witness.replayed);
        assert_eq!(
            second.witness.witness_sequence,
            first.witness.witness_sequence
        );
        assert!(matches!(
            codex_hepta_memory::write_local_rehydration_witness(
                &lease,
                &executor,
                "operation:e16-extension",
                &checkpoint,
                0,
            )
            .await
            .expect("third replay"),
            LocalRehydrationWitnessWrite::Replay(_)
        ));
    }

    #[tokio::test]
    async fn lifecycle_turn_binding_rejects_auto_compact_before_observation() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        let error = write_local_rehydration_witness_at_lifecycle(
            LocalRehydrationWitnessLifecycleInput::new(
                "auto-compact-e16",
                &turn_store,
                "operation:e16-extension",
                0,
                &checkpoint,
                &lease,
                &executor,
            ),
        )
        .await
        .expect_err("auto-compact turn must fail closed");
        assert!(matches!(
            error,
            LocalRehydrationWitnessLifecycleError::TurnBindingMismatch
        ));
        assert!(
            executor
                .rehydration("operation:e16-extension")
                .await
                .expect("witness lookup")
                .is_none()
        );
    }

    #[tokio::test]
    async fn lifecycle_writer_rejects_policy_that_enables_authority() {
        let (_temp, turn_store, lease, executor, checkpoint) = prepared().await;
        let mut policy = LocalDevelopmentLifecyclePolicy::qualification_only();
        policy.production_activation = true;
        let error = write_local_rehydration_witness_at_lifecycle(
            LocalRehydrationWitnessLifecycleInput::with_policy(
                policy,
                "turn:e16-extension-policy",
                &turn_store,
                "operation:e16-extension",
                0,
                &checkpoint,
                &lease,
                &executor,
            ),
        )
        .await
        .expect_err("production policy must fail closed");
        assert!(matches!(
            error,
            LocalRehydrationWitnessLifecycleError::Policy(_)
        ));
    }
}
