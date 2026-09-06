use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::CognitiveUnavailableReason;
use crate::framing::frame_part;

/// Schema version for the local-development compact hook handshake.
pub const COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION: u32 = 1;

/// Namespace for this validation-only seam. It is deliberately not a
/// production authority or a persisted-event namespace.
pub const COGNITIVE_COMPACT_HOOK_NAMESPACE: &str = "local_development_only";

/// Errors returned by the read-only compact hook contract.
#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum CognitiveCompactError {
    #[error("cognitive compact hooks are absent from this runtime")]
    RuntimeAbsent,
    #[error("cognitive compact hooks are unavailable: {reason:?}")]
    RuntimeUnavailable { reason: CognitiveUnavailableReason },
    #[error("invalid cognitive compact contract: {message}")]
    Invalid { message: String },
    #[error("compact summary cannot admit a fact")]
    SummaryFactAdmission,
    #[error("compact loss report dropped a protected reference")]
    ProtectedReferenceLoss,
    #[error("compact checkpoint revision mismatch: expected {expected}, found {actual}")]
    RevisionMismatch { expected: u64, actual: u64 },
}

/// Epoch and fencing values captured by a pre-compact hook.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactFence {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
}

impl CompactFence {
    pub fn new(
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
    ) -> Result<Self, CognitiveCompactError> {
        if authority_epoch == 0 || owner_epoch == 0 || generation == 0 {
            return Err(invalid("compact fence epochs must be non-zero"));
        }
        let fencing_token = fencing_token.into();
        validate_text(&fencing_token, "fencing token", /*max_bytes*/ 256)?;
        Ok(Self {
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token,
        })
    }
}

/// Immutable parent range captured before compaction starts.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactParentSnapshot {
    pub context_id: String,
    pub parent_event_start: u64,
    pub parent_event_end: u64,
    pub expected_parent_revision: u64,
    pub expected_state_sha256: Sha256Digest,
    pub fence: CompactFence,
}

impl CompactParentSnapshot {
    pub fn new(
        context_id: impl Into<String>,
        parent_event_start: u64,
        parent_event_end: u64,
        expected_parent_revision: u64,
        expected_state_sha256: Sha256Digest,
        fence: CompactFence,
    ) -> Result<Self, CognitiveCompactError> {
        if parent_event_start > parent_event_end {
            return Err(invalid("compact parent event range is inverted"));
        }
        let context_id = context_id.into();
        validate_text(&context_id, "context id", /*max_bytes*/ 512)?;
        Ok(Self {
            context_id,
            parent_event_start,
            parent_event_end,
            expected_parent_revision,
            expected_state_sha256,
            fence,
        })
    }

    fn digest(&self) -> Sha256Digest {
        let start = self.parent_event_start.to_be_bytes();
        let end = self.parent_event_end.to_be_bytes();
        let revision = self.expected_parent_revision.to_be_bytes();
        let authority = self.fence.authority_epoch.to_be_bytes();
        let owner = self.fence.owner_epoch.to_be_bytes();
        let generation = self.fence.generation.to_be_bytes();
        digest_parts(
            b"parent-snapshot",
            &[
                self.context_id.as_bytes(),
                &start,
                &end,
                &revision,
                self.expected_state_sha256.as_str().as_bytes(),
                &authority,
                &owner,
                &generation,
                self.fence.fencing_token.as_bytes(),
            ],
        )
    }
}

/// Short-lived pre-hook lease envelope.
///
/// This type is intentionally just a signed-by-digest snapshot. Constructing
/// it does not acquire a lease, append an event, or grant execution authority;
/// an Agent-local authoritative writer must perform the real CAS transaction.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactLease {
    pub schema_version: u32,
    pub namespace: String,
    pub lease_id: String,
    pub snapshot: CompactParentSnapshot,
    pub lease_sha256: Sha256Digest,
}

impl CompactLease {
    pub fn from_snapshot(snapshot: CompactParentSnapshot) -> Self {
        let snapshot_digest = snapshot.digest();
        let lease_sha256 = digest_parts(b"compact-lease", &[snapshot_digest.as_str().as_bytes()]);
        let lease_id = format!("ctxlease:v1:{}", lease_sha256.as_str());
        Self {
            schema_version: COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION,
            namespace: COGNITIVE_COMPACT_HOOK_NAMESPACE.to_string(),
            lease_id,
            snapshot,
            lease_sha256,
        }
    }

    /// Recompute the lease identity after deserialization. Compact leases are
    /// digest-bound envelopes, not authority grants; callers must reject a
    /// payload whose stored id or digest no longer matches its snapshot.
    pub fn validate_integrity(&self) -> Result<(), CognitiveCompactError> {
        let expected_digest = digest_parts(
            b"compact-lease",
            &[self.snapshot.digest().as_str().as_bytes()],
        );
        if self.lease_sha256 != expected_digest {
            return Err(invalid("compact lease digest does not match snapshot"));
        }
        let expected_id = format!("ctxlease:v1:{}", expected_digest.as_str());
        if self.lease_id != expected_id {
            return Err(invalid("compact lease id does not match digest"));
        }
        Ok(())
    }
}

/// Bounded protected reference carried through a compact checkpoint.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactProtectedRef {
    pub ref_id: String,
    pub kind: String,
    pub required: bool,
}

impl CompactProtectedRef {
    pub fn new(
        ref_id: impl Into<String>,
        kind: impl Into<String>,
        required: bool,
    ) -> Result<Self, CognitiveCompactError> {
        let ref_id = ref_id.into();
        let kind = kind.into();
        validate_text(&ref_id, "protected reference id", /*max_bytes*/ 512)?;
        validate_text(&kind, "protected reference kind", /*max_bytes*/ 128)?;
        Ok(Self {
            ref_id,
            kind,
            required,
        })
    }
}

/// Model/policy digest envelope. A compact summary is never a memory fact.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactSummaryReceipt {
    pub summary_sha256: Sha256Digest,
    pub model_receipt_sha256: Sha256Digest,
    pub policy_digest: Sha256Digest,
    fact_admission: bool,
}

impl CompactSummaryReceipt {
    pub fn new(
        summary_sha256: Sha256Digest,
        model_receipt_sha256: Sha256Digest,
        policy_digest: Sha256Digest,
    ) -> Self {
        Self {
            summary_sha256,
            model_receipt_sha256,
            policy_digest,
            fact_admission: false,
        }
    }

    pub fn fact_admission(&self) -> bool {
        self.fact_admission
    }
}

/// Loss information produced while summarizing a parent event range.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactLossReport {
    pub omitted_event_ids: Vec<String>,
    pub omitted_span_count: u64,
    pub protected_refs_lost: Vec<String>,
    pub semantic_loss_score_ppm: u32,
    pub report_sha256: Sha256Digest,
}

impl CompactLossReport {
    pub fn new(
        mut omitted_event_ids: Vec<String>,
        omitted_span_count: u64,
        mut protected_refs_lost: Vec<String>,
        semantic_loss_score_ppm: u32,
    ) -> Result<Self, CognitiveCompactError> {
        if semantic_loss_score_ppm > 1_000_000 {
            return Err(invalid("semantic loss score must be <= 1_000_000 ppm"));
        }
        for event_id in &omitted_event_ids {
            validate_text(event_id, "omitted event id", /*max_bytes*/ 512)?;
        }
        for ref_id in &protected_refs_lost {
            validate_text(
                ref_id,
                "lost protected reference id",
                /*max_bytes*/ 512,
            )?;
        }
        omitted_event_ids.sort();
        omitted_event_ids.dedup();
        protected_refs_lost.sort();
        protected_refs_lost.dedup();
        let span_count = omitted_span_count.to_be_bytes();
        let score = semantic_loss_score_ppm.to_be_bytes();
        let omitted = joined_parts(&omitted_event_ids);
        let lost = joined_parts(&protected_refs_lost);
        let report_sha256 = digest_parts(
            b"compact-loss-report",
            &[&span_count, &score, &omitted, &lost],
        );
        Ok(Self {
            omitted_event_ids,
            omitted_span_count,
            protected_refs_lost,
            semantic_loss_score_ppm,
            report_sha256,
        })
    }
}

/// Checkpoint handed from the compact operation to the post hook.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CompactCheckpoint {
    pub schema_version: u32,
    pub namespace: String,
    pub checkpoint_id: String,
    pub lease: CompactLease,
    pub protected_refs: Vec<CompactProtectedRef>,
    pub summary: CompactSummaryReceipt,
    pub loss_report: CompactLossReport,
    pub checkpoint_revision: u64,
}

impl CompactCheckpoint {
    pub fn new(
        checkpoint_id: impl Into<String>,
        lease: CompactLease,
        protected_refs: Vec<CompactProtectedRef>,
        summary: CompactSummaryReceipt,
        loss_report: CompactLossReport,
        checkpoint_revision: u64,
    ) -> Result<Self, CognitiveCompactError> {
        let checkpoint_id = checkpoint_id.into();
        validate_text(&checkpoint_id, "checkpoint id", /*max_bytes*/ 512)?;
        if summary.fact_admission() {
            return Err(CognitiveCompactError::SummaryFactAdmission);
        }
        if !loss_report.protected_refs_lost.is_empty() {
            return Err(CognitiveCompactError::ProtectedReferenceLoss);
        }
        let mut seen = std::collections::BTreeSet::new();
        for protected_ref in &protected_refs {
            if !seen.insert(protected_ref.ref_id.as_str()) {
                return Err(invalid("duplicate protected reference id"));
            }
        }
        Ok(Self {
            schema_version: COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION,
            namespace: COGNITIVE_COMPACT_HOOK_NAMESPACE.to_string(),
            checkpoint_id,
            lease,
            protected_refs,
            summary,
            loss_report,
            checkpoint_revision,
        })
    }

    pub fn rehydration_plan(
        &self,
        expected_revision: u64,
    ) -> Result<RehydrationPlan, CognitiveCompactError> {
        if self.checkpoint_revision != expected_revision {
            return Err(CognitiveCompactError::RevisionMismatch {
                expected: expected_revision,
                actual: self.checkpoint_revision,
            });
        }
        self.validate_payload()?;
        Ok(RehydrationPlan {
            schema_version: self.schema_version,
            namespace: self.namespace.clone(),
            checkpoint_id: self.checkpoint_id.clone(),
            checkpoint_revision: self.checkpoint_revision,
            protected_refs: self.protected_refs.clone(),
            summary_sha256: self.summary.summary_sha256.clone(),
            status: RehydrationStatus::NotStarted,
        })
    }

    /// Validates the checkpoint against a fresh parent snapshot without
    /// mutating a store. The authoritative writer must apply the returned
    /// decision in its own CAS transaction.
    pub fn validate_against(&self, current: &CompactParentSnapshot) -> CompactCommitDecision {
        if self.validate_payload().is_err() {
            return CompactCommitDecision::Rejected {
                reason: CompactRejectReason::InvalidPayload,
            };
        }
        let expected = &self.lease.snapshot;
        if expected.fence != current.fence {
            return CompactCommitDecision::StaleGeneration;
        }
        if expected.context_id != current.context_id
            || expected.parent_event_start != current.parent_event_start
            || expected.parent_event_end != current.parent_event_end
        {
            return CompactCommitDecision::Conflict {
                reason: CompactConflictReason::ParentRangeChanged,
            };
        }
        if expected.expected_parent_revision != current.expected_parent_revision {
            return CompactCommitDecision::Conflict {
                reason: CompactConflictReason::ParentRevisionChanged,
            };
        }
        if expected.expected_state_sha256 != current.expected_state_sha256 {
            return CompactCommitDecision::Conflict {
                reason: CompactConflictReason::ParentStateChanged,
            };
        }
        CompactCommitDecision::Accepted {
            checkpoint_id: self.checkpoint_id.clone(),
            checkpoint_revision: self.checkpoint_revision,
        }
    }

    fn validate_payload(&self) -> Result<(), CognitiveCompactError> {
        if self.schema_version != COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION
            || self.namespace != COGNITIVE_COMPACT_HOOK_NAMESPACE
            || self.lease.schema_version != COGNITIVE_COMPACT_HOOK_SCHEMA_VERSION
            || self.lease.namespace != COGNITIVE_COMPACT_HOOK_NAMESPACE
        {
            return Err(invalid("unsupported compact hook schema or namespace"));
        }
        self.lease.validate_integrity()?;
        if self.summary.fact_admission() {
            return Err(CognitiveCompactError::SummaryFactAdmission);
        }
        if !self.loss_report.protected_refs_lost.is_empty() {
            return Err(CognitiveCompactError::ProtectedReferenceLoss);
        }
        Ok(())
    }
}

/// Result of a read-only CAS/fence validation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "result", rename_all = "snake_case")]
pub enum CompactCommitDecision {
    Accepted {
        checkpoint_id: String,
        checkpoint_revision: u64,
    },
    Conflict {
        reason: CompactConflictReason,
    },
    StaleGeneration,
    Rejected {
        reason: CompactRejectReason,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompactConflictReason {
    ParentRangeChanged,
    ParentRevisionChanged,
    ParentStateChanged,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CompactRejectReason {
    InvalidPayload,
}

/// Post-hook output. Rehydration remains a separate, visible operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RehydrationPlan {
    pub schema_version: u32,
    pub namespace: String,
    pub checkpoint_id: String,
    pub checkpoint_revision: u64,
    pub protected_refs: Vec<CompactProtectedRef>,
    pub summary_sha256: Sha256Digest,
    pub status: RehydrationStatus,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RehydrationStatus {
    NotStarted,
    Complete,
    Partial,
    Failed,
    Revoked,
}

fn validate_text(value: &str, label: &str, max_bytes: usize) -> Result<(), CognitiveCompactError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> CognitiveCompactError {
    CognitiveCompactError::Invalid {
        message: message.into(),
    }
}

fn joined_parts(parts: &[String]) -> Vec<u8> {
    parts
        .iter()
        .flat_map(|value| value.as_bytes().iter().copied().chain([0]))
        .collect()
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta-memory:cognitive-compact:v1");
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    Sha256Digest::for_bytes(&hasher.finalize())
}
