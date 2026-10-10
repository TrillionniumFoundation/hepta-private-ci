//! Stable Agent-local logical-turn registry for local qualification.
//!
//! A logical turn is a durable identity which may have more than one physical
//! attempt.  This module only records local provenance and a one-winner CAS;
//! it does not register a scheduler, call Agentd, invoke a provider, write the
//! KG, or grant production authority.  Every mutating operation is performed
//! under one SQLite `BEGIN IMMEDIATE` transaction and verifies the complete
//! local lease and registry chains before appending a row.
//!
//! Takeover is intentionally a local qualification heuristic: an expired,
//! unadmitted attempt may be superseded only while the locked store observes
//! its exact active lease head and zero evidence.  This is not an OS/process
//! death proof and must not be promoted to a production ownership authority.

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
use crate::LocalLease;
use crate::LocalLeaseBinding;
use crate::LocalLeaseOutboxError;
use crate::LocalLeaseState;
use crate::framing::frame_part;
use crate::local_lease_outbox::append_lease;
use crate::local_lease_outbox::load_lease_chain;

/// Schema version for the local qualification registry contract.
pub const LOGICAL_TURN_REGISTRY_SCHEMA_VERSION: u32 = 1;
/// This registry is deliberately narrower than a production turn authority.
pub const LOGICAL_TURN_REGISTRY_NAMESPACE: &str = "local_qualification_only";
pub const LOGICAL_TURN_REGISTRY_EXTERNAL_EFFECTS: bool = false;
pub const LOGICAL_TURN_REGISTRY_KG_WRITE_AUTHORITY: bool = false;
pub const LOGICAL_TURN_REGISTRY_PRODUCTION_CALLER: bool = false;

const MAX_TEXT_BYTES: usize = 512;
const MAX_REGISTRY_ROWS: usize = 16_384;
const IDENTITY_DOMAIN: &[u8] = b"hepta-memory:logical-turn-identity:v1";
const ATTEMPT_DOMAIN: &[u8] = b"hepta-memory:logical-turn-attempt:v1";
const GENESIS_ATTEMPT: &[u8] = b"hepta-memory:logical-turn-attempt:genesis:v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum IdentityDisposition {
    Inserted,
    Existing,
    Conflict,
}

#[derive(Debug, Error)]
pub enum LogicalTurnRegistryError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Lease(#[from] LocalLeaseOutboxError),
    #[error("invalid logical-turn registry input: {0}")]
    Invalid(String),
    #[error("logical-turn registry is corrupt: {0}")]
    Corrupt(String),
    #[error("logical-turn registry transaction failed: {0}")]
    Transaction(String),
    #[error("logical-turn registry clock failed: {0}")]
    Clock(String),
    #[error("logical-turn registry serialization failed: {0}")]
    Serialization(String),
}

/// Immutable request describing the stable logical identity of a turn.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalTurnRequest {
    pub logical_turn_id: String,
    pub scope_key: String,
    pub logical_binding_sha256: Sha256Digest,
}

impl LogicalTurnRequest {
    pub fn new(
        logical_turn_id: impl Into<String>,
        scope_key: impl Into<String>,
        logical_binding_sha256: Sha256Digest,
    ) -> Result<Self, LogicalTurnRegistryError> {
        let request = Self {
            logical_turn_id: logical_turn_id.into(),
            scope_key: scope_key.into(),
            logical_binding_sha256,
        };
        request.validate()?;
        Ok(request)
    }

    pub fn validate(&self) -> Result<(), LogicalTurnRegistryError> {
        validate_text(&self.logical_turn_id, "logical turn id")?;
        validate_text(&self.scope_key, "logical scope key")?;
        validate_digest(&self.logical_binding_sha256, "logical binding")
    }
}

/// Caller-owned physical attempt and exact local lease witness.
///
/// The registry never derives a lease/fence from a logical identity.  It only
/// accepts an attempt after the supplied tuple is found in the Agent-local
/// append-only lease journal (or appends generation one in the same locked
/// transaction for a first reservation).
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalTurnAttemptRequest {
    pub attempt_id: String,
    pub lease_id: String,
    pub journal_id: String,
    pub trajectory_id: String,
    pub occurrence_key: String,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub lease_expires_at_unix_seconds: u64,
}

impl LogicalTurnAttemptRequest {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        attempt_id: impl Into<String>,
        lease_id: impl Into<String>,
        journal_id: impl Into<String>,
        trajectory_id: impl Into<String>,
        occurrence_key: impl Into<String>,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
    ) -> Result<Self, LogicalTurnRegistryError> {
        let request = Self {
            attempt_id: attempt_id.into(),
            lease_id: lease_id.into(),
            journal_id: journal_id.into(),
            trajectory_id: trajectory_id.into(),
            occurrence_key: occurrence_key.into(),
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token: fencing_token.into(),
            lease_expires_at_unix_seconds,
        };
        request.validate()?;
        Ok(request)
    }

    pub fn validate(&self) -> Result<(), LogicalTurnRegistryError> {
        validate_text(&self.attempt_id, "attempt id")?;
        validate_text(&self.lease_id, "lease id")?;
        validate_text(&self.journal_id, "journal id")?;
        validate_text(&self.trajectory_id, "trajectory id")?;
        validate_text(&self.occurrence_key, "occurrence key")?;
        validate_text_max(&self.fencing_token, "fencing token", /*max_bytes*/ 256)?;
        if self.authority_epoch == 0 || self.owner_epoch == 0 {
            return Err(invalid("authority and owner epochs must be non-zero"));
        }
        if self.generation == 0 {
            return Err(invalid("generation must be non-zero"));
        }
        if self.lease_expires_at_unix_seconds == 0 {
            return Err(invalid("lease expiry must be non-zero"));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LogicalTurnAttemptTransition {
    Active,
    Superseded,
}

impl LogicalTurnAttemptTransition {
    fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Superseded => "superseded",
        }
    }

    fn parse(value: &str) -> Result<Self, LogicalTurnRegistryError> {
        match value {
            "active" => Ok(Self::Active),
            "superseded" => Ok(Self::Superseded),
            other => Err(corrupt(format!(
                "unknown logical-turn transition {other:?}"
            ))),
        }
    }
}

/// Verified immutable registry row.  A superseded row is a transition copy
/// of the old attempt; the following active row names the winner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalTurnAttempt {
    pub owner_agent_id: AgentId,
    pub logical_turn_id: String,
    pub registry_sequence: u64,
    pub attempt_no: u64,
    pub attempt_id: String,
    pub transition: LogicalTurnAttemptTransition,
    pub superseded_by_attempt_id: Option<String>,
    pub logical_binding_sha256: Sha256Digest,
    pub lease_id: String,
    pub lease_sequence: u64,
    pub lease_head_sha256: Sha256Digest,
    pub journal_id: String,
    pub trajectory_id: String,
    pub occurrence_key: String,
    pub generation: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub fencing_token: String,
    pub lease_expires_at_unix_seconds: u64,
    pub previous_sha256: Sha256Digest,
    pub attempt_sha256: Sha256Digest,
    pub recorded_at_unix_seconds: i64,
}

impl LogicalTurnAttempt {
    pub fn is_active(&self) -> bool {
        self.transition == LogicalTurnAttemptTransition::Active
    }

    pub fn is_expired_at(&self, now_unix_seconds: u64) -> bool {
        self.lease_expires_at_unix_seconds <= now_unix_seconds
    }

    fn matches_request(
        &self,
        request: &LogicalTurnRequest,
        attempt: &LogicalTurnAttemptRequest,
    ) -> bool {
        // Expiry is a persisted lease binding, but it is not a physical
        // identity.  A same-process replay may cross a wall-clock second
        // and present a newly computed TTL; the durable head below is the
        // authoritative expiry witness.
        self.logical_turn_id == request.logical_turn_id
            && self.logical_binding_sha256 == request.logical_binding_sha256
            && self.attempt_id == attempt.attempt_id
            && self.lease_id == attempt.lease_id
            && self.journal_id == attempt.journal_id
            && self.trajectory_id == attempt.trajectory_id
            && self.occurrence_key == attempt.occurrence_key
            && self.authority_epoch == attempt.authority_epoch
            && self.owner_epoch == attempt.owner_epoch
            && self.generation == attempt.generation
            && self.fencing_token == attempt.fencing_token
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LogicalTurnEvidence {
    pub event_rows: u64,
    pub outbox_rows: u64,
    pub compact_rows: u64,
    pub trajectory_rows: u64,
}

/// Read-only classification of one stable logical-turn registry head.
///
/// The classification is a snapshot witness only.  In particular,
/// `ExpiredZeroEvidence` does not authorize takeover, release, or renewal;
/// callers must still use the serialized reservation CAS with a fresh
/// attempt-scoped physical identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LogicalTurnInspectionDisposition {
    Missing,
    Conflict,
    Active,
    ExpiredZeroEvidence,
    ExpiredWithEvidence,
    TerminalPhysicalLease,
}

/// Read-only snapshot of a logical-turn identity, its verified attempt head,
/// current physical lease head, and any local evidence bound to that attempt.
/// No raw prompt or provider payload is retained here; the request contains
/// only the caller-supplied scope and digest binding.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LogicalTurnInspection {
    pub request: LogicalTurnRequest,
    pub identity_sha256: Sha256Digest,
    pub stored_scope_key: Option<String>,
    pub stored_binding_sha256: Option<Sha256Digest>,
    pub head: Option<LogicalTurnAttempt>,
    pub lease_head: Option<LocalLease>,
    /// Conservative counts of rows bound to the observed attempt.  They are
    /// diagnostic evidence only; a non-empty count never authorizes a
    /// takeover, and a later CAS must recheck the complete chains.
    pub evidence: LogicalTurnEvidence,
    pub disposition: LogicalTurnInspectionDisposition,
    pub observed_at_unix_seconds: u64,
}

impl LogicalTurnEvidence {
    pub fn is_empty(&self) -> bool {
        self.event_rows == 0
            && self.outbox_rows == 0
            && self.compact_rows == 0
            && self.trajectory_rows == 0
    }

    pub fn total_rows(&self) -> u64 {
        self.event_rows
            .saturating_add(self.outbox_rows)
            .saturating_add(self.compact_rows)
            .saturating_add(self.trajectory_rows)
    }
}

/// Result of one serialized reservation attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(clippy::large_enum_variant)]
pub enum LogicalTurnReservation {
    Acquired {
        attempt: LogicalTurnAttempt,
    },
    Replayed {
        attempt: LogicalTurnAttempt,
    },
    Takeover {
        superseded: LogicalTurnAttempt,
        attempt: LogicalTurnAttempt,
    },
    ExistingInFlight {
        attempt: LogicalTurnAttempt,
    },
    Conflict {
        reason: String,
    },
    BlockedByEvidence {
        attempt: LogicalTurnAttempt,
        evidence: LogicalTurnEvidence,
    },
}

impl LogicalTurnReservation {
    /// Return the current winner when the result carries one.
    pub fn attempt(&self) -> Option<&LogicalTurnAttempt> {
        match self {
            Self::Acquired { attempt }
            | Self::Replayed { attempt }
            | Self::ExistingInFlight { attempt }
            | Self::BlockedByEvidence { attempt, .. }
            | Self::Takeover { attempt, .. } => Some(attempt),
            Self::Conflict { .. } => None,
        }
    }

    pub fn is_winner(&self) -> bool {
        matches!(self, Self::Acquired { .. } | Self::Takeover { .. })
    }
}

impl CognitiveStore {
    /// Reserve one stable logical turn or return the exact durable winner.
    ///
    /// The request is local-qualification-only.  The first call appends a
    /// generation-one bound lease and an `active` registry row atomically.
    /// An exact replay returns `Replayed`; a live different attempt returns
    /// `ExistingInFlight`.  An expired attempt can be superseded only when no
    /// local event/outbox/compact/trajectory evidence exists for it.  The
    /// old `superseded` transition, old-lease rollback marker, and new
    /// `active` winner are appended in the same transaction, so concurrent
    /// callers cannot both win and stale handles lose their lease-head fence.
    pub async fn reserve_or_replay_logical_turn(
        &self,
        request: LogicalTurnRequest,
        attempt: LogicalTurnAttemptRequest,
    ) -> Result<LogicalTurnReservation, LogicalTurnRegistryError> {
        request.validate()?;
        attempt.validate()?;

        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let identity_sha256 = logical_identity_digest(
            self.owner_agent_id(),
            &request.logical_turn_id,
            &request.scope_key,
            &request.logical_binding_sha256,
        );
        let identity_disposition = ensure_identity(
            &mut transaction,
            self.owner_agent_id(),
            &request,
            &identity_sha256,
        )
        .await?;
        if identity_disposition == IdentityDisposition::Conflict {
            return commit_reservation(
                transaction,
                LogicalTurnReservation::Conflict {
                    reason: "logical identity differs from the durable registry row".to_string(),
                },
            )
            .await;
        }
        let rows = load_attempt_chain(
            &mut transaction,
            self.owner_agent_id(),
            &request.logical_turn_id,
            &request.logical_binding_sha256,
        )
        .await?;
        if rows.is_empty() && identity_disposition == IdentityDisposition::Existing {
            return Err(corrupt(
                "durable logical-turn identity has no attempt chain",
            ));
        }
        let head = rows.last().cloned();
        let now = now_unix_seconds()?;

        if let Some(head) = head.as_ref() {
            if head.matches_request(&request, &attempt) {
                let mut persisted_attempt = attempt.clone();
                persisted_attempt.lease_expires_at_unix_seconds =
                    head.lease_expires_at_unix_seconds;
                let lease = verify_or_load_requested_lease(
                    &mut transaction,
                    self,
                    &persisted_attempt,
                    /*allow_expired*/ false,
                )
                .await?;
                if lease.is_none() {
                    return commit_reservation(
                        transaction,
                        LogicalTurnReservation::Conflict {
                            reason: "exact logical attempt is missing its local lease witness"
                                .to_string(),
                        },
                    )
                    .await;
                }
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Replayed {
                        attempt: head.clone(),
                    },
                )
                .await;
            }

            if head.logical_binding_sha256 != request.logical_binding_sha256 {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "logical binding differs from the durable identity".to_string(),
                    },
                )
                .await;
            }

            // The physical lease may have reached a terminal state after the
            // observation writer completed, while the immutable registry head
            // intentionally remains an `active` identity row.  Treat that
            // head as a durable terminal conflict before the TTL/live branch;
            // otherwise a future caller could misclassify it as in-flight or
            // attempt a takeover, and a clean reopen would reject the store.
            let (latest_lease, _) =
                load_lease_chain(&mut transaction, &head.lease_id, self.owner_agent_id()).await?;
            let Some(latest_lease) = latest_lease else {
                return Err(corrupt("logical attempt lease journal is missing"));
            };
            if latest_lease.state != LocalLeaseState::Active {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "logical turn already has a terminal physical lease".to_string(),
                    },
                )
                .await;
            }

            if !head.is_expired_at(now) {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::ExistingInFlight {
                        attempt: head.clone(),
                    },
                )
                .await;
            }

            verify_attempt_lease_witness(&mut transaction, head).await?;

            let evidence = evidence_for_attempt(&mut transaction, head).await?;
            if !evidence.is_empty() {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::BlockedByEvidence {
                        attempt: head.clone(),
                        evidence,
                    },
                )
                .await;
            }
            if attempt.lease_id == head.lease_id {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "takeover must present a distinct attempt-scoped lease".to_string(),
                    },
                )
                .await;
            }
            if attempt.attempt_id == head.attempt_id
                || attempt.journal_id == head.journal_id
                || attempt.trajectory_id == head.trajectory_id
                || attempt.occurrence_key == head.occurrence_key
            {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "takeover must present fresh attempt-scoped journal, trajectory, and occurrence identities".to_string(),
                    },
                )
                .await;
            }
            if attempt.generation != 1 {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "a takeover attempt must start a fresh lease generation one"
                            .to_string(),
                    },
                )
                .await;
            }
            if attempt.authority_epoch != head.authority_epoch {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason:
                            "takeover authority epoch must match the historical local authority"
                                .to_string(),
                    },
                )
                .await;
            }
            if attempt.owner_epoch < head.owner_epoch {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "takeover owner epoch must not regress below the expired attempt"
                            .to_string(),
                    },
                )
                .await;
            }
            // Equality is intentional: a same-generation retry may have no
            // stronger lifecycle epoch to present.  It is safe only because
            // the locked path above has already proved expiry, zero local
            // evidence, and a fresh physical identity; lower epochs remain
            // fenced as stale callers.
            if attempt.lease_expires_at_unix_seconds <= now {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "takeover lease must have a future expiry".to_string(),
                    },
                )
                .await;
            }
            if physical_identity_is_reused(&mut transaction, &attempt).await? {
                return commit_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "takeover attempt-scoped identity is already bound elsewhere"
                            .to_string(),
                    },
                )
                .await;
            }
            let _lease = ensure_requested_lease(&mut transaction, self, &attempt).await?;
            let superseded = append_attempt(
                &mut transaction,
                self.owner_agent_id(),
                &request,
                &attempt_from_existing_for_supersede(head),
                head.registry_sequence + 1,
                head.attempt_no,
                LogicalTurnAttemptTransition::Superseded,
                Some(&attempt.attempt_id),
                &head.attempt_sha256,
                now_unix_i64()?,
            )
            .await?;
            // Retire the expired physical lease only after its immutable
            // superseded registry witness has been appended.  The old
            // attempt remains readable as history, while stale handles now
            // fail the ordinary lease-head fence instead of lingering as an
            // apparently active row.
            let (old_lease, _) =
                load_lease_chain(&mut transaction, &head.lease_id, self.owner_agent_id()).await?;
            let old_lease = old_lease.ok_or_else(|| {
                corrupt("expired logical attempt lease disappeared during takeover")
            })?;
            let old_binding = LocalLeaseBinding::new(
                head.authority_epoch,
                head.owner_epoch,
                head.lease_expires_at_unix_seconds,
            )?;
            append_lease(
                &mut transaction,
                &head.lease_id,
                self.owner_agent_id(),
                head.generation,
                &head.fencing_token,
                LocalLeaseState::RolledBack,
                Some(&old_lease),
                Some(&old_binding),
            )
            .await?;
            let active = append_attempt(
                &mut transaction,
                self.owner_agent_id(),
                &request,
                &attempt,
                head.registry_sequence + 2,
                head.attempt_no + 1,
                LogicalTurnAttemptTransition::Active,
                /*superseded_by_attempt_id*/ None,
                &superseded.attempt_sha256,
                now_unix_i64()?,
            )
            .await?;
            return commit_reservation(
                transaction,
                LogicalTurnReservation::Takeover {
                    superseded,
                    attempt: active,
                },
            )
            .await;
        }

        if physical_identity_is_reused(&mut transaction, &attempt).await? {
            if identity_disposition == IdentityDisposition::Inserted {
                // Do not commit an orphan immutable identity when the first
                // physical reservation is rejected by a legacy/cross-logical
                // collision.  Roll back the whole transaction, then preserve
                // the typed conflict result for the caller.
                return rollback_reservation(
                    transaction,
                    LogicalTurnReservation::Conflict {
                        reason: "attempt-scoped identity is already bound elsewhere".to_string(),
                    },
                )
                .await;
            }
            return commit_reservation(
                transaction,
                LogicalTurnReservation::Conflict {
                    reason: "attempt-scoped identity is already bound elsewhere".to_string(),
                },
            )
            .await;
        }
        let _lease = ensure_requested_lease(&mut transaction, self, &attempt).await?;
        let active = append_attempt(
            &mut transaction,
            self.owner_agent_id(),
            &request,
            &attempt,
            /*registry_sequence*/ 1,
            /*attempt_no*/ 1,
            LogicalTurnAttemptTransition::Active,
            /*superseded_by_attempt_id*/ None,
            &genesis_attempt_digest(),
            now_unix_i64()?,
        )
        .await?;
        commit_reservation(
            transaction,
            LogicalTurnReservation::Acquired { attempt: active },
        )
        .await
    }

    /// Inspect one stable logical turn without inserting or changing any
    /// registry, lease, event, outbox, compact, or H7 row.  The read
    /// transaction verifies the immutable identity, complete attempt chain,
    /// historical lease witnesses, current lease head, and conservative
    /// counts of evidence rows bound to the attempt.
    /// The result is a snapshot and may become stale immediately; callers
    /// must not treat it as takeover or dispatch authority.
    pub async fn inspect_logical_turn(
        &self,
        request: LogicalTurnRequest,
    ) -> Result<LogicalTurnInspection, LogicalTurnRegistryError> {
        request.validate()?;
        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let identity_sha256 = logical_identity_digest(
            self.owner_agent_id(),
            &request.logical_turn_id,
            &request.scope_key,
            &request.logical_binding_sha256,
        );
        let identity = sqlx::query(
            "SELECT scope_key, logical_binding_sha256, identity_sha256
             FROM cognitive_logical_turns
             WHERE owner_agent_id = ? AND logical_turn_id = ?",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(&request.logical_turn_id)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(crate::cognitive_store::unavailable)?;
        let observed_at_unix_seconds = now_unix_seconds()?;
        let Some(identity) = identity else {
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LogicalTurnInspection {
                request,
                identity_sha256,
                stored_scope_key: None,
                stored_binding_sha256: None,
                head: None,
                lease_head: None,
                evidence: empty_logical_turn_evidence(),
                disposition: LogicalTurnInspectionDisposition::Missing,
                observed_at_unix_seconds,
            });
        };
        let stored_scope_key: String = identity
            .try_get("scope_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let stored_binding_text: String = identity
            .try_get("logical_binding_sha256")
            .map_err(crate::cognitive_store::unavailable)?;
        let stored_binding_sha256 = Sha256Digest::parse(&stored_binding_text)
            .map_err(|error| corrupt(format!("invalid stored logical binding: {error}")))?;
        let stored_identity_text: String = identity
            .try_get("identity_sha256")
            .map_err(crate::cognitive_store::unavailable)?;
        let stored_identity_sha256 = Sha256Digest::parse(&stored_identity_text)
            .map_err(|error| corrupt(format!("invalid stored logical identity: {error}")))?;
        let expected_stored_identity = logical_identity_digest(
            self.owner_agent_id(),
            &request.logical_turn_id,
            &stored_scope_key,
            &stored_binding_sha256,
        );
        if stored_identity_sha256 != expected_stored_identity {
            return Err(corrupt(
                "logical identity digest does not match immutable fields",
            ));
        }
        if stored_scope_key != request.scope_key
            || stored_binding_sha256 != request.logical_binding_sha256
            || stored_identity_sha256 != identity_sha256
        {
            transaction
                .commit()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(LogicalTurnInspection {
                request,
                identity_sha256,
                stored_scope_key: Some(stored_scope_key),
                stored_binding_sha256: Some(stored_binding_sha256),
                head: None,
                lease_head: None,
                evidence: empty_logical_turn_evidence(),
                disposition: LogicalTurnInspectionDisposition::Conflict,
                observed_at_unix_seconds,
            });
        }

        let attempts = load_attempt_chain(
            &mut transaction,
            self.owner_agent_id(),
            &request.logical_turn_id,
            &request.logical_binding_sha256,
        )
        .await?;
        let head = attempts
            .last()
            .cloned()
            .ok_or_else(|| corrupt("durable logical-turn identity has no attempt chain"))?;
        let (lease_head, _) =
            load_lease_chain(&mut transaction, &head.lease_id, self.owner_agent_id()).await?;
        let lease_head =
            lease_head.ok_or_else(|| corrupt("logical-turn registry head has no lease journal"))?;
        // A lease id may legally receive a later generation after a normal
        // terminal transition.  That successor must not be mistaken for the
        // registry head's historical physical witness; otherwise a read-only
        // inspection could report a false Active/Expired state.  Active heads
        // therefore require the exact sequence+digest CAS witness as well as
        // the chain validation performed above.
        if lease_head.state == LocalLeaseState::Active {
            verify_attempt_lease_witness(&mut transaction, &head).await?;
        } else if lease_head.generation != head.generation
            || lease_head.fencing_token != head.fencing_token
            || lease_head.authority_epoch != Some(head.authority_epoch)
            || lease_head.owner_epoch != Some(head.owner_epoch)
            || lease_head.lease_expires_at_unix_seconds != Some(head.lease_expires_at_unix_seconds)
        {
            return Err(corrupt(
                "logical-turn registry head lease identity drifted before terminal inspection",
            ));
        }
        let evidence = evidence_for_attempt(&mut transaction, &head).await?;
        let disposition = match lease_head.state {
            LocalLeaseState::Released | LocalLeaseState::RolledBack => {
                LogicalTurnInspectionDisposition::TerminalPhysicalLease
            }
            LocalLeaseState::Active => {
                let expired = head.is_expired_at(observed_at_unix_seconds);
                if !expired {
                    LogicalTurnInspectionDisposition::Active
                } else if evidence.is_empty() {
                    LogicalTurnInspectionDisposition::ExpiredZeroEvidence
                } else {
                    LogicalTurnInspectionDisposition::ExpiredWithEvidence
                }
            }
        };
        transaction
            .commit()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(LogicalTurnInspection {
            request,
            identity_sha256,
            stored_scope_key: Some(stored_scope_key),
            stored_binding_sha256: Some(stored_binding_sha256),
            head: Some(head),
            lease_head: Some(lease_head),
            evidence,
            disposition,
            observed_at_unix_seconds,
        })
    }
}

fn empty_logical_turn_evidence() -> LogicalTurnEvidence {
    LogicalTurnEvidence {
        event_rows: 0,
        outbox_rows: 0,
        compact_rows: 0,
        trajectory_rows: 0,
    }
}

async fn commit_reservation(
    transaction: Transaction<'_, Sqlite>,
    reservation: LogicalTurnReservation,
) -> Result<LogicalTurnReservation, LogicalTurnRegistryError> {
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(reservation)
}

async fn rollback_reservation(
    transaction: Transaction<'_, Sqlite>,
    reservation: LogicalTurnReservation,
) -> Result<LogicalTurnReservation, LogicalTurnRegistryError> {
    transaction
        .rollback()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(reservation)
}

async fn ensure_identity(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    request: &LogicalTurnRequest,
    identity_sha256: &Sha256Digest,
) -> Result<IdentityDisposition, LogicalTurnRegistryError> {
    let existing = sqlx::query(
        "SELECT scope_key, logical_binding_sha256, identity_sha256
         FROM cognitive_logical_turns
         WHERE owner_agent_id = ? AND logical_turn_id = ?",
    )
    .bind(owner.as_str())
    .bind(&request.logical_turn_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if let Some(row) = existing {
        let scope_key: String = row
            .try_get("scope_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let logical_binding_sha256: String = row
            .try_get("logical_binding_sha256")
            .map_err(crate::cognitive_store::unavailable)?;
        let stored_identity_sha256: String = row
            .try_get("identity_sha256")
            .map_err(crate::cognitive_store::unavailable)?;
        if scope_key != request.scope_key
            || logical_binding_sha256 != request.logical_binding_sha256.as_str()
            || stored_identity_sha256 != identity_sha256.as_str()
        {
            return Ok(IdentityDisposition::Conflict);
        }
        // Recompute the identity digest from the immutable row values even on
        // an exact replay; a self-consistent but incorrect stored digest is
        // corruption, not a replay disposition.
        let expected = logical_identity_digest(
            owner,
            &request.logical_turn_id,
            &scope_key,
            &request.logical_binding_sha256,
        );
        if stored_identity_sha256 != expected.as_str() {
            return Err(corrupt(
                "logical identity digest does not match immutable fields",
            ));
        }
        return Ok(IdentityDisposition::Existing);
    }
    sqlx::query(
        "INSERT INTO cognitive_logical_turns (
            owner_agent_id, logical_turn_id, scope_key, logical_binding_sha256,
            identity_sha256, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?)",
    )
    .bind(owner.as_str())
    .bind(&request.logical_turn_id)
    .bind(&request.scope_key)
    .bind(request.logical_binding_sha256.as_str())
    .bind(identity_sha256.as_str())
    .bind(now_unix_i64()?)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(IdentityDisposition::Inserted)
}

async fn ensure_requested_lease(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    request: &LogicalTurnAttemptRequest,
) -> Result<LocalLease, LogicalTurnRegistryError> {
    let binding = LocalLeaseBinding::new(
        request.authority_epoch,
        request.owner_epoch,
        request.lease_expires_at_unix_seconds,
    )?;
    let (latest, _) =
        load_lease_chain(transaction, &request.lease_id, store.owner_agent_id()).await?;
    if let Some(previous) = latest.as_ref() {
        if previous.state == LocalLeaseState::Active {
            if previous.generation == request.generation
                && previous.fencing_token == request.fencing_token
                && previous.authority_epoch == Some(request.authority_epoch)
                && previous.owner_epoch == Some(request.owner_epoch)
                && previous.lease_expires_at_unix_seconds
                    == Some(request.lease_expires_at_unix_seconds)
            {
                let now = now_unix_seconds()?;
                if previous
                    .lease_expires_at_unix_seconds
                    .is_some_and(|expiry| expiry <= now)
                {
                    return Err(LogicalTurnRegistryError::Invalid(
                        "requested lease fence has already expired".to_string(),
                    ));
                }
                return Ok(previous.clone());
            }
            return Err(LogicalTurnRegistryError::Invalid(
                "requested lease id already has a different active fence".to_string(),
            ));
        }
        if request.generation != previous.generation.saturating_add(1) {
            return Err(LogicalTurnRegistryError::Invalid(format!(
                "lease generation must advance from {} to {}",
                previous.generation,
                previous.generation.saturating_add(1)
            )));
        }
        return Ok(append_lease(
            transaction,
            &request.lease_id,
            store.owner_agent_id(),
            request.generation,
            &request.fencing_token,
            LocalLeaseState::Active,
            Some(previous),
            Some(&binding),
        )
        .await?);
    }
    if request.generation != 1 {
        return Err(LogicalTurnRegistryError::Invalid(
            "first local lease generation must be one".to_string(),
        ));
    }
    Ok(append_lease(
        transaction,
        &request.lease_id,
        store.owner_agent_id(),
        request.generation,
        &request.fencing_token,
        LocalLeaseState::Active,
        /*previous*/ None,
        Some(&binding),
    )
    .await?)
}

/// Reject a caller that tries to reuse any physical attempt identity already
/// present in this Agent-local database.  The registry API is public to local
/// qualification callers, so the Agentd hash construction is not the only
/// boundary that must prevent cross-logical aliasing.  Legacy rows are also
/// included: an upgrade must not silently bind a new logical turn to an old
/// lease, compact journal, H7 trajectory, or admitted occurrence.
async fn physical_identity_is_reused(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt: &LogicalTurnAttemptRequest,
) -> Result<bool, LogicalTurnRegistryError> {
    let registry_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_logical_turn_attempts
         WHERE attempt_id = ? OR lease_id = ? OR journal_id = ?
            OR trajectory_id = ? OR occurrence_key = ?",
    )
    .bind(&attempt.attempt_id)
    .bind(&attempt.lease_id)
    .bind(&attempt.journal_id)
    .bind(&attempt.trajectory_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if registry_rows > 0 {
        return Ok(true);
    }

    let lease_rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_leases WHERE lease_id = ?")
            .bind(&attempt.lease_id)
            .fetch_one(&mut **transaction)
            .await
            .map_err(crate::cognitive_store::unavailable)?;
    if lease_rows > 0 {
        return Ok(true);
    }

    let event_or_outbox_rows: i64 = sqlx::query_scalar(
        "SELECT (
            (SELECT COUNT(*) FROM cognitive_local_events
             WHERE lease_id = ? OR occurrence_key = ?) +
            (SELECT COUNT(*) FROM cognitive_local_outbox
             WHERE lease_id = ? OR occurrence_key = ?)
        )",
    )
    .bind(&attempt.lease_id)
    .bind(&attempt.occurrence_key)
    .bind(&attempt.lease_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if event_or_outbox_rows > 0 {
        return Ok(true);
    }

    let compact_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_compact_events
         WHERE journal_id = ? OR lease_id = ?",
    )
    .bind(&attempt.journal_id)
    .bind(&attempt.lease_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if compact_rows > 0 {
        return Ok(true);
    }

    let trajectory_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_h7_trajectory_events
         WHERE lease_id = ? OR trajectory_id = ? OR occurrence_key = ?",
    )
    .bind(&attempt.lease_id)
    .bind(&attempt.trajectory_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(trajectory_rows > 0)
}

async fn verify_or_load_requested_lease(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &CognitiveStore,
    request: &LogicalTurnAttemptRequest,
    allow_expired: bool,
) -> Result<Option<LocalLease>, LogicalTurnRegistryError> {
    let (latest, _) =
        load_lease_chain(transaction, &request.lease_id, store.owner_agent_id()).await?;
    let Some(lease) = latest else {
        return Ok(None);
    };
    if lease.state != LocalLeaseState::Active
        || lease.generation != request.generation
        || lease.fencing_token != request.fencing_token
        || lease.authority_epoch != Some(request.authority_epoch)
        || lease.owner_epoch != Some(request.owner_epoch)
        || lease.lease_expires_at_unix_seconds != Some(request.lease_expires_at_unix_seconds)
    {
        return Ok(None);
    }
    if !allow_expired && lease.lease_expires_at_unix_seconds.unwrap_or(0) <= now_unix_seconds()? {
        return Ok(None);
    }
    Ok(Some(lease))
}

/// Verify that an attempt still points at the exact historical lease row it
/// recorded.  This is deliberately independent of the current lease head:
/// superseded attempts may have a terminal row appended after their registry
/// transition, but the immutable row they recorded must remain exact.
async fn verify_historical_lease_witness(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt: &LogicalTurnAttempt,
) -> Result<LocalLeaseState, LogicalTurnRegistryError> {
    // Loading the complete chain validates its owner, state transitions and
    // digest links before the exact historical row is inspected.
    let (_, _) = load_lease_chain(transaction, &attempt.lease_id, &attempt.owner_agent_id).await?;
    let row = sqlx::query(
        "SELECT owner_agent_id, generation, fencing_token, state,
                authority_epoch, owner_epoch, lease_expires_at_unix_seconds,
                lease_sha256
         FROM cognitive_local_leases
         WHERE lease_id = ? AND lease_sequence = ?",
    )
    .bind(&attempt.lease_id)
    .bind(to_i64(attempt.lease_sequence, "lease sequence")?)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?
    .ok_or_else(|| corrupt("logical attempt historical lease row is missing"))?;
    let owner: String = row
        .try_get("owner_agent_id")
        .map_err(crate::cognitive_store::unavailable)?;
    let generation: i64 = row
        .try_get("generation")
        .map_err(crate::cognitive_store::unavailable)?;
    let fencing_token: String = row
        .try_get("fencing_token")
        .map_err(crate::cognitive_store::unavailable)?;
    let state: String = row
        .try_get("state")
        .map_err(crate::cognitive_store::unavailable)?;
    let authority_epoch: Option<i64> = row
        .try_get("authority_epoch")
        .map_err(crate::cognitive_store::unavailable)?;
    let owner_epoch: Option<i64> = row
        .try_get("owner_epoch")
        .map_err(crate::cognitive_store::unavailable)?;
    let expiry: Option<i64> = row
        .try_get("lease_expires_at_unix_seconds")
        .map_err(crate::cognitive_store::unavailable)?;
    let lease_sha256: String = row
        .try_get("lease_sha256")
        .map_err(crate::cognitive_store::unavailable)?;
    if owner != attempt.owner_agent_id.as_str()
        || generation != to_i64(attempt.generation, "generation")?
        || fencing_token != attempt.fencing_token
        || authority_epoch != Some(to_i64(attempt.authority_epoch, "authority epoch")?)
        || owner_epoch != Some(to_i64(attempt.owner_epoch, "owner epoch")?)
        || expiry
            != Some(to_i64(
                attempt.lease_expires_at_unix_seconds,
                "lease expiry",
            )?)
        || lease_sha256 != attempt.lease_head_sha256.as_str()
    {
        return Err(corrupt("logical attempt lease row does not match witness"));
    }
    let state = match state.as_str() {
        "active" => LocalLeaseState::Active,
        "released" => LocalLeaseState::Released,
        "rolled_back" => LocalLeaseState::RolledBack,
        other => return Err(corrupt(format!("unknown historical lease state {other:?}"))),
    };
    Ok(state)
}

/// Verify the current head used by takeover CAS.  The expired head must still
/// be the exact active row observed by the registry; a release/rotation wins
/// the race and is rejected rather than being treated as an implicit lease
/// takeover.
async fn verify_attempt_lease_witness(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt: &LogicalTurnAttempt,
) -> Result<(), LogicalTurnRegistryError> {
    verify_historical_lease_witness(transaction, attempt).await?;
    let (latest, _) =
        load_lease_chain(transaction, &attempt.lease_id, &attempt.owner_agent_id).await?;
    let Some(latest) = latest else {
        return Err(corrupt("logical attempt lease journal is missing"));
    };
    if latest.state != LocalLeaseState::Active
        || latest.lease_sequence != attempt.lease_sequence
        || latest.lease_sha256 != attempt.lease_head_sha256
    {
        return Err(corrupt(
            "logical attempt lease witness is no longer the exact active head",
        ));
    }
    Ok(())
}

fn attempt_from_existing_for_supersede(attempt: &LogicalTurnAttempt) -> LogicalTurnAttemptRequest {
    LogicalTurnAttemptRequest {
        attempt_id: attempt.attempt_id.clone(),
        lease_id: attempt.lease_id.clone(),
        journal_id: attempt.journal_id.clone(),
        trajectory_id: attempt.trajectory_id.clone(),
        occurrence_key: attempt.occurrence_key.clone(),
        authority_epoch: attempt.authority_epoch,
        owner_epoch: attempt.owner_epoch,
        generation: attempt.generation,
        fencing_token: attempt.fencing_token.clone(),
        lease_expires_at_unix_seconds: attempt.lease_expires_at_unix_seconds,
    }
}

#[allow(clippy::too_many_arguments)]
async fn append_attempt(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    request: &LogicalTurnRequest,
    attempt: &LogicalTurnAttemptRequest,
    registry_sequence: u64,
    attempt_no: u64,
    transition: LogicalTurnAttemptTransition,
    superseded_by_attempt_id: Option<&str>,
    previous_sha256: &Sha256Digest,
    recorded_at_unix_seconds: i64,
) -> Result<LogicalTurnAttempt, LogicalTurnRegistryError> {
    let lease_sequence: i64 = sqlx::query_scalar(
        "SELECT lease_sequence FROM cognitive_local_leases
         WHERE owner_agent_id = ? AND lease_id = ? AND generation = ?
           AND fencing_token = ? AND state = 'active'
         ORDER BY lease_sequence DESC LIMIT 1",
    )
    .bind(owner.as_str())
    .bind(&attempt.lease_id)
    .bind(to_i64(attempt.generation, "generation")?)
    .bind(&attempt.fencing_token)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?
    .ok_or_else(|| corrupt("logical attempt has no active local lease witness"))?;
    let lease_head_sha256: String = sqlx::query_scalar(
        "SELECT lease_sha256 FROM cognitive_local_leases
         WHERE owner_agent_id = ? AND lease_id = ? AND lease_sequence = ?",
    )
    .bind(owner.as_str())
    .bind(&attempt.lease_id)
    .bind(lease_sequence)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let lease_head_sha256 = Sha256Digest::parse(lease_head_sha256)
        .map_err(|error| corrupt(format!("invalid local lease witness digest: {error}")))?;
    let attempt_sha256 = attempt_digest(
        owner,
        request,
        attempt,
        registry_sequence,
        attempt_no,
        transition,
        superseded_by_attempt_id,
        &lease_head_sha256,
        previous_sha256,
    );
    sqlx::query(
        "INSERT INTO cognitive_logical_turn_attempts (
            owner_agent_id, logical_turn_id, registry_sequence, attempt_no,
            attempt_id, transition, superseded_by_attempt_id,
            logical_binding_sha256, lease_id, lease_sequence, lease_head_sha256,
            journal_id, trajectory_id, occurrence_key, generation,
            authority_epoch, owner_epoch, fencing_token,
            lease_expires_at_unix_seconds, previous_sha256, attempt_sha256,
            recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(owner.as_str())
    .bind(&request.logical_turn_id)
    .bind(to_i64(registry_sequence, "registry sequence")?)
    .bind(to_i64(attempt_no, "attempt number")?)
    .bind(&attempt.attempt_id)
    .bind(transition.as_str())
    .bind(superseded_by_attempt_id)
    .bind(request.logical_binding_sha256.as_str())
    .bind(&attempt.lease_id)
    .bind(lease_sequence)
    .bind(lease_head_sha256.as_str())
    .bind(&attempt.journal_id)
    .bind(&attempt.trajectory_id)
    .bind(&attempt.occurrence_key)
    .bind(to_i64(attempt.generation, "generation")?)
    .bind(to_i64(attempt.authority_epoch, "authority epoch")?)
    .bind(to_i64(attempt.owner_epoch, "owner epoch")?)
    .bind(&attempt.fencing_token)
    .bind(to_i64(
        attempt.lease_expires_at_unix_seconds,
        "lease expiry",
    )?)
    .bind(previous_sha256.as_str())
    .bind(attempt_sha256.as_str())
    .bind(recorded_at_unix_seconds)
    .execute(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(LogicalTurnAttempt {
        owner_agent_id: owner.clone(),
        logical_turn_id: request.logical_turn_id.clone(),
        registry_sequence,
        attempt_no,
        attempt_id: attempt.attempt_id.clone(),
        transition,
        superseded_by_attempt_id: superseded_by_attempt_id.map(str::to_string),
        logical_binding_sha256: request.logical_binding_sha256.clone(),
        lease_id: attempt.lease_id.clone(),
        lease_sequence: u64::try_from(lease_sequence)
            .map_err(|_| corrupt("lease sequence overflow"))?,
        lease_head_sha256,
        journal_id: attempt.journal_id.clone(),
        trajectory_id: attempt.trajectory_id.clone(),
        occurrence_key: attempt.occurrence_key.clone(),
        generation: attempt.generation,
        authority_epoch: attempt.authority_epoch,
        owner_epoch: attempt.owner_epoch,
        fencing_token: attempt.fencing_token.clone(),
        lease_expires_at_unix_seconds: attempt.lease_expires_at_unix_seconds,
        previous_sha256: previous_sha256.clone(),
        attempt_sha256,
        recorded_at_unix_seconds,
    })
}

async fn load_attempt_chain(
    transaction: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    logical_turn_id: &str,
    logical_binding_sha256: &Sha256Digest,
) -> Result<Vec<LogicalTurnAttempt>, LogicalTurnRegistryError> {
    let rows = sqlx::query(
        "SELECT registry_sequence, attempt_no, attempt_id, transition,
                superseded_by_attempt_id, logical_binding_sha256, lease_id,
                lease_sequence, lease_head_sha256, journal_id, trajectory_id,
                occurrence_key, generation, authority_epoch, owner_epoch,
                fencing_token, lease_expires_at_unix_seconds, previous_sha256,
                attempt_sha256, recorded_at_unix_seconds
         FROM cognitive_logical_turn_attempts
         WHERE owner_agent_id = ? AND logical_turn_id = ?
         ORDER BY registry_sequence",
    )
    .bind(owner.as_str())
    .bind(logical_turn_id)
    .fetch_all(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if rows.len() > MAX_REGISTRY_ROWS {
        return Err(corrupt("logical-turn registry exceeds bounded row count"));
    }
    let mut previous_sha256 = genesis_attempt_digest();
    let mut attempts: Vec<LogicalTurnAttempt> = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let registry_sequence = read_u64(row, "registry_sequence")?;
        if registry_sequence != u64::try_from(index + 1).unwrap_or(u64::MAX) {
            return Err(corrupt("logical-turn registry sequence is not contiguous"));
        }
        let attempt_no = read_u64(row, "attempt_no")?;
        let attempt_id: String = row
            .try_get("attempt_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let transition = LogicalTurnAttemptTransition::parse(
            row.try_get::<String, _>("transition")
                .map_err(crate::cognitive_store::unavailable)?
                .as_str(),
        )?;
        let superseded_by_attempt_id: Option<String> = row
            .try_get("superseded_by_attempt_id")
            .map_err(crate::cognitive_store::unavailable)?;
        if (transition == LogicalTurnAttemptTransition::Active
            && superseded_by_attempt_id.is_some())
            || (transition == LogicalTurnAttemptTransition::Superseded
                && superseded_by_attempt_id.is_none())
        {
            return Err(corrupt(
                "logical-turn transition/supersession shape is invalid",
            ));
        }
        let stored_binding: String = row
            .try_get("logical_binding_sha256")
            .map_err(crate::cognitive_store::unavailable)?;
        if stored_binding != logical_binding_sha256.as_str() {
            return Err(corrupt(
                "logical-turn attempt binding differs from identity",
            ));
        }
        let lease_id: String = row
            .try_get("lease_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let lease_sequence = read_u64(row, "lease_sequence")?;
        let lease_head_sha256 = digest_from_row(row, "lease_head_sha256")?;
        let journal_id: String = row
            .try_get("journal_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let trajectory_id: String = row
            .try_get("trajectory_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let occurrence_key: String = row
            .try_get("occurrence_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let generation = read_u64(row, "generation")?;
        let authority_epoch = read_u64(row, "authority_epoch")?;
        let owner_epoch = read_u64(row, "owner_epoch")?;
        let fencing_token: String = row
            .try_get("fencing_token")
            .map_err(crate::cognitive_store::unavailable)?;
        let lease_expires_at_unix_seconds = read_u64(row, "lease_expires_at_unix_seconds")?;
        let stored_previous = digest_from_row(row, "previous_sha256")?;
        if stored_previous != previous_sha256 {
            return Err(corrupt("logical-turn attempt previous digest mismatch"));
        }
        let attempt_sha256 = digest_from_row(row, "attempt_sha256")?;
        let request = LogicalTurnAttemptRequest {
            attempt_id: attempt_id.clone(),
            lease_id: lease_id.clone(),
            journal_id: journal_id.clone(),
            trajectory_id: trajectory_id.clone(),
            occurrence_key: occurrence_key.clone(),
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token: fencing_token.clone(),
            lease_expires_at_unix_seconds,
        };
        request.validate()?;
        if attempt_sha256
            != attempt_digest_without_scope(
                owner,
                logical_turn_id,
                logical_binding_sha256,
                &request,
                registry_sequence,
                attempt_no,
                transition,
                superseded_by_attempt_id.as_deref(),
                &lease_head_sha256,
                &stored_previous,
            )
        {
            return Err(corrupt("logical-turn attempt digest mismatch"));
        }
        let recorded_at_unix_seconds: i64 = row
            .try_get("recorded_at_unix_seconds")
            .map_err(crate::cognitive_store::unavailable)?;
        let attempt = LogicalTurnAttempt {
            owner_agent_id: owner.clone(),
            logical_turn_id: logical_turn_id.to_string(),
            registry_sequence,
            attempt_no,
            attempt_id,
            transition,
            superseded_by_attempt_id,
            logical_binding_sha256: logical_binding_sha256.clone(),
            lease_id,
            lease_sequence,
            lease_head_sha256,
            journal_id,
            trajectory_id,
            occurrence_key,
            generation,
            authority_epoch,
            owner_epoch,
            fencing_token,
            lease_expires_at_unix_seconds,
            previous_sha256: stored_previous,
            attempt_sha256: attempt_sha256.clone(),
            recorded_at_unix_seconds,
        };
        let historical_lease_state = verify_historical_lease_witness(transaction, &attempt).await?;
        if attempt.transition == LogicalTurnAttemptTransition::Active
            && historical_lease_state != LocalLeaseState::Active
        {
            return Err(corrupt(
                "active logical-turn attempt does not point at an active lease row",
            ));
        }
        if index == 0
            && (attempt.transition != LogicalTurnAttemptTransition::Active
                || attempt.attempt_no != 1)
        {
            return Err(corrupt(
                "logical-turn registry must begin with attempt one active",
            ));
        }
        if let Some(previous) = attempts.last() {
            match previous.transition {
                LogicalTurnAttemptTransition::Active => {
                    if attempt.transition != LogicalTurnAttemptTransition::Superseded
                        || attempt.attempt_no != previous.attempt_no
                        || attempt.attempt_id != previous.attempt_id
                        || attempt.superseded_by_attempt_id.is_none()
                        || attempt.superseded_by_attempt_id.as_deref()
                            == Some(previous.attempt_id.as_str())
                        || !same_physical_attempt(&attempt, previous)
                    {
                        return Err(corrupt(
                            "active logical-turn row must be followed by an exact superseded copy",
                        ));
                    }
                }
                LogicalTurnAttemptTransition::Superseded => {
                    if previous.superseded_by_attempt_id.as_deref()
                        != Some(attempt.attempt_id.as_str())
                        || attempt.transition != LogicalTurnAttemptTransition::Active
                        || attempt.attempt_no != previous.attempt_no.saturating_add(1)
                        || attempt.attempt_id == previous.attempt_id
                        || attempt.lease_id == previous.lease_id
                        || attempt.journal_id == previous.journal_id
                        || attempt.trajectory_id == previous.trajectory_id
                        || attempt.occurrence_key == previous.occurrence_key
                    {
                        return Err(corrupt(
                            "superseded logical-turn row is not followed by a fresh winner",
                        ));
                    }
                }
            }
        }
        previous_sha256 = attempt_sha256;
        attempts.push(attempt);
    }
    let Some(head) = attempts.last() else {
        return Ok(attempts);
    };
    if head.transition != LogicalTurnAttemptTransition::Active {
        return Err(corrupt(
            "logical-turn registry cannot end with a superseded transition",
        ));
    }
    Ok(attempts)
}

fn same_physical_attempt(left: &LogicalTurnAttempt, right: &LogicalTurnAttempt) -> bool {
    left.logical_binding_sha256 == right.logical_binding_sha256
        && left.lease_id == right.lease_id
        && left.lease_sequence == right.lease_sequence
        && left.lease_head_sha256 == right.lease_head_sha256
        && left.journal_id == right.journal_id
        && left.trajectory_id == right.trajectory_id
        && left.occurrence_key == right.occurrence_key
        && left.generation == right.generation
        && left.authority_epoch == right.authority_epoch
        && left.owner_epoch == right.owner_epoch
        && left.fencing_token == right.fencing_token
        && left.lease_expires_at_unix_seconds == right.lease_expires_at_unix_seconds
}

async fn evidence_for_attempt(
    transaction: &mut Transaction<'_, Sqlite>,
    attempt: &LogicalTurnAttempt,
) -> Result<LogicalTurnEvidence, LogicalTurnRegistryError> {
    // Do not scope these probes only by the expected owner.  A foreign row
    // reusing any attempt-scoped identifier is itself evidence that the
    // identity boundary is compromised; fail closed instead of allowing a
    // takeover that a later reopen verifier would reject.
    let event_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_events
         WHERE lease_id = ? OR occurrence_key = ?",
    )
    .bind(&attempt.lease_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let outbox_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_local_outbox
         WHERE lease_id = ? OR occurrence_key = ?",
    )
    .bind(&attempt.lease_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let compact_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_compact_events
         WHERE journal_id = ? OR lease_id = ?",
    )
    .bind(&attempt.journal_id)
    .bind(&attempt.lease_id)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let trajectory_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_h7_trajectory_events
         WHERE trajectory_id = ? OR lease_id = ? OR occurrence_key = ?",
    )
    .bind(&attempt.trajectory_id)
    .bind(&attempt.lease_id)
    .bind(&attempt.occurrence_key)
    .fetch_one(&mut **transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    Ok(LogicalTurnEvidence {
        event_rows: non_negative_count(event_rows, "event evidence")?,
        outbox_rows: non_negative_count(outbox_rows, "outbox evidence")?,
        compact_rows: non_negative_count(compact_rows, "compact evidence")?,
        trajectory_rows: non_negative_count(trajectory_rows, "trajectory evidence")?,
    })
}

fn logical_identity_digest(
    owner: &AgentId,
    logical_turn_id: &str,
    scope_key: &str,
    logical_binding_sha256: &Sha256Digest,
) -> Sha256Digest {
    digest_parts(
        IDENTITY_DOMAIN,
        &[
            owner.as_str().as_bytes(),
            logical_turn_id.as_bytes(),
            scope_key.as_bytes(),
            logical_binding_sha256.as_str().as_bytes(),
        ],
    )
}

#[allow(clippy::too_many_arguments)]
fn attempt_digest(
    owner: &AgentId,
    request: &LogicalTurnRequest,
    attempt: &LogicalTurnAttemptRequest,
    registry_sequence: u64,
    attempt_no: u64,
    transition: LogicalTurnAttemptTransition,
    superseded_by_attempt_id: Option<&str>,
    lease_head_sha256: &Sha256Digest,
    previous_sha256: &Sha256Digest,
) -> Sha256Digest {
    attempt_digest_without_scope(
        owner,
        &request.logical_turn_id,
        &request.logical_binding_sha256,
        attempt,
        registry_sequence,
        attempt_no,
        transition,
        superseded_by_attempt_id,
        lease_head_sha256,
        previous_sha256,
    )
}

#[allow(clippy::too_many_arguments)]
fn attempt_digest_without_scope(
    owner: &AgentId,
    logical_turn_id: &str,
    logical_binding_sha256: &Sha256Digest,
    attempt: &LogicalTurnAttemptRequest,
    registry_sequence: u64,
    attempt_no: u64,
    transition: LogicalTurnAttemptTransition,
    superseded_by_attempt_id: Option<&str>,
    lease_head_sha256: &Sha256Digest,
    previous_sha256: &Sha256Digest,
) -> Sha256Digest {
    let superseded = superseded_by_attempt_id.unwrap_or("");
    digest_parts(
        ATTEMPT_DOMAIN,
        &[
            owner.as_str().as_bytes(),
            logical_turn_id.as_bytes(),
            logical_binding_sha256.as_str().as_bytes(),
            &registry_sequence.to_be_bytes(),
            &attempt_no.to_be_bytes(),
            attempt.attempt_id.as_bytes(),
            transition.as_str().as_bytes(),
            superseded.as_bytes(),
            attempt.lease_id.as_bytes(),
            &attempt.generation.to_be_bytes(),
            &attempt.authority_epoch.to_be_bytes(),
            &attempt.owner_epoch.to_be_bytes(),
            attempt.fencing_token.as_bytes(),
            &attempt.lease_expires_at_unix_seconds.to_be_bytes(),
            attempt.journal_id.as_bytes(),
            attempt.trajectory_id.as_bytes(),
            attempt.occurrence_key.as_bytes(),
            lease_head_sha256.as_str().as_bytes(),
            previous_sha256.as_str().as_bytes(),
        ],
    )
}

fn genesis_attempt_digest() -> Sha256Digest {
    Sha256Digest::for_bytes(GENESIS_ATTEMPT)
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn validate_text(value: &str, label: &str) -> Result<(), LogicalTurnRegistryError> {
    validate_text_max(value, label, MAX_TEXT_BYTES)
}

fn validate_text_max(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), LogicalTurnRegistryError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), LogicalTurnRegistryError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|error| {
            invalid(format!(
                "{label} must be a lowercase SHA-256 digest: {error}"
            ))
        })
}

fn invalid(message: impl Into<String>) -> LogicalTurnRegistryError {
    LogicalTurnRegistryError::Invalid(message.into())
}

fn corrupt(message: impl Into<String>) -> LogicalTurnRegistryError {
    LogicalTurnRegistryError::Corrupt(message.into())
}

fn read_u64(row: &sqlx::sqlite::SqliteRow, column: &str) -> Result<u64, LogicalTurnRegistryError> {
    let value: i64 = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    if value <= 0 {
        return Err(corrupt(format!("{column} must be positive")));
    }
    u64::try_from(value).map_err(|_| corrupt(format!("{column} overflows u64")))
}

fn digest_from_row(
    row: &sqlx::sqlite::SqliteRow,
    column: &str,
) -> Result<Sha256Digest, LogicalTurnRegistryError> {
    let value: String = row
        .try_get(column)
        .map_err(crate::cognitive_store::unavailable)?;
    Sha256Digest::parse(value).map_err(|error| corrupt(format!("invalid {column}: {error}")))
}

fn to_i64(value: u64, label: &str) -> Result<i64, LogicalTurnRegistryError> {
    i64::try_from(value).map_err(|_| invalid(format!("{label} overflows SQLite INTEGER")))
}

fn non_negative_count(value: i64, label: &str) -> Result<u64, LogicalTurnRegistryError> {
    u64::try_from(value).map_err(|_| corrupt(format!("{label} count is negative")))
}

fn now_unix_seconds() -> Result<u64, LogicalTurnRegistryError> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| LogicalTurnRegistryError::Clock(error.to_string()))?
        .as_secs();
    Ok(seconds)
}

fn now_unix_i64() -> Result<i64, LogicalTurnRegistryError> {
    i64::try_from(now_unix_seconds()?).map_err(|_| {
        LogicalTurnRegistryError::Clock("timestamp overflows SQLite INTEGER".to_string())
    })
}

/// Verify every logical identity and its append-only attempt chain.  This is
/// called by the cognitive-store schema verifier and intentionally performs no
/// writes or takeover decisions.
pub(crate) async fn verify_logical_turn_registry(
    pool: &SqlitePool,
    owner: &AgentId,
) -> Result<(), CognitiveStoreError> {
    let mut transaction = pool
        .begin()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    let foreign_identity_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_logical_turns WHERE owner_agent_id != ?",
    )
    .bind(owner.as_str())
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    let foreign_attempt_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_logical_turn_attempts WHERE owner_agent_id != ?",
    )
    .bind(owner.as_str())
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if foreign_identity_rows != 0 || foreign_attempt_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "logical-turn registry contains a foreign owner".to_string(),
        ));
    }
    let orphan_attempt_rows: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM cognitive_logical_turn_attempts AS a
         LEFT JOIN cognitive_logical_turns AS i
           ON i.owner_agent_id = a.owner_agent_id
          AND i.logical_turn_id = a.logical_turn_id
         WHERE i.logical_turn_id IS NULL",
    )
    .fetch_one(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    if orphan_attempt_rows != 0 {
        return Err(CognitiveStoreError::Corrupt(
            "logical-turn attempt has no immutable identity row".to_string(),
        ));
    }
    let rows = sqlx::query(
        "SELECT logical_turn_id, scope_key, logical_binding_sha256, identity_sha256,
                recorded_at_unix_seconds
         FROM cognitive_logical_turns WHERE owner_agent_id = ? ORDER BY logical_turn_id",
    )
    .bind(owner.as_str())
    .fetch_all(&mut *transaction)
    .await
    .map_err(crate::cognitive_store::unavailable)?;
    for row in rows {
        let logical_turn_id: String = row
            .try_get("logical_turn_id")
            .map_err(crate::cognitive_store::unavailable)?;
        let scope_key: String = row
            .try_get("scope_key")
            .map_err(crate::cognitive_store::unavailable)?;
        let logical_binding_sha256 = digest_from_row(&row, "logical_binding_sha256")
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let identity_sha256 = digest_from_row(&row, "identity_sha256")
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let recorded_at: i64 = row
            .try_get("recorded_at_unix_seconds")
            .map_err(crate::cognitive_store::unavailable)?;
        if recorded_at < 0 {
            return Err(CognitiveStoreError::Corrupt(
                "logical identity recorded timestamp is negative".to_string(),
            ));
        }
        LogicalTurnRequest {
            logical_turn_id: logical_turn_id.clone(),
            scope_key: scope_key.clone(),
            logical_binding_sha256: logical_binding_sha256.clone(),
        }
        .validate()
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        if identity_sha256
            != logical_identity_digest(owner, &logical_turn_id, &scope_key, &logical_binding_sha256)
        {
            return Err(CognitiveStoreError::Corrupt(
                "logical identity digest does not match immutable fields".to_string(),
            ));
        }
        let attempts = load_attempt_chain(
            &mut transaction,
            owner,
            &logical_turn_id,
            &logical_binding_sha256,
        )
        .await
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        if attempts.is_empty() {
            return Err(CognitiveStoreError::Corrupt(
                "logical identity has no attempt chain".to_string(),
            ));
        }
    }
    transaction
        .commit()
        .await
        .map_err(crate::cognitive_store::unavailable)?;
    Ok(())
}
