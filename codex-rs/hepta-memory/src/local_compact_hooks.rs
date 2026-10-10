//! Qualification-only CognitiveRuntime compact hooks backed by the existing
//! local lease/event/outbox and compact executor.
//!
//! The ordinary [`CognitiveRuntime::pre_compact`] and `post_compact` methods
//! remain pure typed envelopes.  These opt-in helpers add the smallest local
//! persistence bridge: pre records an Applied local hook intent, while post
//! records a Pending intent, appends/commits the checkpoint, writes the
//! idempotent rehydration witness, and only then marks the local intent
//! Applied.  No helper is registered automatically and none can dispatch an
//! outbox row or authorize production effects.

use codex_hepta_contracts::Sha256Digest;
use serde_json::json;

use crate::CognitiveCompactError;
use crate::CognitiveRuntime;
use crate::CompactCheckpoint;
use crate::CompactParentSnapshot;
use crate::LocalCompactExecutor;
use crate::LocalCompactExecutorError;
use crate::LocalLeaseOutbox;
use crate::LocalMemoryAdmissionState;
use crate::LocalOutcomeState;
use crate::RehydrationPlan;

pub const LOCAL_COMPACT_HOOKS_SCHEMA_VERSION: u32 = 1;
pub const LOCAL_COMPACT_HOOKS_NAMESPACE: &str = "local_development_only";
pub const LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER: bool = false;
pub const LOCAL_COMPACT_HOOKS_PROMOTION: bool = false;

const PRE_TOPIC: &str = "hepta.memory.compact.pre.v1";
const POST_TOPIC: &str = "hepta.memory.compact.post.v1";

#[derive(Debug, thiserror::Error)]
pub enum LocalCompactHooksError {
    #[error(transparent)]
    Compact(#[from] CognitiveCompactError),
    #[error(transparent)]
    Lease(#[from] crate::LocalLeaseOutboxError),
    #[error(transparent)]
    Executor(#[from] LocalCompactExecutorError),
    #[error("local compact hook target rejected: {0}")]
    TargetRejected(String),
    #[error("invalid local compact hook: {0}")]
    Invalid(String),
    #[error("local compact hook outcome is indeterminate")]
    Indeterminate,
}

/// Handles the exact bound lease, executor and pre-hook identity.  It is an
/// opt-in qualification value; constructing one does not register a callback.
#[derive(Clone)]
pub struct LocalCompactHook {
    pub schema_version: u32,
    pub namespace: String,
    pub lease: LocalLeaseOutbox,
    pub executor: LocalCompactExecutor,
    pub compact_lease: crate::CompactLease,
    pub pre_occurrence_key: String,
    pub state: LocalMemoryAdmissionState,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub promotion: bool,
}

impl std::fmt::Debug for LocalCompactHook {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LocalCompactHook")
            .field("schema_version", &self.schema_version)
            .field("namespace", &self.namespace)
            .field("lease_id", &self.lease.lease_id())
            .field("journal_id", &self.executor.journal_id())
            .field("pre_occurrence_key", &self.pre_occurrence_key)
            .field("state", &self.state)
            .field("external_effects", &self.external_effects)
            .field("kg_write_authority", &self.kg_write_authority)
            .field("production_caller", &self.production_caller)
            .field("promotion", &self.promotion)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalCompactHookReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub operation_id: String,
    pub checkpoint_sha256: Sha256Digest,
    pub state: LocalMemoryAdmissionState,
    pub rehydration: RehydrationPlan,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub promotion: bool,
}

impl CognitiveRuntime {
    /// Persist the pre-compact local intent and open the exact bound compact
    /// executor.  Legacy/unbound leases are rejected rather than inferred.
    pub async fn pre_compact_local(
        &self,
        journal_id: impl Into<String>,
        lease: &LocalLeaseOutbox,
        snapshot: CompactParentSnapshot,
    ) -> Result<LocalCompactHook, LocalCompactHooksError> {
        let compact_lease = self.pre_compact(snapshot.clone())?;
        let store = self.available_store().ok_or_else(|| {
            LocalCompactHooksError::Invalid("runtime has no available local store".to_string())
        })?;
        if !lease.is_bound_to_store(store) || !lease.is_explicitly_bound() {
            return Err(LocalCompactHooksError::Invalid(
                "compact hook requires a bound lease from the runtime's exact store".to_string(),
            ));
        }
        let binding = lease.binding().ok_or_else(|| {
            LocalCompactHooksError::Invalid("compact hook lease binding is missing".to_string())
        })?;
        if binding.authority_epoch != snapshot.fence.authority_epoch
            || binding.owner_epoch != snapshot.fence.owner_epoch
            || lease.generation() != snapshot.fence.generation
            || lease.fencing_token() != snapshot.fence.fencing_token
        {
            return Err(LocalCompactHooksError::Invalid(
                "compact hook lease and snapshot fence differ".to_string(),
            ));
        }
        let executor = store
            .open_local_compact_executor_bound(journal_id, snapshot.fence.clone(), lease)
            .await?;
        let pre_occurrence_key = format!("compact-pre:v1:{}", compact_lease.lease_sha256.as_str());
        let payload = serde_json::to_string(&json!({
            "schema_version": LOCAL_COMPACT_HOOKS_SCHEMA_VERSION,
            "kind": "compact_pre",
            "lease_sha256": compact_lease.lease_sha256,
            "context_id": snapshot.context_id,
            "parent_event_start": snapshot.parent_event_start,
            "parent_event_end": snapshot.parent_event_end,
            "external_effects": LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS,
            "kg_write_authority": LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY,
            "production_caller": LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER,
            "promotion": LOCAL_COMPACT_HOOKS_PROMOTION,
        }))
        .map_err(|error| LocalCompactHooksError::Invalid(error.to_string()))?;
        let state = ensure_applied(lease, &pre_occurrence_key, PRE_TOPIC, payload).await?;
        if state != LocalMemoryAdmissionState::Applied {
            return Err(LocalCompactHooksError::Invalid(
                "pre-compact local intent did not reach Applied".to_string(),
            ));
        }
        Ok(LocalCompactHook {
            schema_version: LOCAL_COMPACT_HOOKS_SCHEMA_VERSION,
            namespace: LOCAL_COMPACT_HOOKS_NAMESPACE.to_string(),
            lease: lease.clone(),
            executor,
            compact_lease,
            pre_occurrence_key,
            state,
            external_effects: LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS,
            kg_write_authority: LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY,
            production_caller: LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER,
            promotion: LOCAL_COMPACT_HOOKS_PROMOTION,
        })
    }

    /// Apply a checkpoint and idempotent rehydration witness under the hook's
    /// exact local lease.  A target failure records Rejected in the local
    /// event chain; an unknown outcome is never upgraded to Applied.
    pub async fn post_compact_local(
        &self,
        hook: &LocalCompactHook,
        operation_id: impl Into<String>,
        checkpoint: &CompactCheckpoint,
        current: &CompactParentSnapshot,
        expected_revision: u64,
    ) -> Result<LocalCompactHookReceipt, LocalCompactHooksError> {
        let operation_id = operation_id.into();
        let _ = self.post_compact(checkpoint, expected_revision)?;
        let store = self.available_store().ok_or_else(|| {
            LocalCompactHooksError::Invalid("runtime has no available local store".to_string())
        })?;
        if !hook.lease.is_bound_to_store(store)
            || !hook.executor.is_bound()
            || checkpoint.lease != hook.compact_lease
            || current.fence != *hook.executor.fence()
        {
            return Err(LocalCompactHooksError::Invalid(
                "post-compact hook input is not bound to the pre-hook lease/fence".to_string(),
            ));
        }
        let checkpoint_sha256 = crate::checkpoint_digest(checkpoint)
            .map_err(|error| LocalCompactHooksError::Invalid(error.to_string()))?;
        let occurrence_key = format!(
            "compact-post:v1:{}:{}",
            operation_digest(&operation_id),
            checkpoint_sha256.as_str()
        );
        let payload = serde_json::to_string(&json!({
            "schema_version": LOCAL_COMPACT_HOOKS_SCHEMA_VERSION,
            "kind": "compact_post",
            "operation_id_sha256": Sha256Digest::for_bytes(operation_id.as_bytes()),
            "checkpoint_sha256": checkpoint_sha256,
            "expected_revision": expected_revision,
            "external_effects": LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS,
            "kg_write_authority": LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY,
            "production_caller": LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER,
            "promotion": LOCAL_COMPACT_HOOKS_PROMOTION,
        }))
        .map_err(|error| LocalCompactHooksError::Invalid(error.to_string()))?;
        let prior = hook
            .lease
            .inspect_occurrence(occurrence_key.clone())
            .await?;
        let pending = match prior {
            None | Some(LocalOutcomeState::Queued) => {
                let _ = hook
                    .lease
                    .admit(occurrence_key.clone(), POST_TOPIC, payload)
                    .await?;
                true
            }
            Some(LocalOutcomeState::Committed) => false,
            Some(LocalOutcomeState::Rejected | LocalOutcomeState::RolledBack) => {
                return Err(LocalCompactHooksError::TargetRejected(
                    "post-compact command is already terminal locally".to_string(),
                ));
            }
            Some(LocalOutcomeState::Indeterminate) => {
                return Err(LocalCompactHooksError::Indeterminate);
            }
        };

        let result = async {
            hook.executor
                .append_intent(&operation_id, checkpoint, current)
                .await?;
            hook.executor
                .commit_checkpoint(&operation_id, &checkpoint_sha256)
                .await?;
            let rehydration = hook
                .executor
                .rehydrate(&operation_id, checkpoint, expected_revision)
                .await?;
            Ok::<_, LocalCompactExecutorError>(rehydration)
        }
        .await;
        match result {
            Ok(rehydration) => {
                if pending {
                    let applied = hook
                        .lease
                        .apply(
                            occurrence_key.clone(),
                            format!("compact:{}", checkpoint_sha256.as_str()),
                        )
                        .await;
                    if let Err(error) = applied
                        && hook.lease.inspect_occurrence(occurrence_key).await?
                            != Some(LocalOutcomeState::Committed)
                    {
                        return Err(error.into());
                    }
                }
                Ok(LocalCompactHookReceipt {
                    schema_version: LOCAL_COMPACT_HOOKS_SCHEMA_VERSION,
                    namespace: LOCAL_COMPACT_HOOKS_NAMESPACE.to_string(),
                    operation_id,
                    checkpoint_sha256,
                    state: LocalMemoryAdmissionState::Applied,
                    rehydration,
                    external_effects: LOCAL_COMPACT_HOOKS_EXTERNAL_EFFECTS,
                    kg_write_authority: LOCAL_COMPACT_HOOKS_KG_WRITE_AUTHORITY,
                    production_caller: LOCAL_COMPACT_HOOKS_PRODUCTION_CALLER,
                    promotion: LOCAL_COMPACT_HOOKS_PROMOTION,
                })
            }
            Err(error) => {
                if pending {
                    let reason = format!("compact_target:{}", bounded_error(&error.to_string()));
                    let _ = hook.lease.reject(occurrence_key, reason).await;
                }
                Err(LocalCompactHooksError::TargetRejected(bounded_error(
                    &error.to_string(),
                )))
            }
        }
    }
}

async fn ensure_applied(
    lease: &LocalLeaseOutbox,
    occurrence_key: &str,
    topic: &str,
    payload: String,
) -> Result<LocalMemoryAdmissionState, LocalCompactHooksError> {
    let prior = lease.inspect_occurrence(occurrence_key.to_string()).await?;
    match prior {
        Some(LocalOutcomeState::Committed) => Ok(LocalMemoryAdmissionState::Applied),
        Some(LocalOutcomeState::Rejected) => Ok(LocalMemoryAdmissionState::Rejected),
        Some(LocalOutcomeState::RolledBack) => Ok(LocalMemoryAdmissionState::Revoked),
        Some(LocalOutcomeState::Indeterminate) => Err(LocalCompactHooksError::Indeterminate),
        None | Some(LocalOutcomeState::Queued) => {
            let _ = lease
                .admit(occurrence_key.to_string(), topic, payload)
                .await?;
            match lease
                .apply(occurrence_key.to_string(), "local_hook_applied")
                .await
            {
                Ok(_) => Ok(LocalMemoryAdmissionState::Applied),
                Err(error) => {
                    if lease.inspect_occurrence(occurrence_key.to_string()).await?
                        == Some(LocalOutcomeState::Committed)
                    {
                        Ok(LocalMemoryAdmissionState::Applied)
                    } else {
                        Err(error.into())
                    }
                }
            }
        }
    }
}

fn operation_digest(operation_id: &str) -> String {
    Sha256Digest::for_bytes(operation_id.as_bytes())
        .as_str()
        .to_string()
}

fn bounded_error(error: &str) -> String {
    error.chars().take(512).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CognitiveStore;
    use crate::CompactFence;
    use crate::CompactLease;
    use crate::CompactLossReport;
    use crate::CompactProtectedRef;
    use crate::CompactSummaryReceipt;
    use crate::LocalLeaseAcquire;
    use crate::cognitive_test_support::agent_id;
    use crate::cognitive_test_support::layout;
    use tempfile::TempDir;

    fn snapshot(fence: CompactFence) -> CompactParentSnapshot {
        CompactParentSnapshot::new(
            "ctx:local-hook",
            1,
            4,
            0,
            Sha256Digest::for_bytes(b"parent"),
            fence,
        )
        .expect("snapshot")
    }

    fn checkpoint(fence: CompactFence) -> CompactCheckpoint {
        checkpoint_with_id(fence, "checkpoint:local-hook")
    }

    fn checkpoint_with_id(fence: CompactFence, checkpoint_id: &str) -> CompactCheckpoint {
        let snapshot = snapshot(fence);
        CompactCheckpoint::new(
            checkpoint_id,
            CompactLease::from_snapshot(snapshot),
            vec![
                CompactProtectedRef::new("approval:hook", "approval", true).expect("protected ref"),
            ],
            CompactSummaryReceipt::new(
                Sha256Digest::for_bytes(b"summary"),
                Sha256Digest::for_bytes(b"model"),
                Sha256Digest::for_bytes(b"policy"),
            ),
            CompactLossReport::new(Vec::new(), 0, Vec::new(), 0).expect("loss"),
            0,
        )
        .expect("checkpoint")
    }

    #[tokio::test]
    async fn runtime_hooks_persist_checkpoint_and_rehydrate_once() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(221);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let fence = CompactFence::new(2, 3, 1, "hook-fence").expect("fence");
        let expires = 4_000_000_000u64;
        let lease = match store
            .acquire_local_lease_bound(
                "lease:compact-hook",
                fence.authority_epoch,
                fence.owner_epoch,
                fence.generation,
                fence.fencing_token.clone(),
                expires,
            )
            .await
            .expect("lease")
        {
            LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
        };
        let runtime = CognitiveRuntime::from_open_result(Ok(store.clone()));
        let parent = snapshot(fence.clone());
        let hook = runtime
            .pre_compact_local("journal:compact-hook", &lease, parent.clone())
            .await
            .expect("pre hook");
        let cp = checkpoint(fence);
        let first = runtime
            .post_compact_local(&hook, "op:compact-hook", &cp, &parent, 0)
            .await
            .expect("post hook");
        assert_eq!(first.state, LocalMemoryAdmissionState::Applied);
        assert_eq!(first.rehydration.status, crate::RehydrationStatus::Complete);
        let second = runtime
            .post_compact_local(&hook, "op:compact-hook", &cp, &parent, 0)
            .await
            .expect("post replay");
        assert_eq!(second.state, LocalMemoryAdmissionState::Applied);
        let events: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM cognitive_compact_events WHERE journal_id = ?",
        )
        .bind("journal:compact-hook")
        .fetch_one(&store.pool)
        .await
        .expect("compact events");
        assert_eq!(events, 3);
        let counts = lease.snapshot_counts().await.expect("local counts");
        assert_eq!(counts.event_rows, 4);
        assert_eq!(counts.outbox_rows, 2);

        // Reusing an operation id with a different checkpoint is rejected by
        // the durable compact journal.  The local post intent must remain a
        // terminal Rejected outcome; it must never be upgraded to Applied or
        // append a second compact revision.
        let conflicting = checkpoint_with_id(
            hook.compact_lease.snapshot.fence.clone(),
            "checkpoint:local-hook-conflict",
        );
        let error = runtime
            .post_compact_local(&hook, "op:compact-hook", &conflicting, &parent, 0)
            .await
            .expect_err("conflicting operation must be rejected");
        assert!(matches!(error, LocalCompactHooksError::TargetRejected(_)));
        let conflicting_digest = crate::checkpoint_digest(&conflicting).expect("digest");
        let conflicting_occurrence = format!(
            "compact-post:v1:{}:{}",
            operation_digest("op:compact-hook"),
            conflicting_digest.as_str()
        );
        assert_eq!(
            hook.lease
                .inspect_occurrence(conflicting_occurrence)
                .await
                .expect("conflict outcome"),
            Some(LocalOutcomeState::Rejected)
        );
        let counts = hook.lease.snapshot_counts().await.expect("local counts");
        assert_eq!(counts.event_rows, 6);
        assert_eq!(counts.outbox_rows, 3);
    }
}
