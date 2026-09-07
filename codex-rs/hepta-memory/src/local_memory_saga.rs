//! Qualification-only MemoryAdmission saga over the Agent-local lease/event/
//! outbox journal.
//!
//! The CognitiveStore memory writer and the local outbox are deliberately
//! separate append-only transactions.  This module makes that boundary
//! explicit instead of pretending that two SQLite-facing APIs form a hidden
//! two-phase commit: a local command is first Pending (`Queued`), then becomes
//! Applied, Rejected, or Revoked through an immutable outcome event.  A retry
//! consults the local outcome and the deterministic memory identity before it
//! calls the target writer, so a successful candidate is never written twice.
//!
//! Nothing in this module dispatches an outbox row, writes a shared KG, or
//! grants production/caller/promotion authority.

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use serde_json::json;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStoreError;
use crate::LocalAdmission;
use crate::LocalLeaseOutbox;
use crate::LocalOutcomeState;
use crate::MemoryAdmissionReceipt;
use crate::MemoryCandidateDraft;
use crate::MemoryCandidateOrigin;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionRecord;
use crate::SourceEventId;
use crate::SourceRevisionId;
use crate::StableMemoryId;

pub const LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION: u32 = 1;
pub const LOCAL_MEMORY_ADMISSION_SAGA_NAMESPACE: &str = "local_development_only";
pub const LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER: bool = false;
pub const LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION: bool = false;

const ADMISSION_TOPIC: &str = "hepta.memory.admission.v1";
const TOMBSTONE_TOPIC: &str = "hepta.memory.tombstone.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalMemoryAdmissionState {
    Pending,
    Applied,
    Rejected,
    Revoked,
}

impl LocalMemoryAdmissionState {
    fn from_local(state: LocalOutcomeState) -> Result<Self, LocalMemoryAdmissionError> {
        match state {
            LocalOutcomeState::Queued => Ok(Self::Pending),
            LocalOutcomeState::Committed => Ok(Self::Applied),
            LocalOutcomeState::Rejected => Ok(Self::Rejected),
            LocalOutcomeState::RolledBack => Ok(Self::Revoked),
            LocalOutcomeState::Indeterminate => Err(LocalMemoryAdmissionError::Indeterminate),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum LocalMemoryAdmissionError {
    #[error(transparent)]
    Store(#[from] CognitiveStoreError),
    #[error(transparent)]
    Lease(#[from] crate::LocalLeaseOutboxError),
    #[error("memory admission target outcome is indeterminate")]
    Indeterminate,
    #[error("invalid local memory admission saga: {0}")]
    Invalid(String),
}

/// A local saga receipt.  `admission` is present only for the transaction that
/// actually wrote the candidate; retries expose the stable identity and
/// revision while avoiding a second CognitiveStore write.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalMemoryAdmissionReceipt {
    pub schema_version: u32,
    pub namespace: String,
    pub command_id: String,
    pub occurrence_key: String,
    pub candidate_id: StableMemoryId,
    pub revision: Option<u64>,
    pub state: LocalMemoryAdmissionState,
    pub admission: Option<MemoryAdmissionReceipt>,
    pub rejection_reason: Option<String>,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub promotion: bool,
}

#[derive(Serialize)]
struct CandidateCommand<'a> {
    schema_version: u32,
    kind: &'static str,
    stable_key: &'a str,
    scope: &'a CognitiveScope,
    content_sha256: Sha256Digest,
    source_event_key: &'a str,
    observed_at_unix_seconds: i64,
    origin: MemoryCandidateOrigin,
}

#[derive(Serialize)]
struct TombstoneCommand<'a> {
    schema_version: u32,
    kind: &'static str,
    memory_id: &'a str,
    expected_revision: u64,
    reason_sha256: Sha256Digest,
    valid_from_unix_seconds: i64,
    origin: MemoryCandidateOrigin,
    source_scope: &'a CognitiveScope,
    source_observed_at_unix_seconds: i64,
}

/// Stable key for one logical tombstone attempt.  The immutable outbox
/// payload carries the complete source binding, but source bytes/scope/time
/// are deliberately excluded from this key so a retry with changed input hits
/// the original occurrence and is rejected by `admit`'s payload CAS instead
/// of silently creating a second queued command.
#[derive(Serialize)]
struct TombstoneOccurrence<'a> {
    schema_version: u32,
    kind: &'static str,
    memory_id: &'a str,
    expected_revision: u64,
    reason_sha256: Sha256Digest,
    valid_from_unix_seconds: i64,
    origin: MemoryCandidateOrigin,
    source_event_key: &'a str,
    source_kind: crate::LedgerSourceKind,
}

#[derive(Clone)]
struct CommandIdentity {
    command_id: String,
    occurrence_key: String,
    payload_json: String,
    candidate_id: StableMemoryId,
}

impl LocalLeaseOutbox {
    /// Admit a model/compaction candidate through the existing local
    /// lease/event/outbox seam.  The target CognitiveStore write is local and
    /// provisional; the saga only records Applied after that write returns.
    pub async fn admit_memory_candidate_saga(
        &self,
        access: &CognitiveAccess,
        draft: &MemoryCandidateDraft,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        let identity = candidate_identity(self, draft)?;
        let existing = self
            .inspect_occurrence(identity.occurrence_key.clone())
            .await?;
        if let Some(state) = existing {
            match state {
                LocalOutcomeState::Queued => {}
                _ => return self.replay_candidate(access, draft, identity, state).await,
            }
        }

        let _queued = match self
            .admit(
                identity.occurrence_key.clone(),
                ADMISSION_TOPIC,
                identity.payload_json.clone(),
            )
            .await?
        {
            LocalAdmission::Queued(receipt) | LocalAdmission::Replay(receipt) => receipt,
        };

        match self.store().admit_memory_candidate(access, draft).await {
            Ok(admission) => {
                let receipt_digest = admission.write.memory.content_sha256.clone();
                match self
                    .apply(
                        identity.occurrence_key.clone(),
                        format!("candidate:{}", receipt_digest.as_str()),
                    )
                    .await
                {
                    Ok(_) => Ok(LocalMemoryAdmissionReceipt {
                        schema_version: LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
                        namespace: LOCAL_MEMORY_ADMISSION_SAGA_NAMESPACE.to_string(),
                        command_id: identity.command_id,
                        occurrence_key: identity.occurrence_key,
                        candidate_id: admission.candidate_id.clone(),
                        revision: Some(admission.revision),
                        state: LocalMemoryAdmissionState::Applied,
                        admission: Some(admission),
                        rejection_reason: None,
                        external_effects: LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS,
                        kg_write_authority: LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY,
                        production_caller: LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER,
                        promotion: LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION,
                    }),
                    Err(error) => {
                        self.recover_apply_race(
                            access,
                            &identity,
                            &admission.candidate_id,
                            Some(admission.revision),
                            error,
                        )
                        .await
                    }
                }
            }
            Err(error) => {
                // A concurrent retry may have completed the target write after
                // our inspection.  Prefer the matching durable candidate over
                // recording a false Rejected outcome.
                if let Some(current) = self
                    .matching_candidate(access, &identity.candidate_id, draft)
                    .await?
                {
                    return self
                        .apply_existing_candidate(
                            &identity,
                            current.id.revision,
                            format!("candidate:{}", current.content_sha256.as_str()),
                        )
                        .await;
                }
                let reason = bounded_reason(error.to_string());
                self.reject_saga(identity, reason).await
            }
        }
    }

    /// Tombstone a candidate through the same Pending -> Applied/Rejected
    /// target-ack path.  The underlying CognitiveStore forget operation is
    /// append-only and cannot resurrect a tombstoned head.
    pub async fn tombstone_memory_candidate_saga(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        origin: MemoryCandidateOrigin,
        source: &crate::SourceDraft,
        reason: String,
        valid_from_unix_seconds: i64,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        let identity = tombstone_identity(
            memory_id,
            expected_revision,
            origin,
            source,
            &reason,
            valid_from_unix_seconds,
        )?;
        // A tombstone target can commit in the same crash window as a
        // candidate admission: the CognitiveStore revision may be durable
        // while the local Applied outcome has not been appended yet.  Keep a
        // queued local command on the retry path so the target call below can
        // either finish the tombstone or discover and adopt the already
        // committed target revision.  Replaying a queued command as a
        // terminal error would strand that durable tombstone forever.
        if let Some(state) = self
            .inspect_occurrence(identity.occurrence_key.clone())
            .await?
        {
            match state {
                LocalOutcomeState::Queued => {}
                _ => {
                    return self
                        .replay_tombstone(
                            access,
                            identity,
                            state,
                            memory_id,
                            expected_revision,
                            source,
                            valid_from_unix_seconds,
                            reason,
                        )
                        .await;
                }
            }
        }
        // Re-run admission even when the occurrence was already queued.  The
        // append-only writer validates the immutable payload/topic/fence on a
        // replay; skipping it would let a caller mutate source binding inputs
        // between reopen and target dispatch.
        let _queued = self
            .admit(
                identity.occurrence_key.clone(),
                TOMBSTONE_TOPIC,
                identity.payload_json.clone(),
            )
            .await?;
        match self
            .store()
            .tombstone_memory_candidate(
                access,
                memory_id,
                expected_revision,
                origin,
                source,
                reason.clone(),
                valid_from_unix_seconds,
            )
            .await
        {
            Ok(admission) => {
                let digest = admission.write.memory.content_sha256.clone();
                match self
                    .apply(
                        identity.occurrence_key.clone(),
                        format!("tombstone:{}", digest.as_str()),
                    )
                    .await
                {
                    Ok(_) => Ok(self.receipt(
                        identity,
                        Some(admission.revision),
                        LocalMemoryAdmissionState::Applied,
                        Some(admission),
                        /*rejection_reason*/ None,
                    )),
                    Err(error) => {
                        self.recover_apply_race(
                            access, &identity, memory_id, /*revision*/ None, error,
                        )
                        .await
                    }
                }
            }
            Err(error) => {
                if let Some(current) = self
                    .tombstoned_candidate(
                        access,
                        memory_id,
                        expected_revision,
                        source,
                        valid_from_unix_seconds,
                        &reason,
                    )
                    .await?
                {
                    return self
                        .apply_existing_candidate(
                            &identity,
                            current.id.revision,
                            format!("tombstone:{}", current.content_sha256.as_str()),
                        )
                        .await;
                }
                self.reject_saga(identity, bounded_reason(error.to_string()))
                    .await
            }
        }
    }

    /// Revoke a still-pending candidate command without touching the target
    /// store.  A committed or rejected command is never rewritten as revoked.
    pub async fn revoke_memory_candidate_saga(
        &self,
        draft: &MemoryCandidateDraft,
        reason: impl Into<String>,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        let identity = candidate_identity(self, draft)?;
        let state = self
            .inspect_occurrence(identity.occurrence_key.clone())
            .await?
            .ok_or_else(|| {
                LocalMemoryAdmissionError::Invalid(
                    "cannot revoke a candidate command that was never admitted".to_string(),
                )
            })?;
        match state {
            LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate => {
                let _ =
                    LocalLeaseOutbox::revoke(self, identity.occurrence_key.clone(), reason.into())
                        .await?;
                Ok(self.receipt(
                    identity,
                    /*revision*/ None,
                    LocalMemoryAdmissionState::Revoked,
                    /*admission*/ None,
                    /*rejection_reason*/ None,
                ))
            }
            LocalOutcomeState::Committed => Err(LocalMemoryAdmissionError::Invalid(
                "an applied candidate cannot be revoked through the pending-command seam"
                    .to_string(),
            )),
            LocalOutcomeState::Rejected | LocalOutcomeState::RolledBack => Ok(self.receipt(
                identity,
                /*revision*/ None,
                LocalMemoryAdmissionState::from_local(state)?,
                /*admission*/ None,
                /*rejection_reason*/ None,
            )),
        }
    }

    async fn replay_candidate(
        &self,
        access: &CognitiveAccess,
        draft: &MemoryCandidateDraft,
        identity: CommandIdentity,
        state: LocalOutcomeState,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        match state {
            LocalOutcomeState::Queued => Err(LocalMemoryAdmissionError::Invalid(
                "queued candidate replay must pass through the admission writer".to_string(),
            )),
            LocalOutcomeState::Committed => {
                let current = self
                    .matching_candidate(access, &identity.candidate_id, draft)
                    .await?
                    .ok_or_else(|| {
                        LocalMemoryAdmissionError::Invalid(
                            "local outcome is Applied but candidate target is missing or changed"
                                .to_string(),
                        )
                    })?;
                Ok(self.receipt(
                    identity,
                    Some(current.id.revision),
                    LocalMemoryAdmissionState::Applied,
                    /*admission*/ None,
                    /*rejection_reason*/ None,
                ))
            }
            LocalOutcomeState::Rejected | LocalOutcomeState::RolledBack => Ok(self.receipt(
                identity,
                /*revision*/ None,
                LocalMemoryAdmissionState::from_local(state)?,
                /*admission*/ None,
                /*rejection_reason*/ None,
            )),
            LocalOutcomeState::Indeterminate => Err(LocalMemoryAdmissionError::Indeterminate),
        }
    }

    async fn replay_tombstone(
        &self,
        access: &CognitiveAccess,
        identity: CommandIdentity,
        state: LocalOutcomeState,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &crate::SourceDraft,
        valid_from_unix_seconds: i64,
        reason: String,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        match state {
            LocalOutcomeState::Committed => {
                let current = self
                    .tombstoned_candidate(
                        access,
                        memory_id,
                        expected_revision,
                        source,
                        valid_from_unix_seconds,
                        &reason,
                    )
                    .await?
                    .ok_or_else(|| {
                        LocalMemoryAdmissionError::Invalid(
                            "local outcome is Applied but tombstone target is missing".to_string(),
                        )
                    })?;
                Ok(self.receipt(
                    identity,
                    Some(current.id.revision),
                    LocalMemoryAdmissionState::Applied,
                    /*admission*/ None,
                    /*rejection_reason*/ None,
                ))
            }
            LocalOutcomeState::Queued => Err(LocalMemoryAdmissionError::Invalid(
                "tombstone command is still Pending; retry requires explicit target input"
                    .to_string(),
            )),
            LocalOutcomeState::Rejected | LocalOutcomeState::RolledBack => Ok(self.receipt(
                identity,
                /*revision*/ None,
                LocalMemoryAdmissionState::from_local(state)?,
                /*admission*/ None,
                /*rejection_reason*/ None,
            )),
            LocalOutcomeState::Indeterminate => Err(LocalMemoryAdmissionError::Indeterminate),
        }
    }

    async fn recover_apply_race(
        &self,
        access: &CognitiveAccess,
        identity: &CommandIdentity,
        candidate_id: &StableMemoryId,
        revision: Option<u64>,
        error: crate::LocalLeaseOutboxError,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        if self
            .inspect_occurrence(identity.occurrence_key.clone())
            .await?
            == Some(LocalOutcomeState::Committed)
        {
            let revision = match revision {
                Some(revision) => revision,
                None => {
                    self.store()
                        .latest_memory(access, candidate_id)
                        .await?
                        .id
                        .revision
                }
            };
            return Ok(self.receipt(
                identity.clone(),
                Some(revision),
                LocalMemoryAdmissionState::Applied,
                /*admission*/ None,
                /*rejection_reason*/ None,
            ));
        }
        Err(error.into())
    }

    async fn apply_existing_candidate(
        &self,
        identity: &CommandIdentity,
        revision: u64,
        receipt: String,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        match self.apply(identity.occurrence_key.clone(), receipt).await {
            Ok(_) => Ok(self.receipt(
                identity.clone(),
                Some(revision),
                LocalMemoryAdmissionState::Applied,
                /*admission*/ None,
                /*rejection_reason*/ None,
            )),
            Err(error) => {
                if self
                    .inspect_occurrence(identity.occurrence_key.clone())
                    .await?
                    == Some(LocalOutcomeState::Committed)
                {
                    Ok(self.receipt(
                        identity.clone(),
                        Some(revision),
                        LocalMemoryAdmissionState::Applied,
                        /*admission*/ None,
                        /*rejection_reason*/ None,
                    ))
                } else {
                    Err(error.into())
                }
            }
        }
    }

    async fn matching_candidate(
        &self,
        access: &CognitiveAccess,
        candidate_id: &StableMemoryId,
        draft: &MemoryCandidateDraft,
    ) -> Result<Option<MemoryRevisionRecord>, LocalMemoryAdmissionError> {
        let current = match self.store().latest_memory(access, candidate_id).await {
            Ok(current) => current,
            Err(CognitiveStoreError::Invalid(message)) if message == "memory does not exist" => {
                return Ok(None);
            }
            Err(error) => return Err(error.into()),
        };
        if current.scope == draft.scope
            && current.content == draft.content
            && current.verification == crate::MemoryVerification::Provisional
            && current.lifecycle == MemoryLifecycleState::Active
            && current.valid_from_unix_seconds == draft.observed_at_unix_seconds
        {
            // A stable key is only the memory identity.  It is not sufficient
            // to prove that a retry refers to the same source observation:
            // two attempts may intentionally reuse a key while carrying a
            // different event, timestamp, or payload.  Adopting the existing
            // head in that case would mint a second Applied local outcome for
            // a command whose target write was rejected.  Require the exact
            // immutable citation and its full source bytes before treating a
            // target-side conflict as an idempotent replay.
            let expected = SourceRevisionId::new(SourceEventId::for_event(
                self.store().owner_agent_id(),
                &draft.scope,
                draft.origin.source_kind(),
                &draft.source_event_key,
            ));
            if current.citations.len() != 1 || current.citations[0] != expected {
                return Ok(None);
            }
            let citation = self.store().read_citation(access, &expected).await?;
            if citation.scope == draft.scope
                && citation.kind == draft.origin.source_kind()
                && citation.content == draft.content.as_bytes()
                && citation.observed_at_unix_seconds == draft.observed_at_unix_seconds
            {
                Ok(Some(current))
            } else {
                Ok(None)
            }
        } else {
            Ok(None)
        }
    }

    async fn tombstoned_candidate(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &crate::SourceDraft,
        valid_from_unix_seconds: i64,
        reason: &str,
    ) -> Result<Option<MemoryRevisionRecord>, LocalMemoryAdmissionError> {
        let current = match self.store().latest_memory(access, memory_id).await {
            Ok(current) => current,
            Err(CognitiveStoreError::Invalid(message)) if message == "memory does not exist" => {
                return Ok(None);
            }
            Err(error) => return Err(error.into()),
        };
        if current.lifecycle
            != (MemoryLifecycleState::Tombstoned {
                reason: reason.to_string(),
            })
        {
            return Ok(None);
        }
        if current.id.revision != expected_revision.saturating_add(1)
            || current.valid_from_unix_seconds != valid_from_unix_seconds
        {
            return Ok(None);
        }

        // A tombstone's reason alone is not a sufficient replay witness.  The
        // source citation is immutable and binds scope, source kind, event
        // key, bytes, and observation time.  Without this check a different
        // forget command could observe an already-tombstoned head and be
        // incorrectly marked Applied after its own target write conflicted.
        let expected = SourceRevisionId::new(SourceEventId::for_event(
            self.store().owner_agent_id(),
            &source.scope,
            source.kind,
            &source.event_key,
        ));
        if current.citations.len() != 1 || current.citations[0] != expected {
            return Ok(None);
        }
        let citation = self.store().read_citation(access, &expected).await?;
        if citation.scope == source.scope
            && citation.kind == source.kind
            && citation.content == source.content
            && citation.observed_at_unix_seconds == source.observed_at_unix_seconds
        {
            Ok(Some(current))
        } else {
            Ok(None)
        }
    }

    async fn reject_saga(
        &self,
        identity: CommandIdentity,
        reason: String,
    ) -> Result<LocalMemoryAdmissionReceipt, LocalMemoryAdmissionError> {
        self.reject_inner(&identity.occurrence_key, &reason).await?;
        Ok(self.receipt(
            identity,
            /*revision*/ None,
            LocalMemoryAdmissionState::Rejected,
            /*admission*/ None,
            Some(reason),
        ))
    }

    async fn reject_inner(
        &self,
        occurrence_key: &str,
        reason: &str,
    ) -> Result<(), LocalMemoryAdmissionError> {
        match LocalLeaseOutbox::reject(self, occurrence_key.to_string(), reason.to_string()).await {
            Ok(_) => Ok(()),
            Err(error) => {
                if self.inspect_occurrence(occurrence_key.to_string()).await?
                    == Some(LocalOutcomeState::Rejected)
                {
                    Ok(())
                } else {
                    Err(error.into())
                }
            }
        }
    }

    fn receipt(
        &self,
        identity: CommandIdentity,
        revision: Option<u64>,
        state: LocalMemoryAdmissionState,
        admission: Option<MemoryAdmissionReceipt>,
        rejection_reason: Option<String>,
    ) -> LocalMemoryAdmissionReceipt {
        LocalMemoryAdmissionReceipt {
            schema_version: LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
            namespace: LOCAL_MEMORY_ADMISSION_SAGA_NAMESPACE.to_string(),
            command_id: identity.command_id,
            occurrence_key: identity.occurrence_key,
            candidate_id: identity.candidate_id,
            revision,
            state,
            admission,
            rejection_reason,
            external_effects: LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS,
            kg_write_authority: LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY,
            production_caller: LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER,
            promotion: LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION,
        }
    }
}

fn candidate_identity(
    lease: &LocalLeaseOutbox,
    draft: &MemoryCandidateDraft,
) -> Result<CommandIdentity, LocalMemoryAdmissionError> {
    crate::cognitive_store::validate_key(&draft.stable_key, "candidate stable key")
        .map_err(LocalMemoryAdmissionError::Store)?;
    let content_sha256 = Sha256Digest::for_bytes(draft.content.as_bytes());
    let command = CandidateCommand {
        schema_version: LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
        kind: "memory_candidate_admission",
        stable_key: &draft.stable_key,
        scope: &draft.scope,
        content_sha256,
        source_event_key: &draft.source_event_key,
        observed_at_unix_seconds: draft.observed_at_unix_seconds,
        origin: draft.origin,
    };
    let payload_json = serde_json::to_string(&json!({
        "schema_version": LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
        "kind": "memory_candidate_admission",
        "command": command,
        "external_effects": LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS,
        "kg_write_authority": LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY,
        "production_caller": LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER,
        "promotion": LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION,
    }))
    .map_err(|error| LocalMemoryAdmissionError::Invalid(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(payload_json.as_bytes());
    let command_id = format!("memcmd:v1:{}", digest.as_str());
    let occurrence_key = format!("memadm:v1:{}", digest.as_str());
    let candidate_id = StableMemoryId::for_key(
        lease.store().owner_agent_id(),
        &draft.scope,
        &draft.stable_key,
    );
    Ok(CommandIdentity {
        command_id,
        occurrence_key,
        payload_json,
        candidate_id,
    })
}

fn tombstone_identity(
    memory_id: &StableMemoryId,
    expected_revision: u64,
    origin: MemoryCandidateOrigin,
    source: &crate::SourceDraft,
    reason: &str,
    valid_from_unix_seconds: i64,
) -> Result<CommandIdentity, LocalMemoryAdmissionError> {
    if reason.trim().is_empty() || reason.len() > 256 || reason.as_bytes().contains(&0) {
        return Err(LocalMemoryAdmissionError::Invalid(
            "tombstone reason must contain 1..=256 non-NUL bytes".to_string(),
        ));
    }
    let command = TombstoneCommand {
        schema_version: LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
        kind: "memory_candidate_tombstone",
        memory_id: memory_id.as_str(),
        expected_revision,
        reason_sha256: Sha256Digest::for_bytes(reason.as_bytes()),
        valid_from_unix_seconds,
        origin,
        source_scope: &source.scope,
        source_observed_at_unix_seconds: source.observed_at_unix_seconds,
    };
    let payload_json = serde_json::to_string(&json!({
        "schema_version": LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
        "kind": "memory_candidate_tombstone",
        "command": command,
        "source_event_key": source.event_key,
        "source_kind": source.kind,
        "external_effects": LOCAL_MEMORY_ADMISSION_SAGA_EXTERNAL_EFFECTS,
        "kg_write_authority": LOCAL_MEMORY_ADMISSION_SAGA_KG_WRITE_AUTHORITY,
        "production_caller": LOCAL_MEMORY_ADMISSION_SAGA_PRODUCTION_CALLER,
        "promotion": LOCAL_MEMORY_ADMISSION_SAGA_PROMOTION,
    }))
    .map_err(|error| LocalMemoryAdmissionError::Invalid(error.to_string()))?;
    let occurrence = TombstoneOccurrence {
        schema_version: LOCAL_MEMORY_ADMISSION_SAGA_SCHEMA_VERSION,
        kind: "memory_candidate_tombstone",
        memory_id: memory_id.as_str(),
        expected_revision,
        reason_sha256: Sha256Digest::for_bytes(reason.as_bytes()),
        valid_from_unix_seconds,
        origin,
        source_event_key: &source.event_key,
        source_kind: source.kind,
    };
    let occurrence_json = serde_json::to_string(&occurrence)
        .map_err(|error| LocalMemoryAdmissionError::Invalid(error.to_string()))?;
    let digest = Sha256Digest::for_bytes(occurrence_json.as_bytes());
    Ok(CommandIdentity {
        command_id: format!("memcmd:v1:{}", digest.as_str()),
        occurrence_key: format!("memtomb:v1:{}", digest.as_str()),
        payload_json,
        candidate_id: memory_id.clone(),
    })
}

fn bounded_reason(reason: String) -> String {
    reason.chars().take(512).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CognitiveScope;
    use crate::CognitiveStore;
    use crate::LedgerSourceKind;
    use crate::LocalLeaseAcquire;
    use crate::SourceDraft;
    use crate::cognitive_test_support::agent_id;
    use crate::cognitive_test_support::layout;
    use tempfile::TempDir;

    async fn setup(number: u8) -> (TempDir, CognitiveStore, LocalLeaseOutbox) {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(number);
        let store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let lease = match store
            .acquire_local_lease("lease:memory-saga", 1, "fence:memory-saga")
            .await
            .expect("lease")
        {
            LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
        };
        (temp, store, lease)
    }

    fn draft() -> MemoryCandidateDraft {
        MemoryCandidateDraft {
            stable_key: "candidate:saga:1".to_string(),
            scope: CognitiveScope::AgentPrivate,
            content: "A local candidate is not yet a fact.".to_string(),
            source_event_key: "turn:event:1".to_string(),
            observed_at_unix_seconds: 100,
            origin: MemoryCandidateOrigin::CompactionSummary,
        }
    }

    #[tokio::test]
    async fn candidate_saga_applies_once_and_replays_without_double_write() {
        let (_temp, store, lease) = setup(211).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner);
        let first = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("first admission");
        assert_eq!(first.state, LocalMemoryAdmissionState::Applied);
        assert!(!first.external_effects);
        assert!(!first.kg_write_authority);
        assert!(!first.production_caller);
        assert!(!first.promotion);
        let second = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("idempotent replay");
        assert_eq!(second.state, LocalMemoryAdmissionState::Applied);
        assert_eq!(second.candidate_id, first.candidate_id);
        assert_eq!(second.revision, Some(1));
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 1);
        let counts = lease.snapshot_counts().await.expect("journal counts");
        assert_eq!(counts.event_rows, 2);
        assert_eq!(counts.outbox_rows, 1);
    }

    #[tokio::test]
    async fn pending_candidate_can_be_revoked_without_target_write() {
        let (_temp, store, lease) = setup(212).await;
        let candidate = draft();
        let identity = candidate_identity(&lease, &candidate).expect("identity");
        lease
            .admit(
                identity.occurrence_key.clone(),
                ADMISSION_TOPIC,
                identity.payload_json,
            )
            .await
            .expect("pending admission");
        let revoked = lease
            .revoke_memory_candidate_saga(&candidate, "qualification revoked")
            .await
            .expect("revoke");
        assert_eq!(revoked.state, LocalMemoryAdmissionState::Revoked);
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 0);
    }

    #[tokio::test]
    async fn queued_target_success_recovery_does_not_append_a_second_revision() {
        let (_temp, store, lease) = setup(214).await;
        let candidate = draft();
        let identity = candidate_identity(&lease, &candidate).expect("identity");
        lease
            .admit(
                identity.occurrence_key.clone(),
                ADMISSION_TOPIC,
                identity.payload_json,
            )
            .await
            .expect("pending admission");
        // Model the crash window after the target transaction committed but
        // before the local Applied outcome was appended.  The saga retry will
        // receive the deterministic stable-key conflict and must adopt the
        // existing target revision rather than writing another one.
        let owner = store.owner_agent_id().clone();
        store
            .admit_memory_candidate(&CognitiveAccess::agent_private(owner), &candidate)
            .await
            .expect("target-side candidate");
        let applied = lease
            .admit_memory_candidate_saga(
                &CognitiveAccess::agent_private(store.owner_agent_id().clone()),
                &candidate,
            )
            .await
            .expect("recover queued target");
        assert_eq!(applied.state, LocalMemoryAdmissionState::Applied);
        assert_eq!(applied.revision, Some(1));
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 1);
    }

    #[tokio::test]
    async fn stable_key_conflict_with_different_source_is_rejected_not_adopted() {
        let (_temp, store, lease) = setup(216).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner);
        let first = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("first candidate");
        assert_eq!(first.state, LocalMemoryAdmissionState::Applied);

        // Reusing a stable key is a target-side conflict, but changing the
        // source event makes this a different command.  The existing head
        // must not be adopted as if the second source had been written.
        let mut conflicting = draft();
        conflicting.source_event_key = "turn:event:different-source".to_string();
        conflicting.observed_at_unix_seconds = 101;
        let second = lease
            .admit_memory_candidate_saga(&access, &conflicting)
            .await
            .expect("conflicting candidate is explicitly rejected");
        assert_eq!(second.state, LocalMemoryAdmissionState::Rejected);
        assert!(second.rejection_reason.is_some());
        assert_eq!(second.candidate_id, first.candidate_id);
        assert_eq!(second.revision, None);

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 1, "a source conflict must not duplicate the target");
        assert_eq!(
            lease.snapshot_counts().await.expect("journal counts"),
            crate::LocalLeaseOutboxCounts {
                lease_rows: 1,
                event_rows: 4,
                outbox_rows: 2,
            }
        );
    }

    #[tokio::test]
    async fn tombstone_target_commit_recovery_after_reopen_is_idempotent() {
        let (temp, store, lease) = setup(215).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner.clone());
        let candidate = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("candidate");
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "forget:event:reopen".to_string(),
            content: b"privacy erasure after reopen".to_vec(),
            observed_at_unix_seconds: 101,
        };
        let reason = "privacy erasure after reopen".to_string();
        let identity = tombstone_identity(
            &candidate.candidate_id,
            1,
            MemoryCandidateOrigin::ModelProposal,
            &source,
            &reason,
            101,
        )
        .expect("tombstone identity");

        // Model the crash window after the target revision commits but before
        // the local Applied outcome is appended.  The queued command remains
        // durable in the outbox while the target is already tombstoned.
        lease
            .admit(
                identity.occurrence_key.clone(),
                TOMBSTONE_TOPIC,
                identity.payload_json.clone(),
            )
            .await
            .expect("queued tombstone");
        let direct = store
            .tombstone_memory_candidate(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                reason.clone(),
                101,
            )
            .await
            .expect("target tombstone");
        assert_eq!(direct.revision, 2);

        // Reopen the Agent-local database as a fresh process would.  The
        // retry must adopt the existing target revision, append exactly one
        // local Applied outcome, and never create a third memory revision.
        drop(lease);
        store.pool.close().await;
        drop(store);
        let reopened_store = CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("reopen store");
        let reopened = match reopened_store
            .acquire_local_lease("lease:memory-saga", 1, "fence:memory-saga")
            .await
            .expect("replay lease")
        {
            LocalLeaseAcquire::Replay(lease) => lease,
            LocalLeaseAcquire::Acquired(_) => panic!("reopen must replay active lease"),
        };
        let recovered = reopened
            .tombstone_memory_candidate_saga(
                &CognitiveAccess::agent_private(owner.clone()),
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                reason,
                101,
            )
            .await
            .expect("recover tombstone after reopen");
        assert_eq!(recovered.state, LocalMemoryAdmissionState::Applied);
        assert_eq!(recovered.revision, Some(2));
        assert!(recovered.admission.is_none());
        assert!(!recovered.external_effects);
        assert!(!recovered.kg_write_authority);
        assert!(!recovered.production_caller);
        assert!(!recovered.promotion);

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&reopened_store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 2, "recovery must not append a duplicate tombstone");
        assert_eq!(
            reopened.snapshot_counts().await.expect("journal counts"),
            crate::LocalLeaseOutboxCounts {
                lease_rows: 1,
                event_rows: 4,
                outbox_rows: 2,
            }
        );
        assert_eq!(
            reopened
                .inspect_occurrence(identity.occurrence_key)
                .await
                .expect("tombstone outcome"),
            Some(LocalOutcomeState::Committed)
        );
    }

    #[tokio::test]
    async fn queued_tombstone_replay_rejects_source_binding_drift() {
        let (_temp, store, lease) = setup(218).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner);
        let candidate = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("candidate");
        let reason = "queued source binding must remain immutable".to_string();
        let first_source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "forget:event:queued-binding".to_string(),
            content: reason.as_bytes().to_vec(),
            observed_at_unix_seconds: 101,
        };
        let first_identity = tombstone_identity(
            &candidate.candidate_id,
            1,
            MemoryCandidateOrigin::ModelProposal,
            &first_source,
            &reason,
            101,
        )
        .expect("first identity");
        lease
            .admit(
                first_identity.occurrence_key.clone(),
                TOMBSTONE_TOPIC,
                first_identity.payload_json.clone(),
            )
            .await
            .expect("queue first tombstone");

        // Keep the logical command identity while changing only the source
        // observation time.  The payload CAS must reject this as an input
        // mutation instead of allowing a queued command to write under a new
        // source witness.
        let changed_source = SourceDraft {
            observed_at_unix_seconds: 102,
            ..first_source.clone()
        };
        let changed_identity = tombstone_identity(
            &candidate.candidate_id,
            1,
            MemoryCandidateOrigin::ModelProposal,
            &changed_source,
            &reason,
            101,
        )
        .expect("changed identity");
        assert_eq!(
            changed_identity.occurrence_key, first_identity.occurrence_key,
            "source observation drift must target the original occurrence"
        );
        assert_ne!(changed_identity.payload_json, first_identity.payload_json);

        let result = lease
            .tombstone_memory_candidate_saga(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &changed_source,
                reason,
                101,
            )
            .await;
        assert!(matches!(
            result,
            Err(LocalMemoryAdmissionError::Lease(
                crate::LocalLeaseOutboxError::CasConflict(_)
            ))
        ));
        assert_eq!(
            lease
                .inspect_occurrence(first_identity.occurrence_key)
                .await
                .expect("queued state"),
            Some(LocalOutcomeState::Queued)
        );
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 1, "input drift must not write a tombstone");
    }

    #[tokio::test]
    async fn tombstone_saga_is_append_only_and_idempotent() {
        let (_temp, store, lease) = setup(213).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner);
        let candidate = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("candidate");
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "forget:event:1".to_string(),
            content: b"privacy erasure".to_vec(),
            observed_at_unix_seconds: 101,
        };
        let first = lease
            .tombstone_memory_candidate_saga(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                "privacy erasure".to_string(),
                101,
            )
            .await
            .expect("tombstone");
        assert_eq!(first.state, LocalMemoryAdmissionState::Applied);
        let second = lease
            .tombstone_memory_candidate_saga(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                "privacy erasure".to_string(),
                101,
            )
            .await
            .expect("tombstone replay");
        assert_eq!(second.state, LocalMemoryAdmissionState::Applied);
        assert_eq!(second.revision, Some(2));
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(count, 2);
    }

    #[tokio::test]
    async fn tombstone_conflict_with_different_source_is_rejected_not_adopted() {
        let (_temp, store, lease) = setup(217).await;
        let owner = store.owner_agent_id().clone();
        let access = CognitiveAccess::agent_private(owner);
        let candidate = lease
            .admit_memory_candidate_saga(&access, &draft())
            .await
            .expect("candidate");
        let reason = "privacy erasure with source binding".to_string();
        let first_source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "forget:event:first-source".to_string(),
            content: reason.as_bytes().to_vec(),
            observed_at_unix_seconds: 101,
        };
        let first = lease
            .tombstone_memory_candidate_saga(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &first_source,
                reason.clone(),
                101,
            )
            .await
            .expect("first tombstone");
        assert_eq!(first.state, LocalMemoryAdmissionState::Applied);

        // The target is already tombstoned, so the second command's write
        // conflicts.  Its different source event must keep it Rejected rather
        // than falsely adopting the first tombstone by matching only reason.
        let second_source = SourceDraft {
            event_key: "forget:event:second-source".to_string(),
            observed_at_unix_seconds: 102,
            ..first_source.clone()
        };
        let second = lease
            .tombstone_memory_candidate_saga(
                &access,
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &second_source,
                reason,
                102,
            )
            .await
            .expect("conflicting tombstone is explicitly rejected");
        assert_eq!(second.state, LocalMemoryAdmissionState::Rejected);
        assert!(second.rejection_reason.is_some());
        assert_eq!(second.revision, None);

        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM memory_revisions")
            .fetch_one(&store.pool)
            .await
            .expect("memory count");
        assert_eq!(
            count, 2,
            "a tombstone source conflict must not append again"
        );
        assert_eq!(
            lease.snapshot_counts().await.expect("journal counts"),
            crate::LocalLeaseOutboxCounts {
                lease_rows: 1,
                event_rows: 6,
                outbox_rows: 3,
            }
        );
    }
}
