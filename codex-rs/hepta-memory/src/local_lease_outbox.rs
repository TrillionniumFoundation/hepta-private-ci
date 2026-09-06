//! Agent-local authoritative lease/fence and append-only event/outbox seam.
//!
//! This module is deliberately bounded to `local_development_only`.  A lease
//! is an append-only history whose last row is the current fence.  Event and
//! outbox admission is one SQLite `BEGIN IMMEDIATE` transaction, so a failed
//! admission cannot leave an event without its paired local intent.  The
//! outbox is a queue/intention record only; it is never an external effect
//! receipt and no scheduler, router, KG writer, or production caller is wired
//! here.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use thiserror::Error;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::framing::frame_part;

pub const LOCAL_LEASE_OUTBOX_NAMESPACE: &str = "local_development_only";
pub const LOCAL_LEASE_OUTBOX_SCHEMA_VERSION: u32 = 1;
pub const LOCAL_LEASE_OUTBOX_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_LEASE_OUTBOX_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_LEASE_OUTBOX_PRODUCTION_CALLER: bool = false;

const MAX_LEASE_ROWS: usize = 4_096;
const MAX_EVENT_ROWS: usize = 16_384;
const MAX_OUTBOX_ROWS: usize = 16_384;
const GENESIS_LEASE_SHA256: &[u8] = b"hepta-memory:local-lease:genesis:v1";
const GENESIS_EVENT_SHA256: &[u8] = b"hepta-memory:local-event:genesis:v1";
const GENESIS_OUTBOX_SHA256: &[u8] = b"hepta-memory:local-outbox:genesis:v1";

#[derive(Debug, Error)]
pub enum LocalLeaseOutboxError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error("invalid local lease/outbox input: {0}")]
    Invalid(String),
    #[error("local lease/outbox access denied: {0}")]
    AccessDenied(String),
    #[error("local lease/outbox CAS conflict: {0}")]
    CasConflict(String),
    #[error("local lease/outbox stale fence: {0}")]
    StaleFence(String),
    #[error("local lease/outbox journal is corrupt: {0}")]
    Corrupt(String),
    #[error("local lease/outbox transition is invalid: {0}")]
    IllegalTransition(String),
    #[error("local lease/outbox transaction was rolled back: {0}")]
    TransactionAborted(String),
    #[error("local lease/outbox serialization failed: {0}")]
    Serialization(String),
    #[error("local lease/outbox clock failed: {0}")]
    Clock(String),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalAdmissionFault {
    AfterEventBeforeOutbox,
    AfterOutboxBeforeCommit,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalLeaseState {
    Active,
    Released,
    RolledBack,
}

/// Read-only classification of one Agent-local append-only lease head.
///
/// `ExpiredActive` is an observation, not permission to take over or mutate
/// the lease.  A caller must still present the exact returned head to an
/// explicit CAS/recovery API; this classifier never grants authority.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalLeaseHeadDisposition {
    Missing,
    Active,
    ExpiredActive,
    Released,
    RolledBack,
}

/// Exact read witness for a local lease head.  The full lease hash chain is
/// verified before a non-missing head is returned, so a successor can use the
/// value as an input witness without guessing a generation or token.  This
/// is a snapshot and may become stale immediately; the subsequent CAS must
/// revalidate it.  This API does not inspect or authorize logical-turn
/// takeover.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalLeaseHeadInspection {
    pub lease_id: String,
    pub head: Option<LocalLease>,
    pub disposition: LocalLeaseHeadDisposition,
}

/// Explicit authority/fence binding persisted for the E.16 lease writer.
///
/// The original H8 API intentionally accepted only generation/token.  Those
/// calls remain valid as an unbound local qualification seam, but they cannot
/// authorize the E.16 compact witness writer.  A bound lease must carry all
/// three values in SQLite and the writer rechecks them inside its transaction.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct LocalLeaseBinding {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
}

impl LocalLeaseBinding {
    pub fn new(
        authority_epoch: u64,
        owner_epoch: u64,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<Self, LocalLeaseOutboxError> {
        if authority_epoch == 0 || owner_epoch == 0 {
            return Err(LocalLeaseOutboxError::Invalid(
                "lease authority and owner epochs must be non-zero".to_string(),
            ));
        }
        if lease_expires_at_unix_seconds == 0 {
            return Err(LocalLeaseOutboxError::Invalid(
                "lease expiry must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            authority_epoch,
            owner_epoch,
            lease_expires_at_unix_seconds,
        })
    }

    /// Validate a host-owned epoch transition against the exact persisted
    /// lease head.  The legacy local qualification API intentionally keeps
    /// accepting caller-supplied bindings; only the host-bound API invokes
    /// this stricter rule.
    ///
    /// The pair `(authority_epoch, owner_epoch)` is a lexicographically
    /// monotonic CAS witness.  A higher authority epoch may deliberately
    /// reset the owner epoch (for example after a supervisor authority
    /// transfer), but an unchanged authority epoch must advance the owner
    /// epoch strictly.  This is still a local contract seam: the actual
    /// supervisor that allocates the epochs is not implemented here.
    fn validate_host_successor(
        &self,
        previous: Option<&LocalLeaseBinding>,
    ) -> Result<(), LocalLeaseOutboxError> {
        validate_lease_binding(self)?;
        if let Some(previous) = previous
            && (self.authority_epoch, self.owner_epoch)
                <= (previous.authority_epoch, previous.owner_epoch)
        {
            return Err(LocalLeaseOutboxError::CasConflict(format!(
                "host lease epoch must advance from ({}, {}) to a lexicographically newer pair",
                previous.authority_epoch, previous.owner_epoch
            )));
        }
        Ok(())
    }
}

impl LocalLeaseState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Released => "released",
            Self::RolledBack => "rolled_back",
        }
    }

    fn parse(value: &str) -> Result<Self, LocalLeaseOutboxError> {
        match value {
            "active" => Ok(Self::Active),
            "released" => Ok(Self::Released),
            "rolled_back" => Ok(Self::RolledBack),
            other => Err(corrupt(format!("unknown lease state {other:?}"))),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct LocalLease {
    pub lease_id: String,
    pub lease_sequence: u64,
    pub owner_agent_id: AgentId,
    pub generation: u64,
    pub fencing_token: String,
    pub state: LocalLeaseState,
    /// `None` denotes a legacy H8 lease.  Such a lease remains usable by the
    /// compatibility event/outbox API but is rejected by the E.16 writer.
    pub authority_epoch: Option<u64>,
    pub owner_epoch: Option<u64>,
    pub lease_expires_at_unix_seconds: Option<u64>,
    pub previous_sha256: Sha256Digest,
    pub lease_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalOutcomeState {
    Queued,
    Indeterminate,
    Committed,
    Rejected,
    RolledBack,
}

impl LocalOutcomeState {
    fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Indeterminate => "indeterminate",
            Self::Committed => "committed",
            Self::Rejected => "rejected",
            Self::RolledBack => "rolled_back",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QueuedReceipt {
    pub lease_id: String,
    pub occurrence_key: String,
    pub event_id: String,
    pub outbox_id: String,
    pub owner_agent_id: AgentId,
    pub generation: u64,
    pub fencing_token: String,
    pub payload_sha256: Sha256Digest,
    /// Always false: a queued local intent is not an external effect receipt.
    pub external_effect: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalAdmission {
    Queued(QueuedReceipt),
    Replay(QueuedReceipt),
}

/// Status-aware result when an owning runtime reopens an active occurrence.
///
/// `Queued` preserves the one existing local intent for normal idempotent
/// replay.  Every other outcome is quarantined or terminal, so recovery
/// verifies the complete lease/event/outbox chains and appends a release in
/// the same `BEGIN IMMEDIATE` transaction.  Neither branch dispatches the
/// outbox or claims an external effect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LocalReplayFinalization {
    /// The lease was replayed after acquisition, but no local event/outbox
    /// admission had committed yet.  The caller may safely continue the
    /// original admission under this still-active fence.
    NotAdmitted,
    Queued(QueuedReceipt),
    Released {
        outcome: LocalOutcomeState,
        lease: LocalLease,
        external_effect: bool,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalOutcomeReceipt {
    pub lease_id: String,
    pub occurrence_key: String,
    pub state: LocalOutcomeState,
    pub event_id: String,
    /// Always false: outcome reconciliation remains local bookkeeping.
    pub external_effect: bool,
}

#[derive(Clone, Debug)]
pub enum LocalLeaseAcquire {
    Acquired(LocalLeaseOutbox),
    Replay(LocalLeaseOutbox),
}

impl LocalLeaseAcquire {
    /// Consume either a fresh acquisition or an exact active replay and
    /// return the same host-bound lease capability.
    ///
    /// Callers still have to verify the binding/current head before every
    /// mutation.  Collapsing the acquisition disposition here grants no new
    /// authority; it only avoids downstream crates having to destructure
    /// variants whose payload fields are intentionally private.
    pub fn into_handle(self) -> LocalLeaseOutbox {
        match self {
            Self::Acquired(lease) | Self::Replay(lease) => lease,
        }
    }
}

#[derive(Clone)]
pub struct LocalLeaseOutbox {
    store: CognitiveStore,
    lease_id: String,
    owner_agent_id: AgentId,
    generation: u64,
    fencing_token: String,
    authority_epoch: Option<u64>,
    owner_epoch: Option<u64>,
    lease_expires_at_unix_seconds: Option<u64>,
}

impl std::fmt::Debug for LocalLeaseOutbox {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("LocalLeaseOutbox")
            .field("lease_id", &self.lease_id)
            .field("owner_agent_id", &self.owner_agent_id)
            .field("generation", &self.generation)
            .field("authority_epoch", &self.authority_epoch)
            .field("owner_epoch", &self.owner_epoch)
            .field(
                "lease_expires_at_unix_seconds",
                &self.lease_expires_at_unix_seconds,
            )
            .field("fencing_token", &"<redacted>")
            .finish()
    }
}

impl LocalLeaseOutbox {
    /// Acquire generation one, or replay an exact active acquisition.
    pub(crate) async fn acquire(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_with_binding(store, lease_id, generation, fencing_token, None, false).await
    }

    /// Acquire or replay a lease with an explicit authority/owner epoch and
    /// expiry binding.  This is the only acquisition path accepted by the
    /// schema-bound compact witness writer.
    pub(crate) async fn acquire_bound(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        binding: LocalLeaseBinding,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_with_binding(
            store,
            lease_id,
            generation,
            fencing_token,
            Some(binding),
            false,
        )
        .await
    }

    /// Acquire or replay a lease using the strict host-bound epoch contract.
    ///
    /// This remains a local qualification seam.  It persists and verifies a
    /// caller-provided binding, but it does not claim to be a supervisor or
    /// production authority source.
    pub(crate) async fn acquire_host_bound(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        binding: LocalLeaseBinding,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_with_binding(
            store,
            lease_id,
            generation,
            fencing_token,
            Some(binding),
            true,
        )
        .await
    }

    async fn acquire_with_binding(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        generation: u64,
        fencing_token: impl Into<String>,
        binding: Option<LocalLeaseBinding>,
        enforce_host_epoch_cas: bool,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let lease_id = lease_id.into();
        let fencing_token = fencing_token.into();
        validate_text(&lease_id, "lease id", 512)?;
        validate_generation(generation)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        if let Some(binding) = binding.as_ref() {
            validate_lease_binding(binding)?;
            if enforce_host_epoch_cas {
                binding.validate_host_successor(None)?;
            }
        } else if enforce_host_epoch_cas {
            return Err(LocalLeaseOutboxError::Invalid(
                "host-bound lease requires an explicit authority/owner/expiry binding".to_string(),
            ));
        }
        let mut transaction = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &lease_id, store.owner_agent_id()).await?;
        let (state, replay) = match latest {
            None => {
                if generation != 1 {
                    return Err(LocalLeaseOutboxError::CasConflict(
                        "first lease generation must be 1".to_string(),
                    ));
                }
                let lease = append_lease(
                    &mut transaction,
                    &lease_id,
                    store.owner_agent_id(),
                    generation,
                    &fencing_token,
                    LocalLeaseState::Active,
                    None,
                    binding.as_ref(),
                )
                .await?;
                (lease, false)
            }
            Some(previous) => {
                if previous.state == LocalLeaseState::Active
                    && previous.owner_agent_id == *store.owner_agent_id()
                    && previous.generation == generation
                    && previous.fencing_token == fencing_token
                    && previous.authority_epoch
                        == binding.as_ref().map(|value| value.authority_epoch)
                    && previous.owner_epoch == binding.as_ref().map(|value| value.owner_epoch)
                    && previous.lease_expires_at_unix_seconds
                        == binding
                            .as_ref()
                            .map(|value| value.lease_expires_at_unix_seconds)
                {
                    // Replaying an active acquisition is a reopen boundary:
                    // do not hand a caller a writable handle until the
                    // historical event and outbox journals have both been
                    // verified under this same write transaction.  Otherwise
                    // a damaged child chain can be hidden behind a successful
                    // `Replay` result until a later operation (or, worse,
                    // mistaken as a fresh writer by a host).
                    let events =
                        verify_event_chain(&mut transaction, &lease_id, store.owner_agent_id())
                            .await?;
                    let outbox =
                        verify_outbox_chain(&mut transaction, &lease_id, store.owner_agent_id())
                            .await?;
                    verify_event_outbox_pairing(&events, &outbox)?;
                    (previous, true)
                } else {
                    if generation <= previous.generation {
                        return Err(LocalLeaseOutboxError::StaleFence(format!(
                            "requested generation {} is not newer than {}",
                            generation, previous.generation
                        )));
                    }
                    if generation != previous.generation + 1 {
                        return Err(LocalLeaseOutboxError::CasConflict(format!(
                            "generation must advance from {} to {}",
                            previous.generation,
                            previous.generation + 1
                        )));
                    }
                    if previous.state == LocalLeaseState::Active {
                        return Err(LocalLeaseOutboxError::CasConflict(
                            "cannot advance an active lease before release or rollback".to_string(),
                        ));
                    }
                    if fencing_token_seen(&mut transaction, &lease_id, &fencing_token).await? {
                        return Err(LocalLeaseOutboxError::CasConflict(
                            "fencing token was already used by this lease".to_string(),
                        ));
                    }
                    if enforce_host_epoch_cas {
                        let binding = binding.as_ref().ok_or_else(|| {
                            LocalLeaseOutboxError::Invalid(
                                "host-bound lease requires an explicit authority/owner/expiry binding"
                                    .to_string(),
                            )
                        })?;
                        let previous_binding = prior_binding(&previous).ok_or_else(|| {
                            LocalLeaseOutboxError::CasConflict(
                                "host-bound lease cannot advance from an unbound head".to_string(),
                            )
                        })?;
                        binding.validate_host_successor(Some(&previous_binding))?;
                    }
                    // A successor generation carries the same append-only
                    // child journals under this lease id.  Validate them
                    // before appending a new head so takeover cannot bury a
                    // corrupt historical event/outbox chain.
                    let events =
                        verify_event_chain(&mut transaction, &lease_id, store.owner_agent_id())
                            .await?;
                    let outbox =
                        verify_outbox_chain(&mut transaction, &lease_id, store.owner_agent_id())
                            .await?;
                    verify_event_outbox_pairing(&events, &outbox)?;
                    let lease = append_lease(
                        &mut transaction,
                        &lease_id,
                        store.owner_agent_id(),
                        generation,
                        &fencing_token,
                        LocalLeaseState::Active,
                        Some(&previous),
                        binding.as_ref(),
                    )
                    .await?;
                    (lease, false)
                }
            }
        };
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let handle = Self::from_lease(store, &state)?;
        Ok(if replay {
            LocalLeaseAcquire::Replay(handle)
        } else {
            LocalLeaseAcquire::Acquired(handle)
        })
    }

    /// Compatibility shim for the pre-head-CAS API.
    ///
    /// A generation number cannot distinguish an active head from a later
    /// release/rollback row with the same generation.  Advancing through this
    /// API is therefore permanently fail-closed; callers must provide the
    /// exact append-only witness through [`Self::acquire_after_head`].  The
    /// method remains so older callers fail safely at runtime instead of
    /// silently bypassing the head CAS.
    pub(crate) async fn acquire_after(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        expected_generation: u64,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        validate_generation(expected_generation)?;
        validate_generation(generation)?;
        if generation
            != expected_generation.checked_add(1).ok_or_else(|| {
                LocalLeaseOutboxError::Invalid(
                    "expected lease generation overflows next generation".to_string(),
                )
            })?
        {
            return Err(LocalLeaseOutboxError::CasConflict(
                "new lease generation must be expected generation + 1".to_string(),
            ));
        }
        let lease_id = lease_id.into();
        let fencing_token = fencing_token.into();
        validate_text(&lease_id, "lease id", 512)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        let _ = store;
        Err(LocalLeaseOutboxError::CasConflict(
            "exact lease head required; use acquire_local_lease_after_head".to_string(),
        ))
    }

    /// Acquire a next generation using the exact append-only lease head as a
    /// compare-and-swap witness.
    ///
    /// A generation number alone cannot distinguish an active head from a
    /// later release/rollback row with the same generation.  The witness
    /// therefore binds the lease id, owner, sequence, state, generation,
    /// fencing token, previous digest, and head digest.  Any intervening
    /// terminal transition fails closed before a new row is appended.
    pub(crate) async fn acquire_after_head(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_after_head_with_binding(
            store,
            lease_id,
            expected_head,
            generation,
            fencing_token,
            None,
            false,
        )
        .await
    }

    pub(crate) async fn acquire_after_head_bound(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        binding: LocalLeaseBinding,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_after_head_with_binding(
            store,
            lease_id,
            expected_head,
            generation,
            fencing_token,
            Some(binding),
            false,
        )
        .await
    }

    /// Acquire the next generation after an exact head CAS under the strict
    /// host-bound authority/owner epoch contract.  The expected head is the
    /// durable local witness; an intervening terminal transition or a stale
    /// epoch fails closed inside the same SQLite write transaction.
    pub(crate) async fn acquire_after_head_host_bound(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        binding: LocalLeaseBinding,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        Self::acquire_after_head_with_binding(
            store,
            lease_id,
            expected_head,
            generation,
            fencing_token,
            Some(binding),
            true,
        )
        .await
    }

    async fn acquire_after_head_with_binding(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        generation: u64,
        fencing_token: impl Into<String>,
        binding: Option<LocalLeaseBinding>,
        enforce_host_epoch_cas: bool,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let lease_id = lease_id.into();
        let fencing_token = fencing_token.into();
        validate_text(&lease_id, "lease id", 512)?;
        validate_generation(generation)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        if let Some(binding) = binding.as_ref() {
            validate_lease_binding(binding)?;
            if enforce_host_epoch_cas {
                binding.validate_host_successor(None)?;
            }
        } else if enforce_host_epoch_cas {
            return Err(LocalLeaseOutboxError::Invalid(
                "host-bound lease requires an explicit authority/owner/expiry binding".to_string(),
            ));
        }
        validate_generation(expected_head.generation)?;
        if expected_head.lease_id != lease_id {
            return Err(LocalLeaseOutboxError::CasConflict(
                "expected lease head belongs to a different lease".to_string(),
            ));
        }
        if expected_head.owner_agent_id != *store.owner_agent_id() {
            return Err(LocalLeaseOutboxError::AccessDenied(
                "expected lease head owner does not match the Agent-local store".to_string(),
            ));
        }
        if expected_head.state == LocalLeaseState::Active {
            return Err(LocalLeaseOutboxError::CasConflict(
                "expected lease head must be terminal before generation advance".to_string(),
            ));
        }
        if generation != expected_head.generation.saturating_add(1) {
            return Err(LocalLeaseOutboxError::CasConflict(
                "new lease generation must be expected head generation + 1".to_string(),
            ));
        }

        let mut transaction = store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &lease_id, store.owner_agent_id()).await?;
        let Some(previous) = latest else {
            return Err(LocalLeaseOutboxError::CasConflict(
                "cannot advance a missing lease".to_string(),
            ));
        };
        if previous.lease_sequence != expected_head.lease_sequence
            || previous.owner_agent_id != expected_head.owner_agent_id
            || previous.generation != expected_head.generation
            || previous.fencing_token != expected_head.fencing_token
            || previous.state != expected_head.state
            || previous.previous_sha256 != expected_head.previous_sha256
            || previous.lease_sha256 != expected_head.lease_sha256
        {
            return Err(LocalLeaseOutboxError::CasConflict(
                "expected lease head no longer matches the current append-only head".to_string(),
            ));
        }
        if fencing_token_seen(&mut transaction, &lease_id, &fencing_token).await? {
            return Err(LocalLeaseOutboxError::CasConflict(
                "fencing token was already used by this lease".to_string(),
            ));
        }
        if enforce_host_epoch_cas {
            let binding = binding.as_ref().ok_or_else(|| {
                LocalLeaseOutboxError::Invalid(
                    "host-bound lease requires an explicit authority/owner/expiry binding"
                        .to_string(),
                )
            })?;
            let previous_binding = prior_binding(&previous).ok_or_else(|| {
                LocalLeaseOutboxError::CasConflict(
                    "host-bound lease cannot advance from an unbound head".to_string(),
                )
            })?;
            binding.validate_host_successor(Some(&previous_binding))?;
        }
        let lease = append_lease(
            &mut transaction,
            &lease_id,
            store.owner_agent_id(),
            generation,
            &fencing_token,
            LocalLeaseState::Active,
            Some(&previous),
            binding.as_ref(),
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalLeaseAcquire::Acquired(Self::from_lease(
            store, &lease,
        )?))
    }

    fn from_lease(
        store: &CognitiveStore,
        lease: &LocalLease,
    ) -> Result<Self, LocalLeaseOutboxError> {
        if lease.state != LocalLeaseState::Active {
            return Err(LocalLeaseOutboxError::StaleFence(
                "cannot open a released local lease".to_string(),
            ));
        }
        if lease.owner_agent_id != *store.owner_agent_id() {
            return Err(LocalLeaseOutboxError::AccessDenied(
                "local lease owner does not match the Agent-local store".to_string(),
            ));
        }
        Ok(Self {
            store: store.clone(),
            lease_id: lease.lease_id.clone(),
            owner_agent_id: lease.owner_agent_id.clone(),
            generation: lease.generation,
            fencing_token: lease.fencing_token.clone(),
            authority_epoch: lease.authority_epoch,
            owner_epoch: lease.owner_epoch,
            lease_expires_at_unix_seconds: lease.lease_expires_at_unix_seconds,
        })
    }

    pub fn lease_id(&self) -> &str {
        &self.lease_id
    }

    pub fn owner_agent_id(&self) -> &AgentId {
        &self.owner_agent_id
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn fencing_token(&self) -> &str {
        &self.fencing_token
    }

    /// Returns the explicit schema binding, if this handle was acquired via
    /// `acquire_local_lease_bound`.  Legacy H8 handles return `None` and are
    /// intentionally ineligible for the E.16 compact witness writer.
    pub fn binding(&self) -> Option<LocalLeaseBinding> {
        match (
            self.authority_epoch,
            self.owner_epoch,
            self.lease_expires_at_unix_seconds,
        ) {
            (Some(authority_epoch), Some(owner_epoch), Some(lease_expires_at_unix_seconds)) => {
                Some(LocalLeaseBinding {
                    authority_epoch,
                    owner_epoch,
                    lease_expires_at_unix_seconds,
                })
            }
            _ => None,
        }
    }

    pub fn is_explicitly_bound(&self) -> bool {
        self.binding().is_some()
    }

    /// Read the fully verified append-only head that this handle names.
    ///
    /// Hosts use this witness when handing a lease across a restart or into a
    /// successor CAS.  Reading it grants no authority and does not bypass the
    /// strict `reopen_bound` checks.
    pub async fn head_witness(&self) -> Result<LocalLease, LocalLeaseOutboxError> {
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let latest = latest.ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("local lease head does not exist".to_string())
        })?;
        // A stale process must not turn this read helper into a way to discover
        // and re-use a newer generation.  The host can ask a fresh store
        // handle for that head explicitly; this handle only witnesses its own
        // generation/fence tuple.
        ensure_current_handle_fields(&latest, self)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(latest)
    }

    /// Return whether this handle was opened against the exact Agent-local
    /// store supplied by the host.  Owner identity and database path are both
    /// part of the comparison; matching only the agent id would allow a
    /// handle from a different temporary/store root to cross the host seam.
    /// This is an identity check only and grants no additional authority.
    pub fn is_bound_to_store(&self, store: &CognitiveStore) -> bool {
        self.store.is_same_local_store(store)
    }

    /// Re-verify the active lease and both append-only journal chains before
    /// a caller performs a terminal transition.  In particular, callers
    /// must not use `release` as a way to hide a corrupt event/outbox chain.
    pub async fn verify_current(&self) -> Result<(), LocalLeaseOutboxError> {
        // Keep the deadline check on the verification path.  `reopen` is
        // intentionally permissive about an expired active head so a host
        // that restarted after the deadline can recover a bound handle and
        // explicitly call `expire_lease`; a read/observer must not use that
        // recovery seam as proof that the lease is still current.
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        self.verify_current_in_transaction(&mut transaction).await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(())
    }

    /// Verify the active lease and both append-only local chains inside a
    /// caller-owned transaction.  Composite local writers use this helper to
    /// hold the SQLite write lock while coupling another journal mutation to
    /// this exact lease fence; it intentionally performs no write.
    pub(crate) async fn verify_current_in_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        let lease = self.current_lease(transaction).await?;
        ensure_current_active(&lease, self)?;
        let events = verify_event_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox = verify_outbox_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        Ok(lease)
    }

    /// Verify the exact active lease identity and local journal chains for a
    /// read-only crash-recovery observation, while deliberately allowing a
    /// bound lease whose deadline has elapsed.  This is not a write
    /// capability: callers must still use an explicit terminal timeout CAS
    /// (`expire_lease`) before any post-TTL lifecycle decision.
    pub(crate) async fn verify_current_for_recovery_in_transaction(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        let lease = self.current_lease(transaction).await?;
        ensure_current_identity(&lease, self)?;
        let events = verify_event_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox = verify_outbox_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        Ok(lease)
    }

    pub(crate) fn store(&self) -> &CognitiveStore {
        &self.store
    }

    /// Reopens an already acquired active lease and verifies every journal
    /// chain before returning a writable handle.
    pub(crate) async fn reopen(
        store: &CognitiveStore,
        lease_id: impl Into<String>,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<Self, LocalLeaseOutboxError> {
        let lease_id = lease_id.into();
        let fencing_token = fencing_token.into();
        validate_text(&lease_id, "lease id", 512)?;
        validate_generation(generation)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        let mut transaction = store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &lease_id, store.owner_agent_id()).await?;
        let Some(lease) = latest else {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease does not exist".to_string(),
            ));
        };
        if lease.state != LocalLeaseState::Active
            || lease.owner_agent_id != *store.owner_agent_id()
            || lease.generation != generation
            || lease.fencing_token != fencing_token
        {
            return Err(LocalLeaseOutboxError::StaleFence(
                "reopened local lease fence is no longer current".to_string(),
            ));
        }
        let events =
            verify_event_chain(&mut transaction, &lease_id, store.owner_agent_id()).await?;
        let outbox =
            verify_outbox_chain(&mut transaction, &lease_id, store.owner_agent_id()).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Self::from_lease(store, &lease)
    }

    /// Reopen an exact active head under the strict host-bound contract.
    ///
    /// Unlike the compatibility `reopen` API, this method requires the full
    /// append-only head witness and an explicit binding.  Every identity and
    /// digest field is compared inside the read transaction before a writable
    /// handle is returned.  Expiry is intentionally not checked here: a host
    /// may reopen an expired head only to make the explicit timeout decision
    /// through `expire_lease`; ordinary writes still fail closed.
    pub(crate) async fn reopen_bound(
        store: &CognitiveStore,
        expected_head: LocalLease,
        binding: LocalLeaseBinding,
    ) -> Result<Self, LocalLeaseOutboxError> {
        validate_generation(expected_head.generation)?;
        validate_lease_binding(&binding)?;
        if expected_head.state != LocalLeaseState::Active {
            return Err(LocalLeaseOutboxError::StaleFence(
                "host-bound reopen requires an active lease head".to_string(),
            ));
        }
        if expected_head.owner_agent_id != *store.owner_agent_id() {
            return Err(LocalLeaseOutboxError::AccessDenied(
                "expected host-bound lease head owner does not match the Agent-local store"
                    .to_string(),
            ));
        }
        if prior_binding(&expected_head).as_ref() != Some(&binding) {
            return Err(LocalLeaseOutboxError::StaleFence(
                "expected host-bound lease head binding does not match the supplied binding"
                    .to_string(),
            ));
        }

        let mut transaction = store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) = load_lease_chain(
            &mut transaction,
            &expected_head.lease_id,
            store.owner_agent_id(),
        )
        .await?;
        let Some(lease) = latest else {
            return Err(LocalLeaseOutboxError::StaleFence(
                "host-bound local lease does not exist".to_string(),
            ));
        };
        if lease != expected_head {
            return Err(LocalLeaseOutboxError::StaleFence(
                "expected host-bound lease head no longer matches the append-only head".to_string(),
            ));
        }
        let events = verify_event_chain(
            &mut transaction,
            &expected_head.lease_id,
            store.owner_agent_id(),
        )
        .await?;
        let outbox = verify_outbox_chain(
            &mut transaction,
            &expected_head.lease_id,
            store.owner_agent_id(),
        )
        .await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Self::from_lease(store, &lease)
    }

    pub async fn release(&self) -> Result<LocalLease, LocalLeaseOutboxError> {
        self.transition_lease(LocalLeaseState::Released).await
    }

    pub async fn rollback_lease(&self) -> Result<LocalLease, LocalLeaseOutboxError> {
        self.transition_lease(LocalLeaseState::RolledBack).await
    }

    /// Terminalize an explicitly bound lease after its deadline has passed.
    ///
    /// Expiry is deliberately a separate operation from `release` and
    /// `rollback_lease`: those operations are host decisions that must happen
    /// before the fence deadline, while this operation is the host's explicit
    /// timeout decision after the deadline.  The append-only schema predates a
    /// distinct `expired` state, so the existing `rolled_back` terminal state
    /// is used for this timeout transition.  The API name and the persisted
    /// binding make the reason auditable without weakening the journal check.
    ///
    /// This method is bound-only.  Legacy H8 leases have no authority epoch,
    /// owner epoch, or expiry and therefore cannot be expired by inference.
    /// Because the compatibility schema has one `rolled_back` terminal state,
    /// a matching bound rollback that was already recorded before the deadline
    /// is also returned as an idempotent terminal result once that deadline is
    /// reached; no second reason marker is invented in SQLite.
    /// All lease, event, and outbox checks happen under the same
    /// `BEGIN IMMEDIATE` transaction as the terminal append.  No takeover,
    /// renewal, reconciliation, scheduler, or external effect is performed.
    pub async fn expire_lease(&self) -> Result<LocalLease, LocalLeaseOutboxError> {
        self.expire_lease_inner(None).await
    }

    #[cfg(test)]
    pub(crate) async fn expire_lease_at_unix_seconds(
        &self,
        now: u64,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        self.expire_lease_inner(Some(now)).await
    }

    async fn expire_lease_inner(
        &self,
        now_override: Option<u64>,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        let handle_binding = self.binding().ok_or_else(|| {
            LocalLeaseOutboxError::Invalid(
                "explicit authority/owner/expiry binding is required to expire a local lease"
                    .to_string(),
            )
        })?;
        validate_lease_binding(&handle_binding)?;

        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let Some(previous) = latest else {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease disappeared".to_string(),
            ));
        };

        // `ensure_current_active` intentionally rejects an expired lease.  An
        // expiry transition needs the same identity/fence checks without that
        // final deadline check, so perform the identity check first and apply
        // the monotonic deadline condition below.  A matching rolled-back
        // head is accepted as an idempotent retry of a timeout that committed
        // before the host observed its result; no second terminal row is
        // appended.
        ensure_current_handle_fields(&previous, self)?;
        let persisted_binding = prior_binding(&previous).ok_or_else(|| {
            LocalLeaseOutboxError::Invalid(
                "explicit authority/owner/expiry binding is required to expire a local lease"
                    .to_string(),
            )
        })?;
        if persisted_binding != handle_binding {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease authority/owner/expiry binding changed".to_string(),
            ));
        }

        // Validate both append-only child journals before closing the lease;
        // expiry must not become a way to hide a damaged event or outbox
        // chain.  These reads remain inside the write transaction, so the
        // checked head is the one immediately preceding the terminal row.
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        self.verify_bound_compact_journals(&mut transaction).await?;

        let now = match now_override {
            Some(now) => now,
            None => u64::try_from(now_unix_seconds()?)
                .map_err(|_| LocalLeaseOutboxError::Clock("clock before Unix epoch".to_string()))?,
        };
        if now < persisted_binding.lease_expires_at_unix_seconds {
            return Err(LocalLeaseOutboxError::StaleFence(format!(
                "local lease has not expired (deadline {})",
                persisted_binding.lease_expires_at_unix_seconds
            )));
        }

        if previous.state == LocalLeaseState::RolledBack {
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(previous);
        }
        if previous.state != LocalLeaseState::Active {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease is no longer active".to_string(),
            ));
        }

        let lease = append_lease(
            &mut transaction,
            &self.lease_id,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            LocalLeaseState::RolledBack,
            Some(&previous),
            Some(&persisted_binding),
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(lease)
    }

    async fn transition_lease(
        &self,
        state: LocalLeaseState,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (latest, _) =
            load_lease_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let Some(previous) = latest else {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease disappeared".to_string(),
            ));
        };
        ensure_current_active(&previous, self)?;
        // A terminal transition must never be usable as a way to hide a
        // damaged child journal. Keep both chain checks inside this same
        // write transaction, immediately before appending the terminal
        // lease row, so a concurrent writer cannot change the checked heads
        // between validation and commit.
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox)?;
        // A host terminal decision must not strand a queued or indeterminate
        // outbox intent behind a terminal lease fence.  Once the lease is
        // closed, the exact generation/token can no longer append the
        // reconcile marker needed to distinguish a committed target write
        // from a rejected/rolled-back one.  Keep this check in the same
        // BEGIN IMMEDIATE transaction as the terminal append so a concurrent
        // outcome writer cannot race the decision.
        ensure_no_unresolved_outcomes(&events, self.generation, &self.fencing_token)?;
        self.verify_bound_compact_journals(&mut transaction).await?;
        let binding = self.binding();
        let lease = append_lease(
            &mut transaction,
            &self.lease_id,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            state,
            Some(&previous),
            binding.as_ref(),
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(lease)
    }

    /// Atomically admit one local event and its paired local outbox intent.
    pub async fn admit(
        &self,
        occurrence_key: impl Into<String>,
        topic: impl Into<String>,
        payload_json: impl Into<String>,
    ) -> Result<LocalAdmission, LocalLeaseOutboxError> {
        self.admit_inner(
            occurrence_key.into(),
            topic.into(),
            payload_json.into(),
            None,
        )
        .await
    }

    /// Test/qualification fault hook proving that event+outbox are one
    /// transaction.  It is local-only and intentionally cannot dispatch.
    pub async fn admit_with_fault(
        &self,
        occurrence_key: impl Into<String>,
        topic: impl Into<String>,
        payload_json: impl Into<String>,
        fault: LocalAdmissionFault,
    ) -> Result<LocalAdmission, LocalLeaseOutboxError> {
        self.admit_inner(
            occurrence_key.into(),
            topic.into(),
            payload_json.into(),
            Some(fault),
        )
        .await
    }

    async fn admit_inner(
        &self,
        occurrence_key: String,
        topic: String,
        payload_json: String,
        fault: Option<LocalAdmissionFault>,
    ) -> Result<LocalAdmission, LocalLeaseOutboxError> {
        validate_text(&occurrence_key, "occurrence key", 512)?;
        validate_text(&topic, "outbox topic", 256)?;
        validate_text(&payload_json, "event payload", 65_536)?;
        let payload_sha256 = Sha256Digest::for_bytes(payload_json.as_bytes());
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;

        if let Some(existing) = find_admission(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        {
            let outbox = find_outbox(
                &mut transaction,
                &self.lease_id,
                &occurrence_key,
                &self.owner_agent_id,
            )
            .await?
            .ok_or_else(|| corrupt("event admission has no paired outbox row"))?;
            if existing.payload_sha256 != payload_sha256
                || outbox.topic != topic
                || outbox.payload_sha256 != payload_sha256
            {
                return Err(LocalLeaseOutboxError::CasConflict(
                    "occurrence replay changed its payload or topic".to_string(),
                ));
            }
            // An occurrence is fenced to the generation that admitted it.
            // A newer generation must never turn a historical admission into
            // a queued replay: doing so would permit a stale occurrence to be
            // dispatched again and used to look like journal corruption when
            // `queued_receipt` compared the old fence with the new handle.
            if existing.generation != self.generation
                || existing.fencing_token != self.fencing_token
                || outbox.generation != self.generation
                || outbox.fencing_token != self.fencing_token
            {
                return Err(LocalLeaseOutboxError::StaleFence(format!(
                    "occurrence was admitted under generation {} and cannot be retried by generation {}",
                    existing.generation, self.generation
                )));
            }
            let outcome = current_outcome(
                &mut transaction,
                &self.lease_id,
                &occurrence_key,
                &self.owner_agent_id,
            )
            .await?;
            if outcome != LocalOutcomeState::Queued {
                // Indeterminate is intentionally fail-closed as well as the
                // terminal states.  The caller must reconcile (or explicitly
                // roll back) before this occurrence can leave quarantine;
                // `admit` must never hand back a dispatchable queued receipt.
                return Err(LocalLeaseOutboxError::IllegalTransition(format!(
                    "occurrence is already in {} state; admission cannot replay",
                    outcome.as_str()
                )));
            }
            let receipt = queued_receipt(self, &existing, &outbox)?;
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LocalAdmission::Replay(receipt));
        }

        let event_sequence = next_event_sequence(&mut transaction, &self.lease_id).await?;
        let event_previous = event_head(&mut transaction, &self.lease_id).await?;
        let event_id = journal_row_id("event", &self.lease_id, event_sequence);
        let event_sha256 = event_digest(
            &self.lease_id,
            event_sequence,
            &event_id,
            &occurrence_key,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            "admitted",
            &payload_sha256,
            &event_previous,
        );
        insert_event(
            &mut transaction,
            EventInsert {
                lease_id: &self.lease_id,
                sequence: event_sequence,
                event_id: &event_id,
                occurrence_key: &occurrence_key,
                owner: &self.owner_agent_id,
                generation: self.generation,
                fencing_token: &self.fencing_token,
                kind: "admitted",
                payload_json: &payload_json,
                payload_sha256: &payload_sha256,
                previous_sha256: &event_previous,
                event_sha256: &event_sha256,
            },
        )
        .await?;
        if fault == Some(LocalAdmissionFault::AfterEventBeforeOutbox) {
            return Err(LocalLeaseOutboxError::TransactionAborted(
                "fault injected after event before outbox".to_string(),
            ));
        }

        let outbox_sequence = next_outbox_sequence(&mut transaction, &self.lease_id).await?;
        let outbox_previous = outbox_head(&mut transaction, &self.lease_id).await?;
        let outbox_id = journal_row_id("outbox", &self.lease_id, outbox_sequence);
        let outbox_sha256 = outbox_digest(
            &self.lease_id,
            outbox_sequence,
            &outbox_id,
            &event_id,
            &occurrence_key,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            &topic,
            &payload_sha256,
            &outbox_previous,
        );
        insert_outbox(
            &mut transaction,
            OutboxInsert {
                lease_id: &self.lease_id,
                sequence: outbox_sequence,
                outbox_id: &outbox_id,
                event_id: &event_id,
                occurrence_key: &occurrence_key,
                owner: &self.owner_agent_id,
                generation: self.generation,
                fencing_token: &self.fencing_token,
                topic: &topic,
                payload_json: &payload_json,
                payload_sha256: &payload_sha256,
                previous_sha256: &outbox_previous,
                outbox_sha256: &outbox_sha256,
            },
        )
        .await?;
        if fault == Some(LocalAdmissionFault::AfterOutboxBeforeCommit) {
            return Err(LocalLeaseOutboxError::TransactionAborted(
                "fault injected after outbox before commit".to_string(),
            ));
        }
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalAdmission::Queued(QueuedReceipt {
            lease_id: self.lease_id.clone(),
            occurrence_key,
            event_id,
            outbox_id,
            owner_agent_id: self.owner_agent_id.clone(),
            generation: self.generation,
            fencing_token: self.fencing_token.clone(),
            payload_sha256,
            external_effect: false,
        }))
    }

    /// Mark a local intent indeterminate after an unknown local outcome.
    /// Unknown never becomes committed implicitly.
    pub async fn mark_indeterminate(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.append_outcome(
            occurrence_key.into(),
            "indeterminate",
            reason.into(),
            &[LocalOutcomeState::Queued, LocalOutcomeState::Indeterminate],
            LocalOutcomeState::Indeterminate,
        )
        .await
    }

    /// Claim one exact queued occurrence before a target dispatch begins.
    ///
    /// The claim is persisted as the existing fail-closed `Indeterminate`
    /// state.  Unlike [`mark_indeterminate`], an identical replay is rejected:
    /// only the transaction that changes `Queued` to `Indeterminate` may call
    /// the target.  A concurrent dispatcher or a process that reopens after a
    /// crash must use status/reconcile instead of dispatching the outbox row a
    /// second time.  This is local bookkeeping only; it neither calls a target
    /// nor proves an external effect.
    pub(crate) async fn claim_dispatch(
        &self,
        occurrence_key: impl Into<String>,
        grant_digest: &Sha256Digest,
        operation_digest: &Sha256Digest,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        let occurrence_key = occurrence_key.into();
        self.verify_dispatch_operation_binding(&occurrence_key, grant_digest, operation_digest)
            .await?;
        self.append_outcome_with_replay_policy(
            occurrence_key,
            "indeterminate",
            format!("dispatch_started_pending_ack:{}", operation_digest.as_str()),
            &[LocalOutcomeState::Queued],
            LocalOutcomeState::Indeterminate,
            false,
        )
        .await
    }

    /// Verify that a dispatch claim digest is canonical and derives from the
    /// exact immutable admission/outbox pair.  This read transaction is
    /// followed by the claim's fenced `BEGIN IMMEDIATE` append; the append
    /// rechecks the current lease and occurrence fence, so a transition or
    /// successor generation between the two steps fails closed.
    async fn verify_dispatch_operation_binding(
        &self,
        occurrence_key: &str,
        grant_digest: &Sha256Digest,
        operation_digest: &Sha256Digest,
    ) -> Result<(), LocalLeaseOutboxError> {
        Sha256Digest::parse(grant_digest.as_str())
            .map_err(LocalLeaseOutboxError::Invalid)
            .map(|_| ())?;
        Sha256Digest::parse(operation_digest.as_str())
            .map_err(LocalLeaseOutboxError::Invalid)
            .map(|_| ())?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let admission = find_admission(
            &mut transaction,
            &self.lease_id,
            occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("dispatch claim admission is missing".to_string())
        })?;
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("dispatch claim outbox is missing".to_string())
        })?;
        ensure_current_occurrence_fence(self, &admission, &outbox)?;
        let expected = dispatch_operation_digest(
            grant_digest,
            &self.lease_id,
            occurrence_key,
            &outbox.topic,
            &outbox.payload_sha256,
        );
        if expected != *operation_digest {
            return Err(LocalLeaseOutboxError::StaleFence(
                "dispatch claim operation digest is not bound to the immutable outbox".to_string(),
            ));
        }
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(())
    }

    /// Apply a local intent after its target-side qualification writer has
    /// returned a receipt.  `Queued` is the durable Pending state and
    /// `Committed` is exposed by higher-level local sagas as Applied.  The
    /// transition is still append-only metadata: it never dispatches the
    /// outbox or claims an external effect.
    pub async fn apply(
        &self,
        occurrence_key: impl Into<String>,
        receipt: impl Into<String>,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.append_outcome(
            occurrence_key.into(),
            "reconcile_committed",
            receipt.into(),
            &[LocalOutcomeState::Queued, LocalOutcomeState::Indeterminate],
            LocalOutcomeState::Committed,
        )
        .await
    }

    /// Reject a local intent after its target-side qualification writer has
    /// failed validation or CAS.  This is the explicit Rejected terminal
    /// state used by the local MemoryAdmission/compact sagas.
    pub async fn reject(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.append_outcome(
            occurrence_key.into(),
            "reconcile_rejected",
            reason.into(),
            &[LocalOutcomeState::Queued, LocalOutcomeState::Indeterminate],
            LocalOutcomeState::Rejected,
        )
        .await
    }

    /// Revoke a still-pending local intent.  This is the local append-only
    /// equivalent of a revoked outbox command; it never deletes the original
    /// event/outbox row and never claims that a target-side effect was undone.
    pub async fn revoke(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.rollback_occurrence(occurrence_key, reason).await
    }

    /// Inspect an occurrence without changing its lease or outcome.  Unlike
    /// [`status`], a missing admission is represented as `None`, which lets a
    /// local saga distinguish its first attempt from an idempotent replay
    /// without parsing an error string or releasing the lease.
    pub async fn inspect_occurrence(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<Option<LocalOutcomeState>, LocalLeaseOutboxError> {
        let occurrence_key = occurrence_key.into();
        validate_text(&occurrence_key, "occurrence key", 512)?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let Some(admission) = find_admission(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        else {
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(None);
        };
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("event admission has no paired outbox row"))?;
        ensure_current_occurrence_fence(self, &admission, &outbox)?;
        let state = current_outcome(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(Some(state))
    }

    /// Reconcile an indeterminate local intent.  `StillIndeterminate` keeps
    /// the quarantine state and can itself be replayed idempotently.
    pub async fn reconcile(
        &self,
        occurrence_key: impl Into<String>,
        outcome: LocalReconcileOutcome,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        let (kind, state) = match outcome {
            LocalReconcileOutcome::Committed => {
                ("reconcile_committed", LocalOutcomeState::Committed)
            }
            LocalReconcileOutcome::Rejected => ("reconcile_rejected", LocalOutcomeState::Rejected),
            LocalReconcileOutcome::StillIndeterminate => (
                "reconcile_still_indeterminate",
                LocalOutcomeState::Indeterminate,
            ),
        };
        self.append_outcome(
            occurrence_key.into(),
            kind,
            outcome.as_str().to_string(),
            &[LocalOutcomeState::Indeterminate],
            state,
        )
        .await
    }

    /// Append an explicit local rollback marker.  This does not delete the
    /// event or outbox row and never claims that an external effect was
    /// undone.
    pub async fn rollback_occurrence(
        &self,
        occurrence_key: impl Into<String>,
        reason: impl Into<String>,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.append_outcome(
            occurrence_key.into(),
            "rolled_back",
            reason.into(),
            &[
                LocalOutcomeState::Queued,
                LocalOutcomeState::Indeterminate,
                LocalOutcomeState::RolledBack,
            ],
            LocalOutcomeState::RolledBack,
        )
        .await
    }

    async fn append_outcome(
        &self,
        occurrence_key: String,
        kind: &str,
        payload: String,
        allowed: &[LocalOutcomeState],
        resulting_state: LocalOutcomeState,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        self.append_outcome_with_replay_policy(
            occurrence_key,
            kind,
            payload,
            allowed,
            resulting_state,
            true,
        )
        .await
    }

    async fn append_outcome_with_replay_policy(
        &self,
        occurrence_key: String,
        kind: &str,
        payload: String,
        allowed: &[LocalOutcomeState],
        resulting_state: LocalOutcomeState,
        allow_exact_replay: bool,
    ) -> Result<LocalOutcomeReceipt, LocalLeaseOutboxError> {
        validate_text(&occurrence_key, "occurrence key", 512)?;
        validate_text(&payload, "outcome payload", 65_536)?;
        let payload_sha256 = Sha256Digest::for_bytes(payload.as_bytes());
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let admission = find_admission(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::IllegalTransition(format!(
                "occurrence {occurrence_key} has no admitted event"
            ))
        })?;
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("event admission has no paired outbox row"))?;
        // Outcomes are attempt-scoped just like admissions.  A lease may be
        // reacquired under a newer generation after the original attempt
        // released, but that newer owner must never append a transition for
        // the historical occurrence.  Without this check the transition
        // would be journaled under the new fence and could make an old
        // occurrence appear to have been handled by the new attempt.
        ensure_current_occurrence_fence(self, &admission, &outbox)?;
        let current = current_outcome(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?;
        if !allowed.contains(&current) {
            match (
                allow_exact_replay,
                find_transition(
                    &mut transaction,
                    &self.lease_id,
                    &occurrence_key,
                    kind,
                    &self.owner_agent_id,
                )
                .await?,
            ) {
                (true, Some(existing)) if existing.payload_sha256 == payload_sha256 => {
                    transaction
                        .commit()
                        .await
                        .map_err(crate::cognitive_store::unavailable)?;
                    return Ok(LocalOutcomeReceipt {
                        lease_id: self.lease_id.clone(),
                        occurrence_key,
                        state: resulting_state,
                        event_id: existing.event_id,
                        external_effect: false,
                    });
                }
                _ => {}
            }
            return Err(LocalLeaseOutboxError::IllegalTransition(format!(
                "occurrence is already in {} state",
                current.as_str()
            )));
        }
        if let Some(existing) = find_transition(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            kind,
            &self.owner_agent_id,
        )
        .await?
        {
            if !allow_exact_replay {
                return Err(LocalLeaseOutboxError::IllegalTransition(
                    "dispatch claim was already consumed".to_string(),
                ));
            }
            if existing.payload_sha256 != payload_sha256 {
                return Err(LocalLeaseOutboxError::CasConflict(
                    "outcome replay changed its reason/payload".to_string(),
                ));
            }
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LocalOutcomeReceipt {
                lease_id: self.lease_id.clone(),
                occurrence_key,
                state: resulting_state,
                event_id: existing.event_id,
                external_effect: false,
            });
        }
        let sequence = next_event_sequence(&mut transaction, &self.lease_id).await?;
        let previous = event_head(&mut transaction, &self.lease_id).await?;
        let event_id = journal_row_id("event", &self.lease_id, sequence);
        let digest = event_digest(
            &self.lease_id,
            sequence,
            &event_id,
            &occurrence_key,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            kind,
            &payload_sha256,
            &previous,
        );
        insert_event(
            &mut transaction,
            EventInsert {
                lease_id: &self.lease_id,
                sequence,
                event_id: &event_id,
                occurrence_key: &occurrence_key,
                owner: &self.owner_agent_id,
                generation: self.generation,
                fencing_token: &self.fencing_token,
                kind,
                payload_json: &payload,
                payload_sha256: &payload_sha256,
                previous_sha256: &previous,
                event_sha256: &digest,
            },
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalOutcomeReceipt {
            lease_id: self.lease_id.clone(),
            occurrence_key,
            state: resulting_state,
            event_id,
            external_effect: false,
        })
    }

    pub async fn status(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<LocalOutcomeState, LocalLeaseOutboxError> {
        let occurrence_key = occurrence_key.into();
        validate_text(&occurrence_key, "occurrence key", 512)?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let admission = find_admission(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::IllegalTransition("occurrence not found".to_string())
        })?;
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("event admission has no paired outbox row"))?;
        // Status is read-only, but it still has to be scoped to the exact
        // admitted attempt. A newer generation must not observe or report
        // the state of an occurrence admitted under an older fence.
        ensure_current_occurrence_fence(self, &admission, &outbox)?;
        let state = current_outcome(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(state)
    }

    /// Verify that a serialized queue receipt still names the exact immutable
    /// event/outbox rows in this local journal.  Checking only the occurrence
    /// state is insufficient: a forged or stale receipt could otherwise reuse
    /// a queued occurrence while substituting a different topic or payload at
    /// the provider boundary.  This helper replays both hash chains and
    /// compares every dispatch-relevant field under one read transaction.
    ///
    /// The method is crate-visible because the production writer owns the
    /// public receipt type; it grants no dispatch authority and never mutates
    /// the journal.
    pub(crate) async fn verify_queued_receipt_binding(
        &self,
        occurrence_key: &str,
        event_id: &str,
        outbox_id: &str,
        topic: &str,
        payload_json: &str,
        payload_sha256: &Sha256Digest,
    ) -> Result<(), LocalLeaseOutboxError> {
        validate_text(occurrence_key, "occurrence key", 512)?;
        validate_text(event_id, "event id", 512)?;
        validate_text(outbox_id, "outbox id", 512)?;
        validate_text(topic, "outbox topic", 256)?;
        validate_text(payload_json, "event payload", 65_536)?;
        if Sha256Digest::for_bytes(payload_json.as_bytes()) != *payload_sha256 {
            return Err(LocalLeaseOutboxError::StaleFence(
                "queued receipt payload digest does not match its payload".to_string(),
            ));
        }

        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let event = find_admission(
            &mut transaction,
            &self.lease_id,
            occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("queued receipt event is missing".to_string())
        })?;
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("queued receipt outbox is missing".to_string())
        })?;
        ensure_current_occurrence_fence(self, &event, &outbox)?;
        if event.event_id != event_id
            || outbox.outbox_id != outbox_id
            || event.occurrence_key != occurrence_key
            || outbox.occurrence_key != occurrence_key
            || event.event_id != outbox.event_id
            || event.payload_json != payload_json
            || outbox.payload_json != payload_json
            || event.payload_sha256 != *payload_sha256
            || outbox.payload_sha256 != *payload_sha256
            || outbox.topic != topic
            || current_outcome(
                &mut transaction,
                &self.lease_id,
                occurrence_key,
                &self.owner_agent_id,
            )
            .await?
                != LocalOutcomeState::Queued
        {
            return Err(LocalLeaseOutboxError::StaleFence(
                "queued receipt does not match the immutable local admission".to_string(),
            ));
        }
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(())
    }

    /// Reopen one already-admitted occurrence without ever re-queuing a
    /// quarantined or terminal result.
    ///
    /// This closes the crash window between a durable outcome transition and
    /// lease release.  A queued occurrence returns its original receipt and
    /// leaves the lease active.  An indeterminate or terminal occurrence is
    /// released atomically after full chain/fence verification, but only when
    /// every *other* occurrence in this generation is already settled.  The
    /// latter guard is important for a replaying writer: releasing after one
    /// occurrence was reconciled would otherwise strand a second queued or
    /// indeterminate outbox row behind a terminal fence.  The outbox remains
    /// immutable local metadata and is never dispatched here.
    pub async fn finalize_replayed_occurrence(
        &self,
        occurrence_key: impl Into<String>,
    ) -> Result<LocalReplayFinalization, LocalLeaseOutboxError> {
        let occurrence_key = occurrence_key.into();
        validate_text(&occurrence_key, "occurrence key", 512)?;
        let mut transaction = self
            .store
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let events =
            verify_event_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        let outbox_rows =
            verify_outbox_chain(&mut transaction, &self.lease_id, &self.owner_agent_id).await?;
        verify_event_outbox_pairing(&events, &outbox_rows)?;
        let admission = find_admission(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?;
        let Some(admission) = admission else {
            // `acquire` and `admit` are intentionally separate local
            // transactions.  A process can therefore die after the lease
            // row commits but before the first event/outbox pair.  This is a
            // recoverable replay, not journal corruption: the caller keeps
            // the verified active handle and retries the original admit.
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LocalReplayFinalization::NotAdmitted);
        };
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("event admission has no paired outbox row"))?;
        let queued = queued_receipt(self, &admission, &outbox)?;
        let outcome = current_outcome(
            &mut transaction,
            &self.lease_id,
            &occurrence_key,
            &self.owner_agent_id,
        )
        .await?;
        if outcome == LocalOutcomeState::Queued {
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LocalReplayFinalization::Queued(queued));
        }
        // Recovery of one occurrence must not close the lease while another
        // current-generation occurrence still needs dispatch or
        // reconciliation.  Keep this check in the same transaction as the
        // terminal append so a concurrent outcome transition cannot race the
        // decision.  The occurrence being finalized is deliberately excluded
        // because its non-queued state is the reason this replay can settle.
        ensure_no_unresolved_outcomes_except(
            &events,
            self.generation,
            &self.fencing_token,
            Some(&occurrence_key),
        )?;
        self.verify_bound_compact_journals(&mut transaction).await?;
        let binding = self.binding();
        let released = append_lease(
            &mut transaction,
            &self.lease_id,
            &self.owner_agent_id,
            self.generation,
            &self.fencing_token,
            LocalLeaseState::Released,
            Some(&lease),
            binding.as_ref(),
        )
        .await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalReplayFinalization::Released {
            outcome,
            lease: released,
            external_effect: false,
        })
    }

    pub async fn snapshot_counts(&self) -> Result<LocalLeaseOutboxCounts, LocalLeaseOutboxError> {
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease_rows =
            count_rows(&mut transaction, "cognitive_local_leases", &self.lease_id).await?;
        let event_rows =
            count_rows(&mut transaction, "cognitive_local_events", &self.lease_id).await?;
        let outbox_rows =
            count_rows(&mut transaction, "cognitive_local_outbox", &self.lease_id).await?;
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalLeaseOutboxCounts {
            lease_rows,
            event_rows,
            outbox_rows,
        })
    }

    async fn current_lease(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<LocalLease, LocalLeaseOutboxError> {
        let (latest, _) =
            load_lease_chain(transaction, &self.lease_id, &self.owner_agent_id).await?;
        latest.ok_or_else(|| {
            LocalLeaseOutboxError::StaleFence("local lease does not exist".to_string())
        })
    }

    /// Audit compact journals in the caller-owned terminalization transaction.
    ///
    /// The compact reopen audit has a convenient store-wide API, but it starts
    /// its own SQLite transaction. Calling it while this handle holds the
    /// `BEGIN IMMEDIATE` lifecycle lock would create a nested-lock/deadlock
    /// hazard. The transaction-scoped helper performs the same descriptor,
    /// fence, hash-chain, owner, and historical lease-head checks through this
    /// exact transaction instead.
    async fn verify_bound_compact_journals(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
    ) -> Result<(), LocalLeaseOutboxError> {
        crate::local_compact_executor::verify_local_compact_journals_for_lease_in_transaction(
            &self.store,
            transaction,
            &self.lease_id,
        )
        .await
        .map_err(|error| match error {
            crate::local_compact_executor::LocalCompactExecutorError::Store(error) => {
                LocalLeaseOutboxError::Store(error)
            }
            other => LocalLeaseOutboxError::Corrupt(format!(
                "compact journal integrity audit failed: {other}"
            )),
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LocalLeaseOutboxCounts {
    pub lease_rows: u64,
    pub event_rows: u64,
    pub outbox_rows: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalReconcileOutcome {
    Committed,
    Rejected,
    StillIndeterminate,
}

impl LocalReconcileOutcome {
    fn as_str(self) -> &'static str {
        match self {
            Self::Committed => "committed",
            Self::Rejected => "rejected",
            Self::StillIndeterminate => "still_indeterminate",
        }
    }
}

impl CognitiveStore {
    /// Inspect one exact Agent-local lease head without opening a writable
    /// handle or changing any row.  The read transaction verifies the full
    /// append-only lease chain and returns the head witness needed by an
    /// explicit successor CAS.  `ExpiredActive` is only a classifier: this
    /// method never performs takeover, release, rollback, or dispatch.
    pub async fn inspect_local_lease_head(
        &self,
        lease_id: impl Into<String>,
    ) -> Result<LocalLeaseHeadInspection, LocalLeaseOutboxError> {
        let lease_id = lease_id.into();
        validate_text(&lease_id, "lease id", 512)?;
        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let (head, _) =
            load_lease_chain(&mut transaction, &lease_id, self.owner_agent_id()).await?;
        let disposition = match head.as_ref() {
            None => LocalLeaseHeadDisposition::Missing,
            Some(lease) => match lease.state {
                LocalLeaseState::Active => {
                    let expired = match lease.lease_expires_at_unix_seconds {
                        Some(expiry) => {
                            let expiry = i64::try_from(expiry).map_err(|_| {
                                LocalLeaseOutboxError::Clock("lease expiry overflow".to_string())
                            })?;
                            expiry <= now_unix_seconds()?
                        }
                        None => false,
                    };
                    if expired {
                        LocalLeaseHeadDisposition::ExpiredActive
                    } else {
                        LocalLeaseHeadDisposition::Active
                    }
                }
                LocalLeaseState::Released => LocalLeaseHeadDisposition::Released,
                LocalLeaseState::RolledBack => LocalLeaseHeadDisposition::RolledBack,
            },
        };
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LocalLeaseHeadInspection {
            lease_id,
            head,
            disposition,
        })
    }

    /// Opens generation one of the local-only lease/outbox seam, or replays an
    /// exact active acquisition.
    pub async fn acquire_local_lease(
        &self,
        lease_id: impl Into<String>,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        LocalLeaseOutbox::acquire(self, lease_id, generation, fencing_token).await
    }

    /// Opens or replays a lease with persisted authority/owner epochs and an
    /// absolute Unix-seconds expiry.  The returned handle is eligible for the
    /// schema-bound compact witness path.
    pub async fn acquire_local_lease_bound(
        &self,
        lease_id: impl Into<String>,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let binding =
            LocalLeaseBinding::new(authority_epoch, owner_epoch, lease_expires_at_unix_seconds)?;
        LocalLeaseOutbox::acquire_bound(self, lease_id, binding, generation, fencing_token).await
    }

    /// Host-bound qualification-only acquisition with a strict monotonic
    /// `(authority_epoch, owner_epoch)` contract.  The caller-provided epoch
    /// pair is persisted in the local append-only lease chain; no production
    /// supervisor authority is implied by this API.
    pub async fn acquire_host_bound_lease(
        &self,
        lease_id: impl Into<String>,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let binding =
            LocalLeaseBinding::new(authority_epoch, owner_epoch, lease_expires_at_unix_seconds)?;
        LocalLeaseOutbox::acquire_host_bound(self, lease_id, binding, generation, fencing_token)
            .await
    }

    pub async fn acquire_local_lease_after(
        &self,
        lease_id: impl Into<String>,
        expected_generation: u64,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        LocalLeaseOutbox::acquire_after(
            self,
            lease_id,
            expected_generation,
            generation,
            fencing_token,
        )
        .await
    }

    /// Acquire a generation after an exact append-only lease-head CAS.
    ///
    /// Prefer this method whenever the caller may race with another owner or
    /// with a release/rollback transition.  The expected head returned by
    /// [`LocalLeaseOutbox::release`] or
    /// [`LocalLeaseOutbox::rollback_lease`] carries the sequence, state,
    /// generation, fencing token, and digest witness required by the CAS.
    pub async fn acquire_local_lease_after_head(
        &self,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        LocalLeaseOutbox::acquire_after_head(
            self,
            lease_id,
            expected_head,
            generation,
            fencing_token,
        )
        .await
    }

    pub async fn acquire_local_lease_after_head_bound(
        &self,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let binding =
            LocalLeaseBinding::new(authority_epoch, owner_epoch, lease_expires_at_unix_seconds)?;
        LocalLeaseOutbox::acquire_after_head_bound(
            self,
            lease_id,
            expected_head,
            binding,
            generation,
            fencing_token,
        )
        .await
    }

    /// Host-bound qualification-only successor acquisition after an exact
    /// append-only head CAS.  Epoch regressions and stale heads fail closed.
    pub async fn acquire_host_bound_lease_after_head(
        &self,
        lease_id: impl Into<String>,
        expected_head: LocalLease,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<LocalLeaseAcquire, LocalLeaseOutboxError> {
        let binding =
            LocalLeaseBinding::new(authority_epoch, owner_epoch, lease_expires_at_unix_seconds)?;
        LocalLeaseOutbox::acquire_after_head_host_bound(
            self,
            lease_id,
            expected_head,
            binding,
            generation,
            fencing_token,
        )
        .await
    }

    pub async fn reopen_local_lease(
        &self,
        lease_id: impl Into<String>,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<LocalLeaseOutbox, LocalLeaseOutboxError> {
        LocalLeaseOutbox::reopen(self, lease_id, generation, fencing_token).await
    }

    /// Reopen an exact active head under the host-bound qualification
    /// contract.  The full head witness and binding are checked before a
    /// writable handle is returned; this does not enable production authority.
    pub async fn reopen_host_bound_lease(
        &self,
        expected_head: LocalLease,
        authority_epoch: u64,
        owner_epoch: u64,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<LocalLeaseOutbox, LocalLeaseOutboxError> {
        let binding =
            LocalLeaseBinding::new(authority_epoch, owner_epoch, lease_expires_at_unix_seconds)?;
        LocalLeaseOutbox::reopen_bound(self, expected_head, binding).await
    }
}

#[derive(Clone, Debug)]
struct EventRow {
    sequence: u64,
    event_id: String,
    occurrence_key: String,
    owner_agent_id: AgentId,
    generation: u64,
    fencing_token: String,
    kind: String,
    payload_json: String,
    payload_sha256: Sha256Digest,
    previous_sha256: Sha256Digest,
    event_sha256: Sha256Digest,
}

#[derive(Clone, Debug)]
struct OutboxRow {
    sequence: u64,
    outbox_id: String,
    event_id: String,
    occurrence_key: String,
    owner_agent_id: AgentId,
    generation: u64,
    fencing_token: String,
    topic: String,
    payload_json: String,
    payload_sha256: Sha256Digest,
    previous_sha256: Sha256Digest,
    outbox_sha256: Sha256Digest,
}

struct EventInsert<'a> {
    lease_id: &'a str,
    sequence: u64,
    event_id: &'a str,
    occurrence_key: &'a str,
    owner: &'a AgentId,
    generation: u64,
    fencing_token: &'a str,
    kind: &'a str,
    payload_json: &'a str,
    payload_sha256: &'a Sha256Digest,
    previous_sha256: &'a Sha256Digest,
    event_sha256: &'a Sha256Digest,
}

struct OutboxInsert<'a> {
    lease_id: &'a str,
    sequence: u64,
    outbox_id: &'a str,
    event_id: &'a str,
    occurrence_key: &'a str,
    owner: &'a AgentId,
    generation: u64,
    fencing_token: &'a str,
    topic: &'a str,
    payload_json: &'a str,
    payload_sha256: &'a Sha256Digest,
    previous_sha256: &'a Sha256Digest,
    outbox_sha256: &'a Sha256Digest,
}

pub(crate) async fn append_lease(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    owner: &AgentId,
    generation: u64,
    fencing_token: &str,
    state: LocalLeaseState,
    previous: Option<&LocalLease>,
    binding: Option<&LocalLeaseBinding>,
) -> Result<LocalLease, LocalLeaseOutboxError> {
    let sequence = previous.map_or(1, |lease| lease.lease_sequence + 1);
    let previous_sha256 = previous
        .map(|lease| lease.lease_sha256.clone())
        .unwrap_or_else(|| Sha256Digest::for_bytes(GENESIS_LEASE_SHA256));
    let lease_sha256 = lease_digest(
        lease_id,
        sequence,
        owner,
        generation,
        fencing_token,
        state,
        &previous_sha256,
        binding,
    );
    let recorded_at = now_unix_seconds()?;
    sqlx::query(
        "INSERT INTO cognitive_local_leases (
            lease_id, lease_sequence, owner_agent_id, generation, fencing_token,
            state, authority_epoch, owner_epoch, lease_expires_at_unix_seconds,
            previous_sha256, lease_sha256, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(lease_id)
    .bind(to_i64(sequence, "lease sequence")?)
    .bind(owner.as_str())
    .bind(to_i64(generation, "lease generation")?)
    .bind(fencing_token)
    .bind(state.as_str())
    .bind(
        binding
            .map(|value| to_i64(value.authority_epoch, "authority epoch"))
            .transpose()?,
    )
    .bind(
        binding
            .map(|value| to_i64(value.owner_epoch, "owner epoch"))
            .transpose()?,
    )
    .bind(
        binding
            .map(|value| to_i64(value.lease_expires_at_unix_seconds, "lease expiry"))
            .transpose()?,
    )
    .bind(previous_sha256.as_str())
    .bind(lease_sha256.as_str())
    .bind(recorded_at)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(LocalLease {
        lease_id: lease_id.to_string(),
        lease_sequence: sequence,
        owner_agent_id: owner.clone(),
        generation,
        fencing_token: fencing_token.to_string(),
        state,
        authority_epoch: binding.map(|value| value.authority_epoch),
        owner_epoch: binding.map(|value| value.owner_epoch),
        lease_expires_at_unix_seconds: binding.map(|value| value.lease_expires_at_unix_seconds),
        previous_sha256,
        lease_sha256,
    })
}

async fn fencing_token_seen(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    fencing_token: &str,
) -> Result<bool, LocalLeaseOutboxError> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_leases
         WHERE lease_id = ? AND fencing_token = ?",
    )
    .bind(lease_id)
    .bind(fencing_token)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(count != 0)
}

pub(crate) async fn load_lease_chain(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<(Option<LocalLease>, usize), LocalLeaseOutboxError> {
    let rows = sqlx::query(
        "SELECT lease_sequence, owner_agent_id, generation, fencing_token,
                state, authority_epoch, owner_epoch,
                lease_expires_at_unix_seconds, previous_sha256, lease_sha256
         FROM cognitive_local_leases
         WHERE lease_id = ?
         ORDER BY lease_sequence",
    )
    .bind(lease_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() > MAX_LEASE_ROWS {
        return Err(corrupt(format!(
            "lease journal exceeds {MAX_LEASE_ROWS} rows"
        )));
    }
    let mut previous = Sha256Digest::for_bytes(GENESIS_LEASE_SHA256);
    let mut active_fencing_tokens = BTreeSet::new();
    let mut latest: Option<LocalLease> = None;
    for (index, row) in rows.iter().enumerate() {
        let sequence = read_u64(row, "lease_sequence")?;
        if sequence != u64::try_from(index + 1).unwrap_or(u64::MAX) {
            return Err(corrupt("lease sequence is not contiguous"));
        }
        let owner = parse_agent(row, "owner_agent_id")?;
        if owner != *expected_owner {
            return Err(corrupt("local lease journal contains a foreign owner"));
        }
        let generation = read_u64(row, "generation")?;
        validate_generation(generation)?;
        let fencing_token: String = row
            .try_get("fencing_token")
            .map_err(crate::cognitive_store::unavailable)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        let state = LocalLeaseState::parse(
            row.try_get::<String, _>("state")
                .map_err(crate::cognitive_store::unavailable)?
                .as_str(),
        )?;
        let authority_epoch = optional_u64(row, "authority_epoch")?;
        let owner_epoch = optional_u64(row, "owner_epoch")?;
        let lease_expires_at_unix_seconds = optional_u64(row, "lease_expires_at_unix_seconds")?;
        let binding = match (authority_epoch, owner_epoch, lease_expires_at_unix_seconds) {
            (None, None, None) => None,
            (Some(authority_epoch), Some(owner_epoch), Some(lease_expires_at_unix_seconds)) => {
                Some(LocalLeaseBinding::new(
                    authority_epoch,
                    owner_epoch,
                    lease_expires_at_unix_seconds,
                )?)
            }
            _ => return Err(corrupt("lease binding columns are partially populated")),
        };
        if index == 0 && (state != LocalLeaseState::Active || generation != 1) {
            return Err(corrupt(
                "lease journal must begin at generation one in active state",
            ));
        }
        let previous_sha256 = digest_from_row(row, "previous_sha256")?;
        let lease_sha256 = digest_from_row(row, "lease_sha256")?;
        if previous_sha256 != previous {
            return Err(corrupt("lease previous digest mismatch"));
        }
        let expected_digest = lease_digest(
            lease_id,
            sequence,
            &owner,
            generation,
            &fencing_token,
            state,
            &previous,
            binding.as_ref(),
        );
        if lease_sha256 != expected_digest {
            return Err(corrupt("lease digest mismatch"));
        }
        if index > 0 {
            let prior = latest.as_ref().expect("lease prior row");
            if generation < prior.generation {
                return Err(corrupt("lease generation regressed"));
            }
            if state != LocalLeaseState::Active && binding != prior_binding(prior) {
                return Err(corrupt(
                    "lease terminal row changed authority/owner/expiry binding",
                ));
            }
            if state == LocalLeaseState::Active
                && prior_binding(prior).is_some()
                && binding.is_none()
            {
                return Err(corrupt(
                    "bound lease generation cannot downgrade to an unbound lease",
                ));
            }
            if state == LocalLeaseState::Active {
                if prior.state == LocalLeaseState::Active {
                    return Err(corrupt("lease journal has two active rows"));
                }
                if generation != prior.generation.saturating_add(1) {
                    return Err(corrupt("active lease generation did not advance by one"));
                }
                if !active_fencing_tokens.insert(fencing_token.clone()) {
                    return Err(corrupt("active lease fencing token was reused"));
                }
            } else if prior.state != LocalLeaseState::Active
                || generation != prior.generation
                || fencing_token != prior.fencing_token
            {
                return Err(corrupt(
                    "lease terminal row changed generation or fencing token",
                ));
            }
        } else if state == LocalLeaseState::Active {
            active_fencing_tokens.insert(fencing_token.clone());
        }
        let lease = LocalLease {
            lease_id: lease_id.to_string(),
            lease_sequence: sequence,
            owner_agent_id: owner,
            generation,
            fencing_token,
            state,
            authority_epoch,
            owner_epoch,
            lease_expires_at_unix_seconds,
            previous_sha256,
            lease_sha256: lease_sha256.clone(),
        };
        previous = lease_sha256;
        latest = Some(lease);
    }
    Ok((latest, rows.len()))
}

/// Return every fence tuple granted anywhere in the lease history.
/// Event/outbox rows are append-only and may outlive the active lease row, so
/// checking membership in the complete history (rather than only comparing
/// with the current active head) preserves valid historical rows after a
/// release, rollback, or timeout expiry while rejecting forged rows that carry
/// a generation/fence never granted by the lease journal. `load_lease_chain`
/// validates every row's digest and transition shape before this helper is
/// called, and the set deduplicates the terminal copy of each tuple.
async fn active_lease_fences(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<BTreeSet<(u64, String)>, LocalLeaseOutboxError> {
    let rows = sqlx::query(
        "SELECT owner_agent_id, generation, fencing_token
         FROM cognitive_local_leases
         WHERE lease_id = ?",
    )
    .bind(lease_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let mut fences = BTreeSet::new();
    for row in rows {
        let owner = parse_agent(&row, "owner_agent_id")?;
        if owner != *expected_owner {
            return Err(corrupt("lease fence history contains a foreign owner"));
        }
        let generation = read_u64(&row, "generation")?;
        validate_generation(generation)?;
        let fencing_token: String = row
            .try_get("fencing_token")
            .map_err(crate::cognitive_store::unavailable)?;
        validate_text(&fencing_token, "fencing token", 256)?;
        fences.insert((generation, fencing_token));
    }
    Ok(fences)
}

async fn insert_event(
    transaction: &mut Transaction<'_, Sqlite>,
    event: EventInsert<'_>,
) -> Result<(), LocalLeaseOutboxError> {
    let recorded_at = now_unix_seconds()?;
    sqlx::query(
        "INSERT INTO cognitive_local_events (
            lease_id, event_sequence, event_id, occurrence_key, owner_agent_id,
            generation, fencing_token, event_kind, payload_json, payload_sha256,
            previous_sha256, event_sha256, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(event.lease_id)
    .bind(to_i64(event.sequence, "event sequence")?)
    .bind(event.event_id)
    .bind(event.occurrence_key)
    .bind(event.owner.as_str())
    .bind(to_i64(event.generation, "event generation")?)
    .bind(event.fencing_token)
    .bind(event.kind)
    .bind(event.payload_json)
    .bind(event.payload_sha256.as_str())
    .bind(event.previous_sha256.as_str())
    .bind(event.event_sha256.as_str())
    .bind(recorded_at)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}

async fn insert_outbox(
    transaction: &mut Transaction<'_, Sqlite>,
    outbox: OutboxInsert<'_>,
) -> Result<(), LocalLeaseOutboxError> {
    let recorded_at = now_unix_seconds()?;
    sqlx::query(
        "INSERT INTO cognitive_local_outbox (
            lease_id, outbox_sequence, outbox_id, event_id, occurrence_key,
            owner_agent_id, generation, fencing_token, topic, payload_json,
            payload_sha256, previous_sha256, outbox_sha256, dispatch_state,
            recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?)",
    )
    .bind(outbox.lease_id)
    .bind(to_i64(outbox.sequence, "outbox sequence")?)
    .bind(outbox.outbox_id)
    .bind(outbox.event_id)
    .bind(outbox.occurrence_key)
    .bind(outbox.owner.as_str())
    .bind(to_i64(outbox.generation, "outbox generation")?)
    .bind(outbox.fencing_token)
    .bind(outbox.topic)
    .bind(outbox.payload_json)
    .bind(outbox.payload_sha256.as_str())
    .bind(outbox.previous_sha256.as_str())
    .bind(outbox.outbox_sha256.as_str())
    .bind(recorded_at)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}

async fn verify_event_chain(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<Vec<EventRow>, LocalLeaseOutboxError> {
    let lease_fences = active_lease_fences(transaction, lease_id, expected_owner).await?;
    let rows = sqlx::query(
        "SELECT event_sequence, event_id, occurrence_key, owner_agent_id,
                generation, fencing_token, event_kind, payload_json,
                payload_sha256, previous_sha256, event_sha256
         FROM cognitive_local_events
         WHERE lease_id = ?
         ORDER BY event_sequence",
    )
    .bind(lease_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() > MAX_EVENT_ROWS {
        return Err(corrupt(format!(
            "event journal exceeds {MAX_EVENT_ROWS} rows"
        )));
    }
    let mut previous = Sha256Digest::for_bytes(GENESIS_EVENT_SHA256);
    // Public append APIs enforce this state machine before writing a row, but
    // reopen-time verification must repeat the invariant for imported or
    // otherwise damaged stores.  Without it, a late
    // `reconcile_still_indeterminate` (or rollback) row could be appended
    // after a terminal outcome and `current_outcome` would silently downgrade
    // the occurrence back to a non-terminal/quarantined state.
    let mut outcome_states = BTreeMap::new();
    let mut seen_kinds = BTreeSet::new();
    let mut events = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let sequence = read_u64(row, "event_sequence")?;
        if sequence != u64::try_from(index + 1).unwrap_or(u64::MAX) {
            return Err(corrupt("event sequence is not contiguous"));
        }
        let event_id: String = row
            .try_get("event_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let occurrence_key: String = row
            .try_get("occurrence_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let owner = parse_agent(row, "owner_agent_id")?;
        if owner != *expected_owner {
            return Err(corrupt("event journal contains a foreign owner"));
        }
        let generation = read_u64(row, "generation")?;
        let fencing_token: String = row
            .try_get("fencing_token")
            .map_err(crate::cognitive_store::unavailable)?;
        validate_text(&fencing_token, "event fencing token", 256)?;
        if !lease_fences.contains(&(generation, fencing_token.clone())) {
            return Err(corrupt(
                "event row references a generation/fencing token never active in the lease history",
            ));
        }
        let kind: String = row
            .try_get("event_kind")
            .map_err(crate::cognitive_store::unavailable)?;
        let payload_json: String = row
            .try_get("payload_json")
            .map_err(crate::cognitive_store::unavailable)?;
        let payload_sha256 = digest_from_row(row, "payload_sha256")?;
        if Sha256Digest::for_bytes(payload_json.as_bytes()) != payload_sha256 {
            return Err(corrupt("event payload digest mismatch"));
        }
        let previous_sha256 = digest_from_row(row, "previous_sha256")?;
        if previous_sha256 != previous {
            return Err(corrupt("event previous digest mismatch"));
        }
        let event_sha256 = digest_from_row(row, "event_sha256")?;
        if event_sha256
            != event_digest(
                lease_id,
                sequence,
                &event_id,
                &occurrence_key,
                &owner,
                generation,
                &fencing_token,
                &kind,
                &payload_sha256,
                &previous,
            )
        {
            return Err(corrupt("event digest mismatch"));
        }
        advance_outcome_state(&mut outcome_states, &mut seen_kinds, &occurrence_key, &kind)?;
        previous = event_sha256.clone();
        events.push(EventRow {
            sequence,
            event_id,
            occurrence_key,
            owner_agent_id: owner,
            generation,
            fencing_token,
            kind,
            payload_json,
            payload_sha256,
            previous_sha256,
            event_sha256,
        });
    }
    Ok(events)
}

pub(crate) async fn verify_event_chain_integrity(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<(), LocalLeaseOutboxError> {
    verify_event_chain(transaction, lease_id, expected_owner)
        .await
        .map(|_| ())
}

/// Apply one event kind to the per-occurrence outcome state while replaying
/// the append-only event chain.  The SQL unique indexes protect the normal
/// writer path, but a verifier must also reject a damaged/imported chain that
/// contains a duplicate kind or a transition after a terminal outcome.
fn advance_outcome_state(
    states: &mut BTreeMap<String, LocalOutcomeState>,
    seen_kinds: &mut BTreeSet<(String, String)>,
    occurrence_key: &str,
    kind: &str,
) -> Result<(), LocalLeaseOutboxError> {
    if !seen_kinds.insert((occurrence_key.to_string(), kind.to_string())) {
        return Err(corrupt(format!(
            "occurrence {occurrence_key} contains duplicate {kind} transition"
        )));
    }

    let current = states.get(occurrence_key).copied();
    let next = match (current, kind) {
        (None, "admitted") => LocalOutcomeState::Queued,
        (None, _) => {
            return Err(corrupt(format!(
                "occurrence {occurrence_key} has {kind} transition before admission"
            )));
        }
        (Some(_), "admitted") => {
            return Err(corrupt(format!(
                "occurrence {occurrence_key} contains a late or duplicate admission"
            )));
        }
        (Some(LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate), "indeterminate") => {
            LocalOutcomeState::Indeterminate
        }
        // Higher-level qualification sagas may learn that the target-side
        // write already committed while the local occurrence is still in its
        // durable Queued state.  They record that fact as a single
        // `reconcile_committed` event (the `apply` path).  Replay must accept
        // this direct terminal transition just as it accepts the usual
        // Indeterminate -> Committed recovery path.
        (
            Some(LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate),
            "reconcile_committed",
        ) => LocalOutcomeState::Committed,
        // The corresponding `reject` path can also settle a still-queued
        // qualification without first manufacturing an indeterminate marker.
        // It is terminal and one-shot; later transitions remain rejected by
        // the terminal-state arm below (and duplicate kinds are rejected
        // above).
        (
            Some(LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate),
            "reconcile_rejected",
        ) => LocalOutcomeState::Rejected,
        (Some(LocalOutcomeState::Indeterminate), "reconcile_still_indeterminate") => {
            LocalOutcomeState::Indeterminate
        }
        (
            Some(
                LocalOutcomeState::Queued
                | LocalOutcomeState::Indeterminate
                | LocalOutcomeState::RolledBack,
            ),
            "rolled_back",
        ) => LocalOutcomeState::RolledBack,
        (Some(state), _) => {
            return Err(corrupt(format!(
                "occurrence {occurrence_key} has invalid {kind} transition from {}",
                state.as_str()
            )));
        }
    };
    states.insert(occurrence_key.to_string(), next);
    Ok(())
}

/// Reject a normal release/rollback while any admitted local occurrence is
/// still awaiting an outcome.  `expire_lease` intentionally remains a
/// separate timeout path: expiry is an explicit quarantine decision after a
/// deadline, whereas a host release/rollback before that deadline must first
/// settle each local intent (reconcile, reject, or occurrence rollback).
fn ensure_no_unresolved_outcomes(
    events: &[EventRow],
    generation: u64,
    fencing_token: &str,
) -> Result<(), LocalLeaseOutboxError> {
    ensure_no_unresolved_outcomes_except(events, generation, fencing_token, None)
}

/// Variant of [`ensure_no_unresolved_outcomes`] used while finalizing one
/// replayed occurrence.  The requested occurrence is already known to be
/// non-queued by the caller, so it may be excluded from the unresolved set;
/// every other occurrence must still be terminal before the lease can close.
fn ensure_no_unresolved_outcomes_except(
    events: &[EventRow],
    generation: u64,
    fencing_token: &str,
    excluded_occurrence: Option<&str>,
) -> Result<(), LocalLeaseOutboxError> {
    let mut states = BTreeMap::new();
    let mut seen_kinds = BTreeSet::new();
    for event in events {
        // Historical generations remain part of the verified append-only
        // chain, but their unresolved outcomes are no longer writable by a
        // successor (the exact generation/fence is required for every
        // outcome append).  Only the handle's current generation may block a
        // normal release/rollback; expiry is the explicit quarantine path
        // for an older generation.
        if event.generation != generation || event.fencing_token != fencing_token {
            continue;
        }
        advance_outcome_state(
            &mut states,
            &mut seen_kinds,
            &event.occurrence_key,
            &event.kind,
        )?;
    }
    let unresolved = states
        .iter()
        .filter_map(|(occurrence_key, state)| {
            if excluded_occurrence.is_some_and(|excluded| excluded == occurrence_key) {
                return None;
            }
            matches!(
                state,
                LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate
            )
            .then_some(occurrence_key.as_str())
        })
        .collect::<Vec<_>>();
    if unresolved.is_empty() {
        return Ok(());
    }
    Err(LocalLeaseOutboxError::IllegalTransition(format!(
        "cannot terminalize lease with unresolved local occurrences: {}",
        unresolved.join(", ")
    )))
}

async fn verify_outbox_chain(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<Vec<OutboxRow>, LocalLeaseOutboxError> {
    let lease_fences = active_lease_fences(transaction, lease_id, expected_owner).await?;
    let rows = sqlx::query(
        "SELECT outbox_sequence, outbox_id, event_id, occurrence_key,
                owner_agent_id, generation, fencing_token, topic, payload_json,
                payload_sha256, previous_sha256, outbox_sha256
         FROM cognitive_local_outbox
         WHERE lease_id = ?
         ORDER BY outbox_sequence",
    )
    .bind(lease_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() > MAX_OUTBOX_ROWS {
        return Err(corrupt(format!("outbox exceeds {MAX_OUTBOX_ROWS} rows")));
    }
    let mut previous = Sha256Digest::for_bytes(GENESIS_OUTBOX_SHA256);
    let mut outbox_rows = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let sequence = read_u64(row, "outbox_sequence")?;
        if sequence != u64::try_from(index + 1).unwrap_or(u64::MAX) {
            return Err(corrupt("outbox sequence is not contiguous"));
        }
        let outbox_id: String = row
            .try_get("outbox_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let event_id: String = row
            .try_get("event_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let occurrence_key: String = row
            .try_get("occurrence_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let owner = parse_agent(row, "owner_agent_id")?;
        if owner != *expected_owner {
            return Err(corrupt("outbox contains a foreign owner"));
        }
        let generation = read_u64(row, "generation")?;
        let fencing_token: String = row
            .try_get("fencing_token")
            .map_err(crate::cognitive_store::unavailable)?;
        validate_text(&fencing_token, "outbox fencing token", 256)?;
        if !lease_fences.contains(&(generation, fencing_token.clone())) {
            return Err(corrupt(
                "outbox row references a generation/fencing token never active in the lease history",
            ));
        }
        let topic: String = row
            .try_get("topic")
            .map_err(crate::cognitive_store::unavailable)?;
        let payload_json: String = row
            .try_get("payload_json")
            .map_err(crate::cognitive_store::unavailable)?;
        let payload_sha256 = digest_from_row(row, "payload_sha256")?;
        if Sha256Digest::for_bytes(payload_json.as_bytes()) != payload_sha256 {
            return Err(corrupt("outbox payload digest mismatch"));
        }
        let previous_sha256 = digest_from_row(row, "previous_sha256")?;
        if previous_sha256 != previous {
            return Err(corrupt("outbox previous digest mismatch"));
        }
        let outbox_sha256 = digest_from_row(row, "outbox_sha256")?;
        if outbox_sha256
            != outbox_digest(
                lease_id,
                sequence,
                &outbox_id,
                &event_id,
                &occurrence_key,
                &owner,
                generation,
                &fencing_token,
                &topic,
                &payload_sha256,
                &previous,
            )
        {
            return Err(corrupt("outbox digest mismatch"));
        }
        previous = outbox_sha256.clone();
        outbox_rows.push(OutboxRow {
            sequence,
            outbox_id,
            event_id,
            occurrence_key,
            owner_agent_id: owner,
            generation,
            fencing_token,
            topic,
            payload_json,
            payload_sha256,
            previous_sha256,
            outbox_sha256,
        });
    }
    Ok(outbox_rows)
}

/// Verify the one-to-one relationship between admitted events and outbox
/// intents for a lease.
///
/// The outbox table has a foreign key in the event direction, but no reverse
/// constraint can require every admitted event to have exactly one intent.
/// The normal admission transaction creates the pair together; this helper
/// repeats that invariant for terminal/recovery transactions so a damaged or
/// imported journal cannot be hidden by releasing the lease.  Both input
/// chains have already been hash-checked by their callers.
fn verify_event_outbox_pairing(
    events: &[EventRow],
    outbox_rows: &[OutboxRow],
) -> Result<(), LocalLeaseOutboxError> {
    let mut admissions = BTreeMap::new();
    for event in events.iter().filter(|event| event.kind == "admitted") {
        if admissions
            .insert(event.occurrence_key.as_str(), event)
            .is_some()
        {
            return Err(corrupt(format!(
                "occurrence {} has more than one admitted event",
                event.occurrence_key
            )));
        }
    }

    let mut paired_occurrences = BTreeSet::new();
    for outbox in outbox_rows {
        let Some(event) = admissions.get(outbox.occurrence_key.as_str()) else {
            return Err(corrupt(format!(
                "local outbox row is not paired with the exact admitted event (outbox {})",
                outbox.outbox_id
            )));
        };
        if !paired_occurrences.insert(outbox.occurrence_key.as_str()) {
            return Err(corrupt(format!(
                "occurrence {} has more than one outbox intent",
                outbox.occurrence_key
            )));
        }
        if event.event_id != outbox.event_id
            || event.occurrence_key != outbox.occurrence_key
            || event.owner_agent_id != outbox.owner_agent_id
            || event.generation != outbox.generation
            || event.fencing_token != outbox.fencing_token
            || event.payload_json != outbox.payload_json
            || event.payload_sha256 != outbox.payload_sha256
        {
            return Err(corrupt(format!(
                "local outbox row is not paired with the exact admitted event (outbox {})",
                outbox.outbox_id
            )));
        }
    }

    if admissions.len() != outbox_rows.len() || paired_occurrences.len() != admissions.len() {
        return Err(corrupt(format!(
            "local event/outbox admission cardinality mismatch (events {}, outbox {})",
            admissions.len(),
            outbox_rows.len()
        )));
    }
    Ok(())
}

pub(crate) async fn verify_outbox_chain_integrity(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    expected_owner: &AgentId,
) -> Result<(), LocalLeaseOutboxError> {
    verify_outbox_chain(transaction, lease_id, expected_owner)
        .await
        .map(|_| ())
}

async fn find_admission(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    occurrence_key: &str,
    owner: &AgentId,
) -> Result<Option<EventRow>, LocalLeaseOutboxError> {
    let events = verify_event_chain(transaction, lease_id, owner).await?;
    Ok(events
        .into_iter()
        .find(|event| event.occurrence_key == occurrence_key && event.kind == "admitted"))
}

async fn find_transition(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    occurrence_key: &str,
    kind: &str,
    owner: &AgentId,
) -> Result<Option<EventRow>, LocalLeaseOutboxError> {
    let events = verify_event_chain(transaction, lease_id, owner).await?;
    Ok(events
        .into_iter()
        .find(|event| event.occurrence_key == occurrence_key && event.kind == kind))
}

async fn find_outbox(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    occurrence_key: &str,
    owner: &AgentId,
) -> Result<Option<OutboxRow>, LocalLeaseOutboxError> {
    let rows = verify_outbox_chain(transaction, lease_id, owner).await?;
    Ok(rows
        .into_iter()
        .find(|row| row.occurrence_key == occurrence_key))
}

async fn current_outcome(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    occurrence_key: &str,
    owner: &AgentId,
) -> Result<LocalOutcomeState, LocalLeaseOutboxError> {
    let events = verify_event_chain(transaction, lease_id, owner).await?;
    let mut state = LocalOutcomeState::Queued;
    for event in events
        .iter()
        .filter(|event| event.occurrence_key == occurrence_key)
    {
        state = match event.kind.as_str() {
            "admitted" => LocalOutcomeState::Queued,
            "indeterminate" => LocalOutcomeState::Indeterminate,
            "reconcile_committed" => LocalOutcomeState::Committed,
            "reconcile_rejected" => LocalOutcomeState::Rejected,
            "reconcile_still_indeterminate" => LocalOutcomeState::Indeterminate,
            "rolled_back" => LocalOutcomeState::RolledBack,
            other => return Err(corrupt(format!("unknown event kind {other:?}"))),
        };
    }
    Ok(state)
}

async fn next_event_sequence(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<u64, LocalLeaseOutboxError> {
    let value: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(event_sequence) FROM cognitive_local_events WHERE lease_id = ?",
    )
    .bind(lease_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(value
        .unwrap_or(0)
        .checked_add(1)
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("event sequence overflow".to_string()))?
        as u64)
}

async fn next_outbox_sequence(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<u64, LocalLeaseOutboxError> {
    let value: Option<i64> = sqlx::query_scalar(
        "SELECT MAX(outbox_sequence) FROM cognitive_local_outbox WHERE lease_id = ?",
    )
    .bind(lease_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(value
        .unwrap_or(0)
        .checked_add(1)
        .ok_or_else(|| LocalLeaseOutboxError::Invalid("outbox sequence overflow".to_string()))?
        as u64)
}

async fn event_head(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<Sha256Digest, LocalLeaseOutboxError> {
    let value: Option<String> = sqlx::query_scalar(
        "SELECT event_sha256 FROM cognitive_local_events
         WHERE lease_id = ? ORDER BY event_sequence DESC LIMIT 1",
    )
    .bind(lease_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    match value {
        Some(value) => Sha256Digest::parse(value).map_err(corrupt),
        None => Ok(Sha256Digest::for_bytes(GENESIS_EVENT_SHA256)),
    }
}

async fn outbox_head(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
) -> Result<Sha256Digest, LocalLeaseOutboxError> {
    let value: Option<String> = sqlx::query_scalar(
        "SELECT outbox_sha256 FROM cognitive_local_outbox
         WHERE lease_id = ? ORDER BY outbox_sequence DESC LIMIT 1",
    )
    .bind(lease_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    match value {
        Some(value) => Sha256Digest::parse(value).map_err(corrupt),
        None => Ok(Sha256Digest::for_bytes(GENESIS_OUTBOX_SHA256)),
    }
}

fn queued_receipt(
    handle: &LocalLeaseOutbox,
    event: &EventRow,
    outbox: &OutboxRow,
) -> Result<QueuedReceipt, LocalLeaseOutboxError> {
    if event.event_id != outbox.event_id
        || event.occurrence_key != outbox.occurrence_key
        || event.owner_agent_id != handle.owner_agent_id
        || event.generation != handle.generation
        || event.fencing_token != handle.fencing_token
        || outbox.owner_agent_id != handle.owner_agent_id
        || outbox.generation != handle.generation
        || outbox.fencing_token != handle.fencing_token
    {
        return Err(corrupt("event/outbox receipt fence binding mismatch"));
    }
    Ok(QueuedReceipt {
        lease_id: handle.lease_id.clone(),
        occurrence_key: event.occurrence_key.clone(),
        event_id: event.event_id.clone(),
        outbox_id: outbox.outbox_id.clone(),
        owner_agent_id: handle.owner_agent_id.clone(),
        generation: handle.generation,
        fencing_token: handle.fencing_token.clone(),
        payload_sha256: event.payload_sha256.clone(),
        external_effect: false,
    })
}

fn ensure_current_occurrence_fence(
    handle: &LocalLeaseOutbox,
    event: &EventRow,
    outbox: &OutboxRow,
) -> Result<(), LocalLeaseOutboxError> {
    if event.event_id != outbox.event_id
        || event.occurrence_key != outbox.occurrence_key
        || event.owner_agent_id != handle.owner_agent_id
        || outbox.owner_agent_id != handle.owner_agent_id
    {
        return Err(corrupt("event/outbox outcome fence binding mismatch"));
    }
    if event.generation != handle.generation
        || event.fencing_token != handle.fencing_token
        || outbox.generation != handle.generation
        || outbox.fencing_token != handle.fencing_token
    {
        return Err(LocalLeaseOutboxError::StaleFence(format!(
            "occurrence was admitted under generation {} and cannot be transitioned by generation {}",
            event.generation, handle.generation
        )));
    }
    Ok(())
}

fn ensure_current_active(
    lease: &LocalLease,
    handle: &LocalLeaseOutbox,
) -> Result<(), LocalLeaseOutboxError> {
    ensure_current_identity(lease, handle)?;
    if let Some(expires_at) = lease.lease_expires_at_unix_seconds {
        let now = u64::try_from(now_unix_seconds()?)
            .map_err(|_| LocalLeaseOutboxError::Clock("clock before Unix epoch".to_string()))?;
        if now >= expires_at {
            return Err(LocalLeaseOutboxError::StaleFence(
                "local lease has expired".to_string(),
            ));
        }
    }
    Ok(())
}

fn ensure_current_identity(
    lease: &LocalLease,
    handle: &LocalLeaseOutbox,
) -> Result<(), LocalLeaseOutboxError> {
    if lease.state != LocalLeaseState::Active {
        return Err(LocalLeaseOutboxError::StaleFence(
            "local lease is no longer active".to_string(),
        ));
    }
    ensure_current_handle_fields(lease, handle)
}

fn ensure_current_handle_fields(
    lease: &LocalLease,
    handle: &LocalLeaseOutbox,
) -> Result<(), LocalLeaseOutboxError> {
    if lease.owner_agent_id != handle.owner_agent_id {
        return Err(LocalLeaseOutboxError::StaleFence(
            "local lease owner changed".to_string(),
        ));
    }
    if lease.generation != handle.generation || lease.fencing_token != handle.fencing_token {
        return Err(LocalLeaseOutboxError::StaleFence(
            "local lease generation or fencing token changed".to_string(),
        ));
    }
    if lease.authority_epoch != handle.authority_epoch
        || lease.owner_epoch != handle.owner_epoch
        || lease.lease_expires_at_unix_seconds != handle.lease_expires_at_unix_seconds
    {
        return Err(LocalLeaseOutboxError::StaleFence(
            "local lease authority/owner/expiry binding changed".to_string(),
        ));
    }
    Ok(())
}

fn validate_lease_binding(binding: &LocalLeaseBinding) -> Result<(), LocalLeaseOutboxError> {
    LocalLeaseBinding::new(
        binding.authority_epoch,
        binding.owner_epoch,
        binding.lease_expires_at_unix_seconds,
    )
    .map(|_| ())
}

fn lease_digest(
    lease_id: &str,
    sequence: u64,
    owner: &AgentId,
    generation: u64,
    fencing_token: &str,
    state: LocalLeaseState,
    previous: &Sha256Digest,
    binding: Option<&LocalLeaseBinding>,
) -> Sha256Digest {
    let sequence_bytes = sequence.to_be_bytes();
    let generation_bytes = generation.to_be_bytes();
    let authority_bytes = binding.map(|value| value.authority_epoch.to_be_bytes());
    let owner_epoch_bytes = binding.map(|value| value.owner_epoch.to_be_bytes());
    let expiry_bytes = binding.map(|value| value.lease_expires_at_unix_seconds.to_be_bytes());
    let mut parts = vec![
        lease_id.as_bytes(),
        &sequence_bytes,
        owner.as_str().as_bytes(),
        &generation_bytes,
        fencing_token.as_bytes(),
        state.as_str().as_bytes(),
    ];
    if let (Some(authority), Some(owner_epoch), Some(expiry)) = (
        authority_bytes.as_ref(),
        owner_epoch_bytes.as_ref(),
        expiry_bytes.as_ref(),
    ) {
        parts.push(authority);
        parts.push(owner_epoch);
        parts.push(expiry);
    }
    parts.push(previous.as_str().as_bytes());
    digest_parts(
        if binding.is_some() {
            b"hepta-memory:local-lease:v2"
        } else {
            b"hepta-memory:local-lease:v1"
        },
        &parts,
    )
}

fn event_digest(
    lease_id: &str,
    sequence: u64,
    event_id: &str,
    occurrence_key: &str,
    owner: &AgentId,
    generation: u64,
    fencing_token: &str,
    kind: &str,
    payload_sha256: &Sha256Digest,
    previous: &Sha256Digest,
) -> Sha256Digest {
    digest_parts(
        b"hepta-memory:local-event:v1",
        &[
            lease_id.as_bytes(),
            &sequence.to_be_bytes(),
            event_id.as_bytes(),
            occurrence_key.as_bytes(),
            owner.as_str().as_bytes(),
            &generation.to_be_bytes(),
            fencing_token.as_bytes(),
            kind.as_bytes(),
            payload_sha256.as_str().as_bytes(),
            previous.as_str().as_bytes(),
        ],
    )
}

fn outbox_digest(
    lease_id: &str,
    sequence: u64,
    outbox_id: &str,
    event_id: &str,
    occurrence_key: &str,
    owner: &AgentId,
    generation: u64,
    fencing_token: &str,
    topic: &str,
    payload_sha256: &Sha256Digest,
    previous: &Sha256Digest,
) -> Sha256Digest {
    digest_parts(
        b"hepta-memory:local-outbox:v1",
        &[
            lease_id.as_bytes(),
            &sequence.to_be_bytes(),
            outbox_id.as_bytes(),
            event_id.as_bytes(),
            occurrence_key.as_bytes(),
            owner.as_str().as_bytes(),
            &generation.to_be_bytes(),
            fencing_token.as_bytes(),
            topic.as_bytes(),
            payload_sha256.as_str().as_bytes(),
            previous.as_str().as_bytes(),
        ],
    )
}

/// Derive the exact provider operation identity from the signed grant and the
/// immutable local admission/outbox fields.  The production writer and the
/// local claim verifier share this framing so a caller cannot substitute an
/// arbitrary digest for a different payload or topic.
pub(crate) fn dispatch_operation_digest(
    grant_digest: &Sha256Digest,
    lease_id: &str,
    occurrence_key: &str,
    topic: &str,
    payload_sha256: &Sha256Digest,
) -> Sha256Digest {
    let mut bytes = Vec::new();
    for part in [
        b"hepta:production-outbox-operation:v1".as_slice(),
        grant_digest.as_str().as_bytes(),
        lease_id.as_bytes(),
        occurrence_key.as_bytes(),
        topic.as_bytes(),
        payload_sha256.as_str().as_bytes(),
    ] {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Sha256Digest::for_bytes(&bytes)
}

/// Build a stable journal row id without allowing a maximum-length lease id
/// to overflow the SQLite `event_id`/`outbox_id` CHECK (512 bytes).  Keep the
/// historical human-readable form whenever it fits; very long lease ids use
/// a collision-resistant digest of the complete id instead of truncating it.
fn journal_row_id(kind: &str, lease_id: &str, sequence: u64) -> String {
    let readable = format!("{kind}:{lease_id}:{sequence}");
    if readable.len() <= 512 {
        readable
    } else {
        let lease_digest = Sha256Digest::for_bytes(lease_id.as_bytes());
        format!("{kind}:lease-sha256:{}:{sequence}", lease_digest.as_str())
    }
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn now_unix_seconds() -> Result<i64, LocalLeaseOutboxError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| LocalLeaseOutboxError::Clock(error.to_string()))?
        .as_secs();
    i64::try_from(seconds)
        .map_err(|_| LocalLeaseOutboxError::Clock("timestamp overflow".to_string()))
}

fn validate_generation(generation: u64) -> Result<(), LocalLeaseOutboxError> {
    if generation == 0 {
        return Err(LocalLeaseOutboxError::Invalid(
            "generation must be non-zero".to_string(),
        ));
    }
    Ok(())
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), LocalLeaseOutboxError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(LocalLeaseOutboxError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn to_i64(value: u64, label: &str) -> Result<i64, LocalLeaseOutboxError> {
    i64::try_from(value)
        .map_err(|_| LocalLeaseOutboxError::Invalid(format!("{label} overflows SQLite INTEGER")))
}

fn read_u64(row: &sqlx::sqlite::SqliteRow, column: &str) -> Result<u64, LocalLeaseOutboxError> {
    let value: i64 = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    u64::try_from(value).map_err(|_| corrupt(format!("{column} is negative")))
}

fn optional_u64(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Option<u64>, LocalLeaseOutboxError> {
    let value: Option<i64> = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    value
        .map(|value| u64::try_from(value).map_err(|_| corrupt(format!("{column} is negative"))))
        .transpose()
}

fn prior_binding(lease: &LocalLease) -> Option<LocalLeaseBinding> {
    match (
        lease.authority_epoch,
        lease.owner_epoch,
        lease.lease_expires_at_unix_seconds,
    ) {
        (Some(authority_epoch), Some(owner_epoch), Some(lease_expires_at_unix_seconds)) => {
            Some(LocalLeaseBinding {
                authority_epoch,
                owner_epoch,
                lease_expires_at_unix_seconds,
            })
        }
        _ => None,
    }
}

fn digest_from_row(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, LocalLeaseOutboxError> {
    let value: String = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    Sha256Digest::parse(value).map_err(corrupt)
}

fn parse_agent(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<AgentId, LocalLeaseOutboxError> {
    let value: String = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    AgentId::parse(value).map_err(|error| corrupt(error.to_string()))
}

async fn count_rows(
    transaction: &mut Transaction<'_, Sqlite>,
    table: &str,
    lease_id: &str,
) -> Result<u64, LocalLeaseOutboxError> {
    let query = format!("SELECT COUNT(*) FROM {table} WHERE lease_id = ?");
    let count: i64 = sqlx::query_scalar(sqlx::AssertSqlSafe(query))
        .bind(lease_id)
        .fetch_one(&mut **transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    u64::try_from(count).map_err(|_| corrupt("negative local journal row count"))
}

fn corrupt(message: impl Into<String>) -> LocalLeaseOutboxError {
    LocalLeaseOutboxError::Corrupt(message.into())
}

/// Reopen-time integrity verification invoked by `CognitiveStore::open`.
pub(crate) async fn verify_local_lease_outbox(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool
        .begin()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let lease_ids: Vec<String> = sqlx::query_scalar(
        "SELECT DISTINCT lease_id FROM cognitive_local_leases ORDER BY lease_id",
    )
    .fetch_all(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    for lease_id in lease_ids {
        load_lease_chain(&mut transaction, &lease_id, owner)
            .await
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let events = verify_event_chain(&mut transaction, &lease_id, owner)
            .await
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let outbox = verify_outbox_chain(&mut transaction, &lease_id, owner)
            .await
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        verify_event_outbox_pairing(&events, &outbox)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    }
    let orphan_event_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events AS e
         LEFT JOIN cognitive_local_leases AS l ON l.lease_id = e.lease_id
         WHERE l.lease_id IS NULL",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let orphan_outbox_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_outbox AS o
         LEFT JOIN cognitive_local_leases AS l ON l.lease_id = o.lease_id
         WHERE l.lease_id IS NULL",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if orphan_event_rows != 0 || orphan_outbox_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "local event/outbox journal contains an orphan lease reference".to_string(),
        ));
    }
    let foreign_event_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE owner_agent_id != ?")
            .bind(owner.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(crate::cognitive_store::unavailable)?;
    let foreign_outbox_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox WHERE owner_agent_id != ?")
            .bind(owner.as_str())
            .fetch_one(&mut *transaction)
            .await
            .map_err(crate::cognitive_store::unavailable)?;
    if foreign_event_rows != 0 || foreign_outbox_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "local event/outbox journal contains a foreign owner".to_string(),
        ));
    }
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}
