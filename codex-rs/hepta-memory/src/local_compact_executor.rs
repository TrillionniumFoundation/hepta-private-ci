//! Small SQLite-backed local-development compact executor.
//!
//! This is the first real persistence seam behind the typed compact contract.
//! It owns one append-only journal in the Agent-local cognitive database and
//! applies the existing checkpoint CAS/fence rules inside `BEGIN IMMEDIATE`.
//! It deliberately does not write KG facts, invoke a scheduler, route a
//! workflow, or dispatch an external effect.  Rehydration is a read-only
//! reconstruction plan backed by a durable committed checkpoint.

use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use thiserror::Error;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CompactCheckpoint;
use crate::CompactFence;
use crate::CompactParentSnapshot;
use crate::CompactPersistenceAppend;
use crate::CompactPersistenceError;
use crate::CompactPersistenceEvent;
use crate::CompactPersistenceEventKind;
use crate::CompactPersistenceJournal;
use crate::CompactPersistenceSnapshot;
use crate::CompactPersistenceState;
use crate::CompactReconcileOutcome;
use crate::CompactRehydrationRecord;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;
use crate::RehydrationPlan;
use crate::RehydrationStatus;
use crate::checkpoint_digest;

pub const LOCAL_COMPACT_EXECUTOR_NAMESPACE: &str = "local_development_only";
pub const LOCAL_COMPACT_EXECUTOR_SCHEMA_VERSION: u32 = 1;
pub const LOCAL_COMPACT_EXECUTOR_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_COMPACT_EXECUTOR_KG_WRITE_AUTHORITY: bool = false;
const MAX_JOURNAL_EVENTS: usize = 4_096;

#[derive(Debug, Error)]
pub enum LocalCompactExecutorError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Lease(#[from] LocalLeaseOutboxError),
    #[error(transparent)]
    Persistence(#[from] CompactPersistenceError),
    #[error("invalid local compact executor input: {0}")]
    Invalid(String),
    #[error("local compact executor journal is corrupt: {0}")]
    Corrupt(String),
    #[error("local compact executor serialization failed: {0}")]
    Serialization(String),
    #[error("local compact executor clock failed: {0}")]
    Clock(String),
}

/// Cross-journal binding persisted on every compact event written by the
/// schema-bound executor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalCompactLeaseBinding {
    pub lease_id: String,
    pub lease_head_sha256: codex_hepta_contracts::Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
}

/// One Agent-local append-only checkpoint executor.
///
/// The executor is intentionally explicit about its scope.  It is suitable
/// for local development, replay, and bounded shadow runs only; callers must
/// not treat its successful commit as a production promotion or an external
/// effect receipt.
#[derive(Clone)]
pub struct LocalCompactExecutor {
    store: CognitiveStore,
    journal_id: String,
    fence: CompactFence,
    lease_binding: Option<LocalCompactLeaseBinding>,
    /// The exact lease handle used to open a schema-bound executor.  Keeping
    /// the handle lets every later mutation revalidate the live lease head,
    /// state, journal chains, and expiry while holding the same SQLite write
    /// transaction as the compact append.  A binding digest alone is not a
    /// capability: it cannot detect a lease release/expiry after open.
    bound_lease: Option<LocalLeaseOutbox>,
}

impl LocalCompactExecutor {
    pub(crate) async fn open(
        store: &CognitiveStore,
        journal_id: impl Into<String>,
        fence: CompactFence,
    ) -> Result<Self, LocalCompactExecutorError> {
        Self::open_with_binding(
            store, journal_id, fence, /*lease_binding*/ None, /*bound_lease*/ None,
        )
        .await
    }

    pub(crate) async fn open_bound(
        store: &CognitiveStore,
        journal_id: impl Into<String>,
        fence: CompactFence,
        lease: &LocalLeaseOutbox,
    ) -> Result<Self, LocalCompactExecutorError> {
        if !store.is_same_local_store(lease.store()) {
            return Err(LocalCompactExecutorError::Invalid(
                "compact executor and lease belong to different local stores".to_string(),
            ));
        }
        let binding = lease.binding().ok_or_else(|| {
            LocalCompactExecutorError::Invalid(
                "schema-bound compact executor requires an explicitly bound lease".to_string(),
            )
        })?;
        if binding.authority_epoch != fence.authority_epoch
            || binding.owner_epoch != fence.owner_epoch
            || lease.generation() != fence.generation
            || lease.fencing_token() != fence.fencing_token
        {
            return Err(LocalCompactExecutorError::Invalid(
                "lease binding does not match compact fence".to_string(),
            ));
        }
        let mut transaction = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let current = lease
            .verify_current_in_transaction(&mut transaction)
            .await?;
        let binding = LocalCompactLeaseBinding {
            lease_id: current.lease_id.clone(),
            lease_head_sha256: current.lease_sha256,
            authority_epoch: binding.authority_epoch,
            owner_epoch: binding.owner_epoch,
            lease_expires_at_unix_seconds: binding.lease_expires_at_unix_seconds,
        };
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Self::open_with_binding(store, journal_id, fence, Some(binding), Some(lease.clone())).await
    }

    async fn open_with_binding(
        store: &CognitiveStore,
        journal_id: impl Into<String>,
        fence: CompactFence,
        lease_binding: Option<LocalCompactLeaseBinding>,
        bound_lease: Option<LocalLeaseOutbox>,
    ) -> Result<Self, LocalCompactExecutorError> {
        let journal_id = journal_id.into();
        validate_text(&journal_id, "journal id", /*max_bytes*/ 512)?;
        validate_fence(&fence)?;
        let executor = Self {
            store: store.clone(),
            journal_id,
            fence,
            lease_binding,
            bound_lease,
        };
        // Opening always verifies the complete chain.  This is intentionally
        // done before any mutation so a damaged journal fails closed.
        let mut transaction = executor
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let _ = executor.load_journal(&mut transaction).await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(executor)
    }

    pub fn journal_id(&self) -> &str {
        &self.journal_id
    }

    pub fn fence(&self) -> &CompactFence {
        &self.fence
    }

    pub fn lease_binding(&self) -> Option<&LocalCompactLeaseBinding> {
        self.lease_binding.as_ref()
    }

    /// Whether this executor was opened with an explicit live lease handle.
    ///
    /// The legacy unbound executor remains available for read-only/shadow
    /// compatibility, but only a bound executor revalidates the lease inside
    /// every mutating transaction.
    pub fn is_bound(&self) -> bool {
        self.bound_lease.is_some()
    }

    /// Whether this executor was opened from the exact lease handle supplied
    /// by the host.  This is an identity check only; it does not consult or
    /// mutate SQLite and grants no additional authority.
    pub(crate) fn is_bound_to_lease(&self, lease: &LocalLeaseOutbox) -> bool {
        let Some(bound_lease) = self.bound_lease.as_ref() else {
            return false;
        };
        self.store.is_same_local_store(lease.store())
            && bound_lease.lease_id() == lease.lease_id()
            && bound_lease.owner_agent_id() == lease.owner_agent_id()
            && bound_lease.generation() == lease.generation()
            && bound_lease.fencing_token() == lease.fencing_token()
            && bound_lease.binding() == lease.binding()
    }

    pub(crate) fn store(&self) -> &CognitiveStore {
        &self.store
    }

    /// Appends an idempotent checkpoint intent under the current parent CAS.
    pub async fn append_intent(
        &self,
        operation_id: impl Into<String>,
        checkpoint: &CompactCheckpoint,
        current: &CompactParentSnapshot,
    ) -> Result<CompactPersistenceAppend, LocalCompactExecutorError> {
        let operation_id = operation_id.into();
        self.mutate(|journal| journal.append_intent(operation_id, checkpoint, current))
            .await
    }

    /// Commits a previously appended checkpoint intent.
    pub async fn commit_checkpoint(
        &self,
        operation_id: &str,
        checkpoint_sha256: &codex_hepta_contracts::Sha256Digest,
    ) -> Result<CompactPersistenceAppend, LocalCompactExecutorError> {
        self.mutate(|journal| journal.commit_checkpoint(operation_id, checkpoint_sha256))
            .await
    }

    /// Quarantines an uncertain local commit.  Unknown outcomes never become
    /// a successful receipt implicitly.
    pub async fn mark_indeterminate(
        &self,
        operation_id: &str,
        reason_code: impl Into<String>,
    ) -> Result<CompactPersistenceAppend, LocalCompactExecutorError> {
        let reason_code = reason_code.into();
        self.mutate(|journal| journal.mark_indeterminate(operation_id, reason_code))
            .await
    }

    /// Reconciles a quarantined operation explicitly.
    pub async fn reconcile(
        &self,
        operation_id: &str,
        outcome: CompactReconcileOutcome,
    ) -> Result<CompactPersistenceAppend, LocalCompactExecutorError> {
        self.mutate(|journal| journal.reconcile(operation_id, outcome))
            .await
    }

    /// Reopens and verifies the durable append-only journal.
    pub async fn snapshot(&self) -> Result<CompactPersistenceSnapshot, LocalCompactExecutorError> {
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let journal = self.load_journal(&mut transaction).await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(journal.snapshot())
    }

    /// Returns the durable state for one operation after chain verification.
    pub async fn state(
        &self,
        operation_id: &str,
    ) -> Result<Option<CompactPersistenceState>, LocalCompactExecutorError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let snapshot = self.snapshot().await?;
        let journal = CompactPersistenceJournal::reopen(snapshot)?;
        Ok(journal.state(operation_id))
    }

    /// Reads the committed checkpoint's rehydration plan and any durable local
    /// witness without appending an event.
    ///
    /// This is the extension-facing read seam.  It verifies the complete
    /// journal, the committed operation state, and the exact checkpoint
    /// digest/revision binding.  A missing witness is represented as
    /// `NotStarted`; a present witness upgrades the returned plan to
    /// `Complete`.  The method never writes KG/projection rows, routes a
    /// request, invokes a provider, or mutates the compact journal.
    pub async fn read_rehydration(
        &self,
        operation_id: &str,
        checkpoint: &CompactCheckpoint,
        expected_revision: u64,
    ) -> Result<LocalRehydrationRead, LocalCompactExecutorError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let plan = checkpoint
            .rehydration_plan(expected_revision)
            .map_err(|error| LocalCompactExecutorError::Invalid(error.to_string()))?;
        let snapshot = self.snapshot().await?;
        let journal = CompactPersistenceJournal::reopen(snapshot)?;
        if journal.state(operation_id) != Some(CompactPersistenceState::Committed) {
            return Err(LocalCompactExecutorError::Invalid(format!(
                "operation {operation_id} is not durably committed"
            )));
        }
        let expected_digest = checkpoint_digest(checkpoint)?;
        let intent_matches = journal.entries().iter().any(|entry| {
            entry.operation_id == operation_id
                && matches!(
                    &entry.kind,
                    CompactPersistenceEventKind::Intent {
                        checkpoint_sha256,
                        ..
                    } if *checkpoint_sha256 == expected_digest
                )
        });
        if !intent_matches {
            return Err(LocalCompactExecutorError::Corrupt(format!(
                "operation {operation_id} is committed with a different checkpoint"
            )));
        }
        let witness = journal.rehydration(operation_id).cloned();
        if let Some(witness) = witness.as_ref()
            && (witness.checkpoint_sha256 != expected_digest
                || witness.expected_revision != expected_revision
                || witness.sequence == 0)
        {
            return Err(LocalCompactExecutorError::Corrupt(format!(
                "operation {operation_id} has an invalid rehydration witness"
            )));
        }
        let status = if witness.is_some() {
            RehydrationStatus::Complete
        } else {
            RehydrationStatus::NotStarted
        };
        Ok(LocalRehydrationRead {
            plan: RehydrationPlan { status, ..plan },
            checkpoint_sha256: expected_digest,
            witness,
        })
    }

    /// Executes the local rehydration step for a committed checkpoint.  The
    /// plan remains read-only, while an append-only local witness is persisted
    /// so restart/reopen can replay the acknowledgement without duplicating
    /// metadata.  No KG/projection row or external effect is written or
    /// claimed.
    pub async fn rehydrate(
        &self,
        operation_id: &str,
        checkpoint: &CompactCheckpoint,
        expected_revision: u64,
    ) -> Result<RehydrationPlan, LocalCompactExecutorError> {
        let read = self
            .read_rehydration(operation_id, checkpoint, expected_revision)
            .await?;
        let _ = self
            .mutate(|journal| {
                journal.record_rehydration(operation_id, &read.checkpoint_sha256, expected_revision)
            })
            .await?;
        Ok(RehydrationPlan {
            status: RehydrationStatus::Complete,
            ..read.plan
        })
    }

    /// Returns the durable local rehydration witness after reopening and
    /// verifying the complete hash chain.
    pub async fn rehydration(
        &self,
        operation_id: &str,
    ) -> Result<Option<CompactRehydrationRecord>, LocalCompactExecutorError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let snapshot = self.snapshot().await?;
        let journal = CompactPersistenceJournal::reopen(snapshot)?;
        Ok(journal.rehydration(operation_id).cloned())
    }

    async fn mutate<F>(
        &self,
        mutation: F,
    ) -> Result<CompactPersistenceAppend, LocalCompactExecutorError>
    where
        F: FnOnce(
            &mut CompactPersistenceJournal,
        ) -> Result<CompactPersistenceAppend, CompactPersistenceError>,
    {
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        if let Some(lease) = self.bound_lease.as_ref() {
            let current = lease
                .verify_current_in_transaction(&mut transaction)
                .await?;
            let binding = self.lease_binding.as_ref().ok_or_else(|| {
                LocalCompactExecutorError::Invalid(
                    "bound compact executor is missing its lease binding".to_string(),
                )
            })?;
            if current.lease_id != binding.lease_id
                || current.lease_sha256 != binding.lease_head_sha256
                || current.authority_epoch != Some(binding.authority_epoch)
                || current.owner_epoch != Some(binding.owner_epoch)
                || current.lease_expires_at_unix_seconds
                    != Some(binding.lease_expires_at_unix_seconds)
            {
                return Err(LocalLeaseOutboxError::StaleFence(
                    "bound compact executor lease head changed after open".to_string(),
                )
                .into());
            }
        }
        let mut journal = self.load_journal(&mut transaction).await?;
        let before = journal.entries().len();
        let result = mutation(&mut journal)?;
        for entry in &journal.entries()[before..] {
            self.insert_event(&mut transaction, entry).await?;
        }
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(result)
    }

    pub(crate) async fn load_journal(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<CompactPersistenceJournal, LocalCompactExecutorError> {
        let rows = sqlx::query(
            "SELECT sequence, owner_agent_id, authority_epoch, owner_epoch,
                    generation, fencing_token,
                    event_json, previous_sha256, event_sha256,
                    lease_id, lease_head_sha256, compact_previous_sha256,
                    compact_event_binding_sha256
             FROM cognitive_compact_events
             WHERE journal_id = ?
             ORDER BY sequence",
        )
        .bind(&self.journal_id)
        .fetch_all(&mut **transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        if rows.len() > MAX_JOURNAL_EVENTS {
            return Err(LocalCompactExecutorError::Corrupt(format!(
                "journal exceeds {MAX_JOURNAL_EVENTS} event reopen limit"
            )));
        }
        let mut entries = Vec::with_capacity(rows.len());
        for row in rows {
            let sequence: i64 = row
                .try_get("sequence")
                .map_err(crate::cognitive_store::unavailable)?;
            let owner_agent_id: String = row
                .try_get("owner_agent_id")
                .map_err(crate::cognitive_store::unavailable)?;
            let authority_epoch: Option<i64> = row
                .try_get("authority_epoch")
                .map_err(crate::cognitive_store::unavailable)?;
            let owner_epoch: Option<i64> = row
                .try_get("owner_epoch")
                .map_err(crate::cognitive_store::unavailable)?;
            let generation: i64 = row
                .try_get("generation")
                .map_err(crate::cognitive_store::unavailable)?;
            let fencing_token: String = row
                .try_get("fencing_token")
                .map_err(crate::cognitive_store::unavailable)?;
            let event_json: String = row
                .try_get("event_json")
                .map_err(crate::cognitive_store::unavailable)?;
            let previous_sha256: String = row
                .try_get("previous_sha256")
                .map_err(crate::cognitive_store::unavailable)?;
            let event_sha256: String = row
                .try_get("event_sha256")
                .map_err(crate::cognitive_store::unavailable)?;
            let lease_id: Option<String> = row
                .try_get("lease_id")
                .map_err(crate::cognitive_store::unavailable)?;
            let lease_head_sha256: Option<String> = row
                .try_get("lease_head_sha256")
                .map_err(crate::cognitive_store::unavailable)?;
            let compact_previous_sha256: Option<String> = row
                .try_get("compact_previous_sha256")
                .map_err(crate::cognitive_store::unavailable)?;
            let compact_event_binding_sha256: Option<String> = row
                .try_get("compact_event_binding_sha256")
                .map_err(crate::cognitive_store::unavailable)?;
            let authority_epoch = authority_epoch
                .and_then(|value| u64::try_from(value).ok())
                .ok_or_else(|| {
                    LocalCompactExecutorError::Corrupt(
                        "event row is missing a valid authority epoch".to_string(),
                    )
                })?;
            let owner_epoch = owner_epoch
                .and_then(|value| u64::try_from(value).ok())
                .ok_or_else(|| {
                    LocalCompactExecutorError::Corrupt(
                        "event row is missing a valid owner epoch".to_string(),
                    )
                })?;
            if owner_agent_id != self.store.owner_agent_id().as_str()
                || authority_epoch != self.fence.authority_epoch
                || owner_epoch != self.fence.owner_epoch
                || generation != i64::try_from(self.fence.generation).unwrap_or(i64::MAX)
                || fencing_token != self.fence.fencing_token
            {
                return Err(LocalCompactExecutorError::Corrupt(
                    "event owner or fence does not match executor".to_string(),
                ));
            }
            let entry: CompactPersistenceEvent = serde_json::from_str(&event_json)
                .map_err(|error| LocalCompactExecutorError::Serialization(error.to_string()))?;
            if sequence != i64::try_from(entry.sequence).unwrap_or(i64::MAX)
                || authority_epoch != entry.authority_epoch
                || owner_epoch != entry.owner_epoch
                || previous_sha256 != entry.previous_sha256.as_str()
                || event_sha256 != entry.event_sha256.as_str()
            {
                return Err(LocalCompactExecutorError::Corrupt(
                    "event row metadata does not match its serialized event".to_string(),
                ));
            }
            match (
                &self.lease_binding,
                lease_id,
                lease_head_sha256,
                compact_previous_sha256,
                compact_event_binding_sha256,
            ) {
                (None, None, None, None, None) => {}
                (
                    Some(binding),
                    Some(lease_id),
                    Some(lease_head_sha256),
                    Some(compact_previous_sha256),
                    Some(compact_event_binding_sha256),
                ) => {
                    let lease_head_sha256 = codex_hepta_contracts::Sha256Digest::parse(
                        lease_head_sha256,
                    )
                    .map_err(|_| {
                        LocalCompactExecutorError::Corrupt(
                            "compact lease head digest is invalid".to_string(),
                        )
                    })?;
                    let compact_previous_sha256 =
                        codex_hepta_contracts::Sha256Digest::parse(compact_previous_sha256)
                            .map_err(|_| {
                                LocalCompactExecutorError::Corrupt(
                                    "compact previous digest is invalid".to_string(),
                                )
                            })?;
                    let stored_binding =
                        codex_hepta_contracts::Sha256Digest::parse(compact_event_binding_sha256)
                            .map_err(|_| {
                                LocalCompactExecutorError::Corrupt(
                                    "compact event binding digest is invalid".to_string(),
                                )
                            })?;
                    if lease_id != binding.lease_id
                        || lease_head_sha256 != binding.lease_head_sha256
                        || compact_previous_sha256.as_str() != previous_sha256
                    {
                        return Err(LocalCompactExecutorError::Corrupt(
                            "compact lease/head binding mismatch".to_string(),
                        ));
                    }
                    let expected_binding = compact_event_binding_digest(
                        &lease_id,
                        &lease_head_sha256,
                        &compact_previous_sha256,
                        &entry.event_sha256,
                    );
                    if stored_binding != expected_binding {
                        return Err(LocalCompactExecutorError::Corrupt(
                            "compact event binding digest mismatch".to_string(),
                        ));
                    }
                    verify_historical_compact_lease_binding(
                        transaction,
                        self.store.owner_agent_id(),
                        &lease_id,
                        &lease_head_sha256,
                        authority_epoch,
                        owner_epoch,
                        &fencing_token,
                        self.fence.generation,
                    )
                    .await?;
                }
                _ => {
                    return Err(LocalCompactExecutorError::Corrupt(
                        "compact lease binding columns are partially populated".to_string(),
                    ));
                }
            }
            entries.push(entry);
        }
        let head_sha256 = entries
            .last()
            .map(|entry| entry.event_sha256.clone())
            .unwrap_or_else(|| {
                codex_hepta_contracts::Sha256Digest::for_bytes(
                    b"hepta-memory:compact-persistence:empty:v1",
                )
            });
        let snapshot = CompactPersistenceSnapshot {
            schema_version: crate::COMPACT_PERSISTENCE_SCHEMA_VERSION,
            namespace: crate::COMPACT_PERSISTENCE_NAMESPACE.to_string(),
            fence: self.fence.clone(),
            entries,
            head_sha256,
        };
        CompactPersistenceJournal::reopen(snapshot).map_err(Into::into)
    }

    pub(crate) async fn insert_event(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        entry: &CompactPersistenceEvent,
    ) -> Result<(), LocalCompactExecutorError> {
        let event_json = serde_json::to_string(entry)
            .map_err(|error| LocalCompactExecutorError::Serialization(error.to_string()))?;
        let recorded_at_unix_seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| LocalCompactExecutorError::Clock(error.to_string()))?
            .as_secs();
        let recorded_at_unix_seconds = i64::try_from(recorded_at_unix_seconds)
            .map_err(|_| LocalCompactExecutorError::Clock("timestamp overflow".to_string()))?;
        sqlx::query(
            "INSERT INTO cognitive_compact_events (
                journal_id, owner_agent_id, authority_epoch, owner_epoch,
                sequence, generation, fencing_token,
                event_json, previous_sha256, event_sha256,
                lease_id, lease_head_sha256, compact_previous_sha256,
                compact_event_binding_sha256, recorded_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&self.journal_id)
        .bind(self.store.owner_agent_id().as_str())
        .bind(i64::try_from(self.fence.authority_epoch).map_err(|_| {
            LocalCompactExecutorError::Invalid("authority epoch overflow".to_string())
        })?)
        .bind(
            i64::try_from(self.fence.owner_epoch).map_err(|_| {
                LocalCompactExecutorError::Invalid("owner epoch overflow".to_string())
            })?,
        )
        .bind(i64::try_from(entry.sequence).map_err(|_| {
            LocalCompactExecutorError::Invalid("event sequence overflow".to_string())
        })?)
        .bind(i64::try_from(entry.generation).map_err(|_| {
            LocalCompactExecutorError::Invalid("event generation overflow".to_string())
        })?)
        .bind(&entry.fencing_token)
        .bind(event_json)
        .bind(entry.previous_sha256.as_str())
        .bind(entry.event_sha256.as_str())
        .bind(
            self.lease_binding
                .as_ref()
                .map(|binding| binding.lease_id.as_str()),
        )
        .bind(
            self.lease_binding
                .as_ref()
                .map(|binding| binding.lease_head_sha256.as_str()),
        )
        .bind(
            self.lease_binding
                .as_ref()
                .map(|_| entry.previous_sha256.as_str()),
        )
        .bind(self.lease_binding.as_ref().map(|binding| {
            compact_event_binding_digest(
                &binding.lease_id,
                &binding.lease_head_sha256,
                &entry.previous_sha256,
                &entry.event_sha256,
            )
            .as_str()
            .to_string()
        }))
        .bind(recorded_at_unix_seconds)
        .execute(&mut **transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        Ok(())
    }
}

/// Pure read result for a local compact rehydration attempt.
///
/// The optional witness is local append-only metadata.  This value itself is
/// not an authority grant and is safe to pass to an explicit host adapter that
/// retains only digest metadata.
#[derive(Clone, Debug, serde::Deserialize, Eq, PartialEq, serde::Serialize)]
pub struct LocalRehydrationRead {
    pub plan: RehydrationPlan,
    pub checkpoint_sha256: codex_hepta_contracts::Sha256Digest,
    pub witness: Option<CompactRehydrationRecord>,
}

impl CognitiveStore {
    /// Opens the local-development-only compact checkpoint executor.
    pub async fn open_local_compact_executor(
        &self,
        journal_id: impl Into<String>,
        fence: CompactFence,
    ) -> Result<LocalCompactExecutor, LocalCompactExecutorError> {
        LocalCompactExecutor::open(self, journal_id, fence).await
    }

    /// Opens a compact executor whose every SQLite event row is bound to the
    /// exact active local lease head and explicit epochs/expiry.
    pub async fn open_local_compact_executor_bound(
        &self,
        journal_id: impl Into<String>,
        fence: CompactFence,
        lease: &LocalLeaseOutbox,
    ) -> Result<LocalCompactExecutor, LocalCompactExecutorError> {
        LocalCompactExecutor::open_bound(self, journal_id, fence, lease).await
    }
}

fn compact_event_binding_digest(
    lease_id: &str,
    lease_head_sha256: &codex_hepta_contracts::Sha256Digest,
    compact_previous_sha256: &codex_hepta_contracts::Sha256Digest,
    event_sha256: &codex_hepta_contracts::Sha256Digest,
) -> codex_hepta_contracts::Sha256Digest {
    let mut hasher = Sha256::new();
    hasher.update(b"hepta-memory:compact-event-binding:v1");
    hasher.update((lease_id.len() as u64).to_be_bytes());
    hasher.update(lease_id.as_bytes());
    hasher.update(lease_head_sha256.as_str().as_bytes());
    hasher.update(compact_previous_sha256.as_str().as_bytes());
    hasher.update(event_sha256.as_str().as_bytes());
    codex_hepta_contracts::Sha256Digest::from_sha256_output(hasher.finalize())
}

/// Return the expiry stored on the exact historical lease row that supplied a
/// compact event's lease head.  Compact rows retain only the lease id/head
/// digest, so the lookup intentionally covers the complete lease history (not
/// just the current active row): a compact witness remains auditable after a
/// host explicitly releases or rolls back its lease.  A digest that was never
/// granted by this owner/fence is an orphan/foreign binding and fails closed.
#[allow(clippy::too_many_arguments)]
async fn historical_compact_lease_expiry(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    lease_id: &str,
    lease_head_sha256: &codex_hepta_contracts::Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &str,
) -> Result<u64, LocalCompactExecutorError> {
    let authority_epoch = i64::try_from(authority_epoch).map_err(|_| {
        LocalCompactExecutorError::Corrupt("compact authority epoch overflows SQLite".to_string())
    })?;
    let owner_epoch = i64::try_from(owner_epoch).map_err(|_| {
        LocalCompactExecutorError::Corrupt("compact owner epoch overflows SQLite".to_string())
    })?;
    let generation = i64::try_from(generation).map_err(|_| {
        LocalCompactExecutorError::Corrupt("compact generation overflows SQLite".to_string())
    })?;
    let rows = sqlx::query(
        "SELECT lease_expires_at_unix_seconds
         FROM cognitive_local_leases
         WHERE lease_id = ?
           AND owner_agent_id = ?
           AND authority_epoch = ?
           AND owner_epoch = ?
           AND generation = ?
           AND fencing_token = ?
           AND lease_sha256 = ?",
    )
    .bind(lease_id)
    .bind(owner.as_str())
    .bind(authority_epoch)
    .bind(owner_epoch)
    .bind(generation)
    .bind(fencing_token)
    .bind(lease_head_sha256.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() != 1 {
        return Err(LocalCompactExecutorError::Corrupt(format!(
            "compact event lease binding is not an exact historical lease head (found {} rows)",
            rows.len()
        )));
    }
    let expiry: Option<i64> = rows[0]
        .try_get("lease_expires_at_unix_seconds")
        .map_err(crate::cognitive_store::unavailable)?;
    let expiry = expiry
        .and_then(|value| u64::try_from(value).ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            LocalCompactExecutorError::Corrupt(
                "compact event lease head has no valid persisted expiry".to_string(),
            )
        })?;
    Ok(expiry)
}

#[allow(clippy::too_many_arguments)]
async fn verify_historical_compact_lease_binding(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    lease_id: &str,
    lease_head_sha256: &codex_hepta_contracts::Sha256Digest,
    authority_epoch: u64,
    owner_epoch: u64,
    fencing_token: &str,
    generation: u64,
) -> Result<(), LocalCompactExecutorError> {
    let _ = historical_compact_lease_expiry(
        transaction,
        owner,
        lease_id,
        lease_head_sha256,
        authority_epoch,
        owner_epoch,
        generation,
        fencing_token,
    )
    .await?;
    Ok(())
}

/// Read the fence/binding descriptor from the first row of a journal.  The
/// complete row set is still validated by `load_journal`; this helper only
/// supplies the expected fence/binding needed to run that validator during a
/// store-wide reopen audit.
async fn compact_journal_descriptor(
    transaction: &mut Transaction<'_, Sqlite>,
    journal_id: &str,
    owner: &AgentId,
) -> Result<(CompactFence, Option<LocalCompactLeaseBinding>), LocalCompactExecutorError> {
    let row = sqlx::query(
        "SELECT owner_agent_id, authority_epoch, owner_epoch,
                generation, fencing_token,
                lease_id, lease_head_sha256, compact_previous_sha256,
                compact_event_binding_sha256
         FROM cognitive_compact_events
         WHERE journal_id = ?
         ORDER BY sequence
         LIMIT 1",
    )
    .bind(journal_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?
    .ok_or_else(|| {
        LocalCompactExecutorError::Corrupt(
            "compact journal descriptor disappeared during reopen audit".to_string(),
        )
    })?;
    let owner_agent_id: String = row
        .try_get("owner_agent_id")
        .map_err(crate::cognitive_store::unavailable)?;
    validate_text(&owner_agent_id, "owner agent id", /*max_bytes*/ 128)?;
    let authority_epoch: i64 = row
        .try_get("authority_epoch")
        .map_err(crate::cognitive_store::unavailable)?;
    let owner_epoch: i64 = row
        .try_get("owner_epoch")
        .map_err(crate::cognitive_store::unavailable)?;
    let generation: i64 = row
        .try_get("generation")
        .map_err(crate::cognitive_store::unavailable)?;
    let authority_epoch = u64::try_from(authority_epoch)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            LocalCompactExecutorError::Corrupt(
                "compact journal descriptor has an invalid authority epoch".to_string(),
            )
        })?;
    let owner_epoch = u64::try_from(owner_epoch)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            LocalCompactExecutorError::Corrupt(
                "compact journal descriptor has an invalid owner epoch".to_string(),
            )
        })?;
    let generation = u64::try_from(generation)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| {
            LocalCompactExecutorError::Corrupt(
                "compact journal descriptor has an invalid generation".to_string(),
            )
        })?;
    let fencing_token: String = row
        .try_get("fencing_token")
        .map_err(crate::cognitive_store::unavailable)?;
    validate_text(&fencing_token, "fencing token", /*max_bytes*/ 256)?;
    let fence = CompactFence::new(
        authority_epoch,
        owner_epoch,
        generation,
        fencing_token.clone(),
    )
    .map_err(|error| LocalCompactExecutorError::Corrupt(error.to_string()))?;

    let lease_id: Option<String> = row
        .try_get("lease_id")
        .map_err(crate::cognitive_store::unavailable)?;
    let lease_head_sha256: Option<String> = row
        .try_get("lease_head_sha256")
        .map_err(crate::cognitive_store::unavailable)?;
    let compact_previous_sha256: Option<String> = row
        .try_get("compact_previous_sha256")
        .map_err(crate::cognitive_store::unavailable)?;
    let compact_event_binding_sha256: Option<String> = row
        .try_get("compact_event_binding_sha256")
        .map_err(crate::cognitive_store::unavailable)?;
    let binding = match (
        lease_id,
        lease_head_sha256,
        compact_previous_sha256,
        compact_event_binding_sha256,
    ) {
        (None, None, None, None) => None,
        (Some(lease_id), Some(lease_head_sha256), Some(compact_previous_sha256), Some(binding)) => {
            validate_text(&lease_id, "lease id", /*max_bytes*/ 512)?;
            let lease_head_sha256 = codex_hepta_contracts::Sha256Digest::parse(lease_head_sha256)
                .map_err(|_| {
                LocalCompactExecutorError::Corrupt(
                    "compact lease head digest is invalid".to_string(),
                )
            })?;
            let compact_previous_sha256 = codex_hepta_contracts::Sha256Digest::parse(
                compact_previous_sha256,
            )
            .map_err(|_| {
                LocalCompactExecutorError::Corrupt("compact previous digest is invalid".to_string())
            })?;
            let _binding = codex_hepta_contracts::Sha256Digest::parse(binding).map_err(|_| {
                LocalCompactExecutorError::Corrupt(
                    "compact event binding digest is invalid".to_string(),
                )
            })?;
            let lease_expires_at_unix_seconds = historical_compact_lease_expiry(
                transaction,
                owner,
                &lease_id,
                &lease_head_sha256,
                authority_epoch,
                owner_epoch,
                generation,
                &fence.fencing_token,
            )
            .await?;
            let _ = compact_previous_sha256;
            Some(LocalCompactLeaseBinding {
                lease_id,
                lease_head_sha256,
                authority_epoch,
                owner_epoch,
                lease_expires_at_unix_seconds,
            })
        }
        _ => {
            return Err(LocalCompactExecutorError::Corrupt(
                "compact lease binding columns are partially populated".to_string(),
            ));
        }
    };
    Ok((fence, binding))
}

/// Reopen-time integrity verification for every persisted compact journal.
///
/// The direct executor loader historically filtered by `owner_agent_id`,
/// which made a foreign row sharing a journal id invisible.  This audit first
/// enumerates journal ids without an owner predicate, then runs the exact
/// owner/fence/hash/binding validator over every row.  It is deliberately
/// read-only and has no lifecycle, scheduler, KG, provider, or external
/// effect behavior.
pub(crate) async fn verify_local_compact_events(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool
        .begin()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let journal_ids: Vec<String> = sqlx::query_scalar(
        "SELECT DISTINCT journal_id FROM cognitive_compact_events ORDER BY journal_id",
    )
    .fetch_all(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let audit_store =
        CognitiveStore::from_read_only_pool(pool.clone(), owner.clone(), PathBuf::new());
    for journal_id in journal_ids {
        validate_text(&journal_id, "journal id", /*max_bytes*/ 512)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let (fence, lease_binding) =
            compact_journal_descriptor(&mut transaction, &journal_id, owner)
                .await
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let executor = LocalCompactExecutor {
            store: audit_store.clone(),
            journal_id,
            fence,
            lease_binding,
            bound_lease: None,
        };
        executor
            .load_journal(&mut transaction)
            .await
            .map_err(|error| match error {
                LocalCompactExecutorError::Store(error) => error,
                other => CognitiveStoreError::Corrupt(other.to_string()),
            })?;
    }
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}

/// Verify the compact journals that can be bound to one local lease while a
/// caller-owned SQLite transaction is already open.
///
/// Lifecycle terminalization must not call [`verify_local_compact_events`]
/// here: that public reopen audit starts a second transaction, which can
/// deadlock against the `BEGIN IMMEDIATE` held by `release`, `rollback`, or
/// `expire_lease`.  This helper deliberately performs only reads through the
/// supplied transaction and reuses the exact descriptor/row loader used by
/// the store-wide audit.
///
/// Journal ids are selected without an owner predicate so a foreign row that
/// shares a target journal cannot be hidden by the normal owner lookup.  The
/// historical lease-head predicate also catches a tamper that rewrites
/// `lease_id` while retaining the immutable lease-head witness.  Unrelated
/// owner-only or legacy/unbound journals are intentionally out of scope: a
/// terminal transition audits only rows that can be bound to this lease.
/// Once a journal is related to the target lease, every row must retain that
/// exact lease id; mixed/foreign rows then fail closed before the terminal
/// lease append.
pub(crate) async fn verify_local_compact_journals_for_lease_in_transaction(
    store: &CognitiveStore,
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<(), LocalCompactExecutorError> {
    validate_text(lease_id, "lease id", /*max_bytes*/ 512)?;
    let owner = store.owner_agent_id();
    let journal_ids: Vec<String> = sqlx::query_scalar(
        "SELECT DISTINCT journal_id
         FROM cognitive_compact_events
         WHERE lease_id = ?
            OR lease_head_sha256 IN (
                SELECT lease_sha256
                FROM cognitive_local_leases
                WHERE lease_id = ? AND owner_agent_id = ?
            )
         ORDER BY journal_id",
    )
    .bind(lease_id)
    .bind(lease_id)
    .bind(owner.as_str())
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;

    for journal_id in journal_ids {
        validate_text(&journal_id, "journal id", /*max_bytes*/ 512)?;

        // A row selected by a target lease id or historical lease-head digest
        // makes the whole journal part of this lifecycle decision.  A
        // different/null lease id in that journal is not an unrelated
        // journal: it is a mixed binding and must be rejected explicitly.
        let target_related_rows: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)
             FROM cognitive_compact_events
             WHERE journal_id = ?
               AND (
                   lease_id = ?
                   OR lease_head_sha256 IN (
                       SELECT lease_sha256
                       FROM cognitive_local_leases
                       WHERE lease_id = ? AND owner_agent_id = ?
                   )
               )",
        )
        .bind(&journal_id)
        .bind(lease_id)
        .bind(lease_id)
        .bind(owner.as_str())
        .fetch_one(&mut **transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        if target_related_rows != 0 {
            let mismatched_lease_rows: i64 = sqlx::query_scalar(
                "SELECT COUNT(*)
                 FROM cognitive_compact_events
                 WHERE journal_id = ?
                   AND (lease_id IS NULL OR lease_id != ?)",
            )
            .bind(&journal_id)
            .bind(lease_id)
            .fetch_one(&mut **transaction)
            .await
            .map_err(crate::cognitive_store::unavailable)?;
            if mismatched_lease_rows != 0 {
                return Err(LocalCompactExecutorError::Corrupt(format!(
                    "compact journal {journal_id} mixes lease bindings for {lease_id}"
                )));
            }
        }

        let (fence, lease_binding) =
            compact_journal_descriptor(transaction, &journal_id, owner).await?;
        let executor = LocalCompactExecutor {
            store: store.clone(),
            journal_id,
            fence,
            lease_binding,
            bound_lease: None,
        };
        executor.load_journal(transaction).await?;
    }
    Ok(())
}

fn validate_fence(fence: &CompactFence) -> Result<(), LocalCompactExecutorError> {
    if fence.authority_epoch == 0 || fence.owner_epoch == 0 || fence.generation == 0 {
        return Err(LocalCompactExecutorError::Invalid(
            "compact fence epochs must be non-zero".to_string(),
        ));
    }
    validate_text(
        &fence.fencing_token,
        "fencing token",
        /*max_bytes*/ 256,
    )
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), LocalCompactExecutorError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(LocalCompactExecutorError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}
