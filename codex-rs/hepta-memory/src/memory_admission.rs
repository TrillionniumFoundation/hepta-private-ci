//! Local, fail-closed admission for model and compaction memory candidates.
//!
//! This layer deliberately sits below the extension/tool surface.  A candidate
//! is persisted through the existing CognitiveStore writer as a provisional
//! memory with an empty KG fact set.  It cannot become a fact merely because a
//! summary or model proposal was produced.  Promotion requires an explicit
//! evidence digest and a compare-and-swap revision update.

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveWriteReceipt;
use crate::KgFactSetDraft;
use crate::LedgerSourceKind;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::SourceDraft;
use crate::SourceRevisionId;
use crate::StableMemoryId;

const MAX_CANDIDATE_BYTES: usize = 64 * 1024;
const MAX_EVIDENCE_BYTES: usize = 256;

/// Origin of a candidate that is not yet an admitted memory fact.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCandidateOrigin {
    CompactionSummary,
    ModelProposal,
    ToolObservation,
}

impl MemoryCandidateOrigin {
    pub const fn source_kind(self) -> LedgerSourceKind {
        match self {
            Self::CompactionSummary => LedgerSourceKind::TurnSummary,
            Self::ModelProposal => LedgerSourceKind::AssistantConclusion,
            Self::ToolObservation => LedgerSourceKind::PersistedToolResult,
        }
    }
}

/// The only states exposed by the production admission slice.
///
/// The full lifecycle is intentionally represented by the existing memory
/// verification/lifecycle fields.  Keeping this enum small prevents callers
/// from inventing a hidden state writer beside `CognitiveStore`.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryCandidateState {
    Provisional,
    Verified,
    Tombstoned,
}

/// Input for a local candidate admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCandidateDraft {
    pub stable_key: String,
    pub scope: CognitiveScope,
    pub content: String,
    pub source_event_key: String,
    pub observed_at_unix_seconds: i64,
    pub origin: MemoryCandidateOrigin,
}

/// Local evidence required to turn a provisional candidate into a verified
/// memory.  This is a content-bound digest, not a production signer or an
/// external authority grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryAdmissionEvidence {
    pub digest: Sha256Digest,
    pub basis: String,
}

impl MemoryAdmissionEvidence {
    pub fn from_bytes(bytes: &[u8], basis: impl Into<String>) -> Result<Self, CognitiveStoreError> {
        if bytes.is_empty() || bytes.len() > MAX_EVIDENCE_BYTES {
            return Err(CognitiveStoreError::Invalid(format!(
                "admission evidence must contain 1..={MAX_EVIDENCE_BYTES} bytes"
            )));
        }
        let basis = basis.into();
        if basis.trim().is_empty() || basis.as_bytes().contains(&0) {
            return Err(CognitiveStoreError::Invalid(
                "admission evidence basis must be non-empty and non-NUL".to_string(),
            ));
        }
        Ok(Self {
            digest: Sha256Digest::for_bytes(bytes),
            basis,
        })
    }
}

/// Receipt returned by the local admission writer.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MemoryAdmissionReceipt {
    pub candidate_id: StableMemoryId,
    pub revision: u64,
    pub state: MemoryCandidateState,
    pub origin: MemoryCandidateOrigin,
    pub source: SourceRevisionId,
    pub fact_admitted: bool,
    pub evidence_digest: Option<Sha256Digest>,
    pub write: CognitiveWriteReceipt,
}

impl CognitiveStore {
    /// Persist a model/compaction candidate as a provisional memory.
    ///
    /// The existing transactional writer records the source and memory in one
    /// SQLite transaction and publishes an empty KG projection.  In
    /// particular, no candidate origin can silently write structured facts.
    pub async fn admit_memory_candidate(
        &self,
        access: &CognitiveAccess,
        draft: &MemoryCandidateDraft,
    ) -> Result<MemoryAdmissionReceipt, CognitiveStoreError> {
        validate_candidate_draft(draft)?;
        let source = SourceDraft {
            scope: draft.scope.clone(),
            kind: draft.origin.source_kind(),
            event_key: draft.source_event_key.clone(),
            content: draft.content.as_bytes().to_vec(),
            observed_at_unix_seconds: draft.observed_at_unix_seconds,
        };
        let write = self
            .remember_with_kg(
                access,
                &source,
                &MemoryDraft {
                    stable_key: draft.stable_key.clone(),
                    revision: MemoryRevisionDraft {
                        scope: draft.scope.clone(),
                        content: draft.content.clone(),
                        verification: MemoryVerification::Provisional,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: draft.observed_at_unix_seconds,
                        valid_to_unix_seconds: None,
                        citations: Vec::new(),
                    },
                },
                &KgFactSetDraft::default(),
            )
            .await?;
        Ok(MemoryAdmissionReceipt {
            candidate_id: write.memory.id.memory_id.clone(),
            revision: write.memory.id.revision,
            state: MemoryCandidateState::Provisional,
            origin: draft.origin,
            source: write.source.clone(),
            fact_admitted: false,
            evidence_digest: None,
            write,
        })
    }

    /// Verify a provisional candidate using a local, content-bound evidence
    /// digest and a normal memory CAS update.  No external provider or signer
    /// is consulted, and the caller must explicitly choose the fact set.
    #[allow(clippy::too_many_arguments)]
    pub async fn verify_memory_candidate(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        origin: MemoryCandidateOrigin,
        source: &SourceDraft,
        content: String,
        valid_from_unix_seconds: i64,
        evidence: &MemoryAdmissionEvidence,
        facts: &KgFactSetDraft,
    ) -> Result<MemoryAdmissionReceipt, CognitiveStoreError> {
        validate_evidence_content(&content, evidence)?;
        if source.kind != LedgerSourceKind::ExplicitMemoryDirective {
            return Err(CognitiveStoreError::Invalid(
                "candidate verification requires an explicit memory directive source".to_string(),
            ));
        }
        if source.content != content.as_bytes() {
            return Err(CognitiveStoreError::Invalid(
                "verification source must exactly bind candidate content".to_string(),
            ));
        }
        // Keep this API narrowly scoped to the candidate state transition.  The
        // lower-level `correct_with_kg` writer is intentionally more general
        // (it supports ordinary verified-memory corrections), so inspect the
        // current head before invoking it.  The CAS below still arbitrates a
        // concurrent writer; this read only prevents a verified or tombstoned
        // memory from being reclassified through the admission surface.
        let current = self.latest_memory(access, memory_id).await?;
        if current.verification != MemoryVerification::Provisional
            || !matches!(current.lifecycle, MemoryLifecycleState::Active)
        {
            return Err(CognitiveStoreError::Conflict(
                "only an active provisional candidate can be verified".to_string(),
            ));
        }
        if current.content != content {
            return Err(CognitiveStoreError::Conflict(
                "candidate content changed before verification".to_string(),
            ));
        }
        let draft = MemoryRevisionDraft {
            scope: source.scope.clone(),
            content,
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        };
        let write = self
            .correct_with_kg(access, memory_id, expected_revision, source, &draft, facts)
            .await?;
        Ok(MemoryAdmissionReceipt {
            candidate_id: write.memory.id.memory_id.clone(),
            revision: write.memory.id.revision,
            state: MemoryCandidateState::Verified,
            origin,
            source: write.source.clone(),
            fact_admitted: !facts.entities.is_empty() || !facts.relations.is_empty(),
            evidence_digest: Some(evidence.digest.clone()),
            write,
        })
    }

    /// Tombstone a candidate through the existing append-only forget path.
    #[allow(clippy::too_many_arguments)]
    pub async fn tombstone_memory_candidate(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        origin: MemoryCandidateOrigin,
        source: &SourceDraft,
        reason: String,
        valid_from_unix_seconds: i64,
    ) -> Result<MemoryAdmissionReceipt, CognitiveStoreError> {
        if reason.trim().is_empty() || reason.len() > 256 || reason.as_bytes().contains(&0) {
            return Err(CognitiveStoreError::Invalid(
                "candidate tombstone reason must contain 1..=256 non-NUL bytes".to_string(),
            ));
        }
        if source.content != reason.as_bytes() {
            return Err(CognitiveStoreError::Invalid(
                "tombstone source must exactly bind the reason".to_string(),
            ));
        }
        let write = self
            .forget_with_kg(
                access,
                memory_id,
                expected_revision,
                source,
                &crate::ForgetMemoryDraft {
                    scope: source.scope.clone(),
                    reason: reason.clone(),
                    valid_from_unix_seconds,
                    citations: Vec::new(),
                },
            )
            .await?;
        Ok(MemoryAdmissionReceipt {
            candidate_id: write.memory.id.memory_id.clone(),
            revision: write.memory.id.revision,
            state: MemoryCandidateState::Tombstoned,
            origin,
            source: write.source.clone(),
            fact_admitted: false,
            evidence_digest: None,
            write,
        })
    }
}

fn validate_candidate_draft(draft: &MemoryCandidateDraft) -> Result<(), CognitiveStoreError> {
    crate::cognitive_store::validate_key(&draft.stable_key, "candidate stable key")?;
    crate::cognitive_store::validate_key(&draft.source_event_key, "candidate source event key")?;
    if draft.content.trim().is_empty()
        || draft.content.len() > MAX_CANDIDATE_BYTES
        || draft.content.as_bytes().contains(&0)
    {
        return Err(CognitiveStoreError::Invalid(format!(
            "candidate content must contain 1..={MAX_CANDIDATE_BYTES} non-NUL bytes"
        )));
    }
    Ok(())
}

fn validate_evidence_content(
    content: &str,
    evidence: &MemoryAdmissionEvidence,
) -> Result<(), CognitiveStoreError> {
    if content.trim().is_empty() || content.len() > MAX_CANDIDATE_BYTES {
        return Err(CognitiveStoreError::Invalid(format!(
            "candidate content must contain 1..={MAX_CANDIDATE_BYTES} bytes"
        )));
    }
    let expected = Sha256Digest::for_bytes(content.as_bytes());
    if expected != evidence.digest {
        return Err(CognitiveStoreError::Invalid(
            "admission evidence digest does not bind candidate content".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::MemoryAdmissionEvidence;
    use super::MemoryCandidateDraft;
    use super::MemoryCandidateOrigin;
    use super::MemoryCandidateState;
    use crate::CognitiveAccess;
    use crate::CognitiveScope;
    use crate::KgEntityFactDraft;
    use crate::KgFactSetDraft;
    use crate::KgRelationFactDraft;
    use crate::LedgerSourceKind;
    use crate::SourceDraft;
    use crate::cognitive_test_support::agent_id;
    use crate::cognitive_test_support::layout;
    use tempfile::TempDir;

    #[test]
    fn candidate_origin_never_maps_to_explicit_directive() {
        assert_eq!(
            MemoryCandidateOrigin::CompactionSummary.source_kind(),
            LedgerSourceKind::TurnSummary
        );
        assert_ne!(
            MemoryCandidateOrigin::ModelProposal.source_kind(),
            LedgerSourceKind::ExplicitMemoryDirective
        );
    }

    #[tokio::test]
    async fn admission_persists_provisional_without_kg_facts() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(101);
        let store = crate::CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let receipt = store
            .admit_memory_candidate(
                &CognitiveAccess::agent_private(owner),
                &MemoryCandidateDraft {
                    stable_key: "compact-candidate-1".to_string(),
                    scope: CognitiveScope::AgentPrivate,
                    content: "The compacted context needs review.".to_string(),
                    source_event_key: "compact:event:1".to_string(),
                    observed_at_unix_seconds: 100,
                    origin: MemoryCandidateOrigin::CompactionSummary,
                },
            )
            .await
            .expect("candidate admission");
        assert_eq!(receipt.state, MemoryCandidateState::Provisional);
        assert!(!receipt.fact_admitted);
        assert_eq!(
            receipt.write.memory.verification,
            crate::MemoryVerification::Provisional
        );
        assert_eq!(receipt.write.projection.entity_count, 0);
        assert_eq!(receipt.write.projection.relation_count, 0);
    }

    #[tokio::test]
    async fn verification_requires_explicit_content_bound_evidence_and_cas() {
        let temp = TempDir::new().expect("temp");
        let owner = agent_id(102);
        let store = crate::CognitiveStore::open(&layout(&temp, &owner))
            .await
            .expect("store");
        let content = "A verified local fact.";
        let candidate = store
            .admit_memory_candidate(
                &CognitiveAccess::agent_private(owner.clone()),
                &MemoryCandidateDraft {
                    stable_key: "verify-candidate-1".to_string(),
                    scope: CognitiveScope::AgentPrivate,
                    content: content.to_string(),
                    source_event_key: "compact:event:2".to_string(),
                    observed_at_unix_seconds: 100,
                    origin: MemoryCandidateOrigin::ModelProposal,
                },
            )
            .await
            .expect("candidate admission");
        let bad =
            MemoryAdmissionEvidence::from_bytes(b"different", "local-test").expect("evidence");
        let source = SourceDraft {
            scope: CognitiveScope::AgentPrivate,
            kind: LedgerSourceKind::ExplicitMemoryDirective,
            event_key: "explicit:verify:1".to_string(),
            content: content.as_bytes().to_vec(),
            observed_at_unix_seconds: 101,
        };
        let error = store
            .verify_memory_candidate(
                &CognitiveAccess::agent_private(owner.clone()),
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                content.to_string(),
                101,
                &bad,
                &KgFactSetDraft::default(),
            )
            .await
            .expect_err("mismatched evidence must fail");
        assert!(matches!(error, crate::CognitiveStoreError::Invalid(_)));
        let evidence = MemoryAdmissionEvidence::from_bytes(content.as_bytes(), "local-test")
            .expect("evidence");
        let verified = store
            .verify_memory_candidate(
                &CognitiveAccess::agent_private(owner.clone()),
                &candidate.candidate_id,
                1,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                content.to_string(),
                101,
                &evidence,
                &KgFactSetDraft {
                    entities: vec![KgEntityFactDraft {
                        key: "fact".to_string(),
                        entity_type: "note".to_string(),
                        label: "Verified local fact".to_string(),
                    }],
                    relations: Vec::<KgRelationFactDraft>::new(),
                },
            )
            .await
            .expect("verified candidate");
        assert_eq!(verified.state, MemoryCandidateState::Verified);
        assert!(verified.fact_admitted);
        assert_eq!(verified.revision, 2);

        let repeat = store
            .verify_memory_candidate(
                &CognitiveAccess::agent_private(owner),
                &candidate.candidate_id,
                2,
                MemoryCandidateOrigin::ModelProposal,
                &source,
                content.to_string(),
                102,
                &evidence,
                &KgFactSetDraft::default(),
            )
            .await
            .expect_err("a verified memory cannot re-enter candidate verification");
        assert!(matches!(repeat, crate::CognitiveStoreError::Conflict(_)));
    }
}
