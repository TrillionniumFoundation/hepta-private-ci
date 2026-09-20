//! Loss-bounded, deletion-aware compaction qualification.
//!
//! Compaction never rewrites or deletes source facts. It selects references from
//! one coherent Lane C snapshot, records exactly what was retained and omitted,
//! preserves protected live references, treats tombstones as terminal and emits
//! a candidate checkpoint plus a separate proof. A checkpoint is not selectable
//! until the proof is produced from independent holdout and reconstruction
//! observations.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::OutcomeSignalV1;
use codex_hepta_cognitive_types::hnmf_learning::ReplaySelectionReceiptV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::CompactCheckpointV1;
use codex_hepta_cognitive_types::lane_c::CompactionProofV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_QUALIFIED_COMPACTION_INPUTS: usize = 65_536;
pub const MAX_PROTECTED_COMPACTION_REFS: usize = 4_096;
const POLICY_DOMAIN: &[u8] = b"hepta.compaction-policy.v2";
const CANDIDATE_DOMAIN: &[u8] = b"hepta.compaction-candidate.v2";
const SUPPORT_MANIFEST_DOMAIN: &[u8] = b"hepta.compaction-support-manifest.v2";
const PAYLOAD_DOMAIN: &[u8] = b"hepta.compaction-payload.v2";
const OMITTED_DOMAIN: &[u8] = b"hepta.compaction-omitted.v2";
const LOSS_REPORT_DOMAIN: &[u8] = b"hepta.compaction-loss-report.v2";
const CANONICAL_REPLAY_SHADOW_DOMAIN: &[u8] =
    b"hepta.compaction.canonical-replay-shadow.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionPolicyV2 {
    pub policy_id: StableId,
    pub algorithm_digest: Digest32,
    pub compatibility_digest: Digest32,
    pub maximum_retained_records: u32,
    pub protected_record_ids: Vec<StableId>,
}

impl CompactionPolicyV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        ensure_digest("algorithm", self.algorithm_digest)?;
        ensure_digest("compatibility", self.compatibility_digest)?;
        let maximum = usize::try_from(self.maximum_retained_records).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_QUALIFIED_COMPACTION_INPUTS {
            return Err(QualifiedCompactionError::InvalidRetentionLimit);
        }
        if self.protected_record_ids.len() > MAX_PROTECTED_COMPACTION_REFS {
            return Err(QualifiedCompactionError::ProtectedReferenceLimitExceeded);
        }
        ensure_unique_ids(&self.protected_record_ids)?;
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut protected = self.protected_record_ids.iter().collect::<Vec<_>>();
        protected.sort();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(POLICY_DOMAIN);
        push_id(&mut bytes, &self.policy_id);
        push_digest(&mut bytes, self.algorithm_digest);
        push_digest(&mut bytes, self.compatibility_digest);
        push_u64(&mut bytes, u64::from(self.maximum_retained_records));
        push_len(&mut bytes, protected.len());
        for record_id in protected {
            push_id(&mut bytes, record_id);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionInputRecordV2 {
    pub record: MemoryRecord,
    pub retention_priority: u32,
    pub retention_reason_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionLossReportV2 {
    pub source_current_heads: u64,
    pub live_source_heads: u64,
    pub retained_records: u64,
    pub omitted_live_records: u64,
    pub deleted_records: u64,
    pub protected_live_records: u64,
    pub protected_retained_records: u64,
    pub protected_deleted_records: u64,
    pub loss_report_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CompactionLossReportV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        if self.live_source_heads + self.deleted_records != self.source_current_heads {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.retained_records + self.omitted_live_records != self.live_source_heads {
            return Err(QualifiedCompactionError::InvalidLossAccounting);
        }
        if self.protected_retained_records != self.protected_live_records
            || self.protected_live_records + self.protected_deleted_records
                > self.source_current_heads
        {
            return Err(QualifiedCompactionError::ProtectedReferenceLost);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.loss_report_digest != self.compute_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("loss_report"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(LOSS_REPORT_DOMAIN);
        for value in [
            self.source_current_heads,
            self.live_source_heads,
            self.retained_records,
            self.omitted_live_records,
            self.deleted_records,
            self.protected_live_records,
            self.protected_retained_records,
            self.protected_deleted_records,
        ] {
            push_u64(&mut bytes, value);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualifiedCompactionCandidateV2 {
    pub source_snapshot: CognitiveSnapshotKeyV1,
    pub policy_digest: Digest32,
    pub retained_records: Vec<MemoryRecord>,
    pub omitted_record_digests: Vec<Digest32>,
    pub checkpoint: CompactCheckpointV1,
    pub loss_report: CompactionLossReportV2,
    pub candidate_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl QualifiedCompactionCandidateV2 {
    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.source_snapshot
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        ensure_digest("policy", self.policy_digest)?;
        self.checkpoint
            .validate()
            .map_err(QualifiedCompactionError::Contract)?;
        self.loss_report.validate()?;
        if self.checkpoint.source_snapshot != self.source_snapshot {
            return Err(QualifiedCompactionError::SnapshotMismatch);
        }
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        let mut identities = BTreeSet::new();
        for record in &self.retained_records {
            record
                .validate()
                .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
            if record.state != RecordState::Live {
                return Err(QualifiedCompactionError::TombstoneRetained(
                    record.record_id.to_string(),
                ));
            }
            if !identities.insert(record.record_id.clone()) {
                return Err(QualifiedCompactionError::DuplicateRetainedRecord(
                    record.record_id.to_string(),
                ));
            }
        }
        if self.candidate_digest != self.compute_candidate_digest() {
            return Err(QualifiedCompactionError::DigestMismatch("candidate"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_candidate_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANDIDATE_DOMAIN);
        push_digest(&mut bytes, self.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.policy_digest);
        push_digest(&mut bytes, self.checkpoint.checkpoint_digest);
        push_digest(&mut bytes, self.loss_report.loss_report_digest);
        push_len(&mut bytes, self.retained_records.len());
        for record in &self.retained_records {
            push_digest(&mut bytes, record.record_digest());
        }
        push_len(&mut bytes, self.omitted_record_digests.len());
        for digest in &self.omitted_record_digests {
            push_digest(&mut bytes, *digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReplayRecordBindingV1 {
    pub event_id: ContractIdV1,
    pub legacy_record_id: StableId,
    pub legacy_record_revision: Revision,
    pub legacy_record_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalReplayCompactionShadowV1 {
    pub candidate: QualifiedCompactionCandidateV2,
    pub replay_receipt: ReplaySelectionReceiptV1,
    pub replay_receipt_digest: Digest32,
    pub outcome_signal: OutcomeSignalV1,
    pub outcome_signal_digest: Digest32,
    pub selected_bindings: Vec<CanonicalReplayRecordBindingV1>,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CanonicalReplayCompactionShadowV1 {
    #[must_use]
    pub fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = CANONICAL_REPLAY_SHADOW_DOMAIN.to_vec();
        push_digest(&mut bytes, self.candidate.source_snapshot.vector_digest);
        push_digest(&mut bytes, self.candidate.candidate_digest);
        push_digest(&mut bytes, self.replay_receipt_digest);
        push_digest(&mut bytes, self.outcome_signal_digest);
        push_len(&mut bytes, self.selected_bindings.len());
        for binding in &self.selected_bindings {
            push_raw_id(&mut bytes, binding.event_id.as_str());
            push_id(&mut bytes, &binding.legacy_record_id);
            push_u64(&mut bytes, binding.legacy_record_revision.get());
            push_digest(&mut bytes, binding.legacy_record_digest);
        }
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), QualifiedCompactionError> {
        self.candidate.validate()?;
        self.replay_receipt
            .validate()
            .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
        self.outcome_signal
            .validate()
            .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
        let replay_digest = canonical_contract_digest_v1(&self.replay_receipt)
            .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
        let outcome_digest = canonical_contract_digest_v1(&self.outcome_signal)
            .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
        if replay_digest != self.replay_receipt_digest || outcome_digest != self.outcome_signal_digest
        {
            return Err(QualifiedCompactionError::CanonicalShadowDigestMismatch);
        }
        validate_canonical_replay_bindings(
            &self.candidate,
            &self.replay_receipt,
            &self.selected_bindings,
        )?;
        if self.authority.grants_any() {
            return Err(QualifiedCompactionError::AuthorityGranted);
        }
        if self.binding_digest != self.compute_binding_digest() {
            return Err(QualifiedCompactionError::CanonicalShadowDigestMismatch);
        }
        Ok(())
    }
}

/// Bind canonical replay/outcome evidence to an existing qualified compaction
/// candidate without changing the candidate's retention decision.
///
/// OutcomeSignalV1 is co-observed evidence only here; this adapter does not
/// claim that the outcome caused the replay selection or compaction priority.
pub fn bind_canonical_replay_outcome_shadow_v1(
    candidate: &QualifiedCompactionCandidateV2,
    replay_receipt: ReplaySelectionReceiptV1,
    outcome_signal: OutcomeSignalV1,
    bindings: Vec<CanonicalReplayRecordBindingV1>,
) -> Result<CanonicalReplayCompactionShadowV1, QualifiedCompactionError> {
    candidate.validate()?;
    replay_receipt
        .validate()
        .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
    outcome_signal
        .validate()
        .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
    validate_canonical_replay_bindings(candidate, &replay_receipt, &bindings)?;
    let replay_receipt_digest = canonical_contract_digest_v1(&replay_receipt)
        .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;
    let outcome_signal_digest = canonical_contract_digest_v1(&outcome_signal)
        .map_err(|error| QualifiedCompactionError::CanonicalContract(error.to_string()))?;

    let mut shadow = CanonicalReplayCompactionShadowV1 {
        candidate: candidate.clone(),
        replay_receipt,
        replay_receipt_digest,
        outcome_signal,
        outcome_signal_digest,
        selected_bindings: bindings,
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    shadow.binding_digest = shadow.compute_binding_digest();
    Ok(shadow)
}

fn validate_canonical_replay_bindings(
    candidate: &QualifiedCompactionCandidateV2,
    replay_receipt: &ReplaySelectionReceiptV1,
    bindings: &[CanonicalReplayRecordBindingV1],
) -> Result<(), QualifiedCompactionError> {
    if bindings.len() != replay_receipt.selected_event_ids.len() {
        return Err(QualifiedCompactionError::CanonicalReplayBindingMismatch);
    }
    let mut used = vec![false; bindings.len()];
    for event_id in &replay_receipt.selected_event_ids {
        let Some((index, binding)) = bindings
            .iter()
            .enumerate()
            .find(|(index, binding)| !used[*index] && &binding.event_id == event_id)
        else {
            return Err(QualifiedCompactionError::CanonicalReplayBindingMismatch);
        };
        used[index] = true;
        let retained = candidate.retained_records.iter().any(|record| {
            record.record_id == binding.legacy_record_id
                && record.revision == binding.legacy_record_revision
                && record.record_digest() == binding.legacy_record_digest
        });
        if !retained {
            return Err(QualifiedCompactionError::CanonicalReplayBindingMismatch);
        }
    }
    if used.iter().any(|used| !*used) {
        return Err(QualifiedCompactionError::CanonicalReplayBindingMismatch);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactionQualificationV2 {
    pub evaluator_id: StableId,
    pub retained_query_suite_digest: Digest32,
    pub reconstruction_obligation_digest: Digest32,
    pub contradiction_holdout_digest: Digest32,
    pub retained_queries_passed: bool,
    pub reconstruction_passed: bool,
    pub contradictions_preserved: bool,
    pub deletion_non_resurrection_passed: bool,
}

pub fn build_qualified_candidate(
    source_snapshot: CognitiveSnapshotKeyV1,
    generation: Generation,
    predecessor_checkpoint_digest: Option<Digest32>,
    policy: &CompactionPolicyV2,
    inputs: Vec<CompactionInputRecordV2>,
) -> Result<QualifiedCompactionCandidateV2, QualifiedCompactionError> {
    source_snapshot
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    policy.validate()?;
    if inputs.len() > MAX_QUALIFIED_COMPACTION_INPUTS {
        return Err(QualifiedCompactionError::InputLimitExceeded);
    }

    let mut by_record = BTreeMap::<StableId, Vec<CompactionInputRecordV2>>::new();
    for input in inputs {
        input
            .record
            .validate()
            .map_err(|error| QualifiedCompactionError::InvalidRecord(error.to_string()))?;
        ensure_digest("retention_reason", input.retention_reason_digest)?;
        by_record
            .entry(input.record.record_id.clone())
            .or_default()
            .push(input);
    }

    let protected = policy
        .protected_record_ids
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>();
    let mut live_heads = Vec::<CompactionInputRecordV2>::new();
    let mut source_current_heads = 0_u64;
    let mut deleted_records = 0_u64;
    let mut protected_deleted_records = 0_u64;

    for (record_id, mut lineage) in by_record {
        lineage.sort_by_key(|input| input.record.revision);
        validate_lineage(&record_id, &lineage)?;
        let Some(head) = lineage.pop() else {
            return Err(QualifiedCompactionError::EmptyLineage);
        };
        source_current_heads = source_current_heads
            .checked_add(1)
            .ok_or(QualifiedCompactionError::Arithmetic)?;
        if head.record.state == RecordState::Tombstone {
            deleted_records = deleted_records
                .checked_add(1)
                .ok_or(QualifiedCompactionError::Arithmetic)?;
            if protected.contains(&record_id) {
                protected_deleted_records = protected_deleted_records
                    .checked_add(1)
                    .ok_or(QualifiedCompactionError::Arithmetic)?;
            }
        } else {
            live_heads.push(head);
        }
    }

    live_heads.sort_by(|left, right| {
        protected
            .contains(&right.record.record_id)
            .cmp(&protected.contains(&left.record.record_id))
            .then_with(|| right.retention_priority.cmp(&left.retention_priority))
            .then_with(|| left.record.record_id.cmp(&right.record.record_id))
            .then_with(|| left.record.revision.cmp(&right.record.revision))
    });
    let protected_live_records = live_heads
        .iter()
        .filter(|input| protected.contains(&input.record.record_id))
        .count();
    let maximum = usize::try_from(policy.maximum_retained_records).unwrap_or(usize::MAX);
    if protected_live_records > maximum {
        return Err(QualifiedCompactionError::ProtectedReferencesExceedCapacity);
    }

    let retained_inputs = live_heads.iter().take(maximum).collect::<Vec<_>>();
    let omitted_inputs = live_heads.iter().skip(maximum).collect::<Vec<_>>();
    if retained_inputs
        .iter()
        .filter(|input| protected.contains(&input.record.record_id))
        .count()
        != protected_live_records
    {
        return Err(QualifiedCompactionError::ProtectedReferenceLost);
    }

    let retained_records = retained_inputs
        .iter()
        .map(|input| input.record.clone())
        .collect::<Vec<_>>();
    let omitted_record_digests = omitted_inputs
        .iter()
        .map(|input| input.record.record_digest())
        .collect::<Vec<_>>();
    let live_source_heads = u64::try_from(live_heads.len()).unwrap_or(u64::MAX);
    let retained_count = u64::try_from(retained_records.len()).unwrap_or(u64::MAX);
    let omitted_count = u64::try_from(omitted_record_digests.len()).unwrap_or(u64::MAX);

    let support_manifest_digest = digest_record_set(
        SUPPORT_MANIFEST_DOMAIN,
        live_heads.iter().map(|input| &input.record),
    );
    let payload_digest = digest_record_set(PAYLOAD_DOMAIN, retained_records.iter());
    let omitted_information_digest = digest_digests(OMITTED_DOMAIN, &omitted_record_digests);
    let mut checkpoint = CompactCheckpointV1 {
        checkpoint_id: StableId::new(format!("compact:{}", generation.get()))
            .map_err(|_| QualifiedCompactionError::InvalidCheckpointIdentity)?,
        generation,
        source_snapshot: source_snapshot.clone(),
        support_manifest_digest,
        algorithm_digest: policy.algorithm_digest,
        payload_digest,
        omitted_information_digest,
        tombstone_cutoff: source_snapshot.vector.tombstone_frontier,
        predecessor_digest: predecessor_checkpoint_digest,
        compatibility_digest: policy.compatibility_digest,
        checkpoint_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    checkpoint.checkpoint_digest = checkpoint.compute_checkpoint_digest();
    checkpoint
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;

    let mut loss_report = CompactionLossReportV2 {
        source_current_heads,
        live_source_heads,
        retained_records: retained_count,
        omitted_live_records: omitted_count,
        deleted_records,
        protected_live_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_retained_records: u64::try_from(protected_live_records).unwrap_or(u64::MAX),
        protected_deleted_records,
        loss_report_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    loss_report.loss_report_digest = loss_report.compute_digest();
    loss_report.validate()?;

    let mut candidate = QualifiedCompactionCandidateV2 {
        source_snapshot,
        policy_digest: policy.digest(),
        retained_records,
        omitted_record_digests,
        checkpoint,
        loss_report,
        candidate_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    candidate.candidate_digest = candidate.compute_candidate_digest();
    candidate.validate()?;
    Ok(candidate)
}

pub fn prove_compaction(
    candidate: &QualifiedCompactionCandidateV2,
    qualification: CompactionQualificationV2,
) -> Result<CompactionProofV1, QualifiedCompactionError> {
    candidate.validate()?;
    for (name, digest) in [
        (
            "retained_query_suite",
            qualification.retained_query_suite_digest,
        ),
        (
            "reconstruction_obligation",
            qualification.reconstruction_obligation_digest,
        ),
        (
            "contradiction_holdout",
            qualification.contradiction_holdout_digest,
        ),
    ] {
        ensure_digest(name, digest)?;
    }
    if !qualification.retained_queries_passed {
        return Err(QualifiedCompactionError::RetainedQueryRegression);
    }
    if !qualification.reconstruction_passed {
        return Err(QualifiedCompactionError::ReconstructionFailed);
    }
    if !qualification.contradictions_preserved {
        return Err(QualifiedCompactionError::ContradictionLoss);
    }
    if !qualification.deletion_non_resurrection_passed {
        return Err(QualifiedCompactionError::DeletionNonResurrectionFailed);
    }
    let mut proof = CompactionProofV1 {
        checkpoint_digest: candidate.checkpoint.checkpoint_digest,
        retained_query_suite_digest: qualification.retained_query_suite_digest,
        reconstruction_obligation_digest: qualification.reconstruction_obligation_digest,
        contradiction_holdout_digest: qualification.contradiction_holdout_digest,
        deletion_cutoff: candidate.checkpoint.tombstone_cutoff,
        source_count: candidate.loss_report.live_source_heads,
        retained_count: candidate.loss_report.retained_records,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_proof_digest();
    proof
        .validate()
        .map_err(QualifiedCompactionError::Contract)?;
    Ok(proof)
}

fn validate_lineage(
    record_id: &StableId,
    lineage: &[CompactionInputRecordV2],
) -> Result<(), QualifiedCompactionError> {
    let mut previous: Option<&MemoryRecord> = None;
    let mut tombstone_seen = false;
    for input in lineage {
        let record = &input.record;
        match previous {
            None => {
                if record.revision.get() != 1 || record.predecessor_digest.is_some() {
                    return Err(QualifiedCompactionError::BrokenLineage(
                        record_id.to_string(),
                    ));
                }
            }
            Some(previous) => {
                if record.revision.get() != previous.revision.get().saturating_add(1)
                    || record.predecessor_digest != Some(previous.record_digest())
                {
                    return Err(QualifiedCompactionError::BrokenLineage(
                        record_id.to_string(),
                    ));
                }
            }
        }
        if tombstone_seen && record.state == RecordState::Live {
            return Err(QualifiedCompactionError::ResurrectionDenied(
                record_id.to_string(),
            ));
        }
        tombstone_seen |= record.state == RecordState::Tombstone;
        previous = Some(record);
    }
    Ok(())
}

fn digest_record_set<'a>(
    domain: &[u8],
    records: impl IntoIterator<Item = &'a MemoryRecord>,
) -> Digest32 {
    let mut digests = records
        .into_iter()
        .map(MemoryRecord::record_digest)
        .collect::<Vec<_>>();
    digests.sort();
    digest_digests(domain, &digests)
}

fn digest_digests(domain: &[u8], digests: &[Digest32]) -> Digest32 {
    let mut digests = digests.to_vec();
    digests.sort();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    push_len(&mut bytes, digests.len());
    for digest in digests {
        push_digest(&mut bytes, digest);
    }
    Digest32::of_bytes(&bytes)
}

fn ensure_unique_ids(values: &[StableId]) -> Result<(), QualifiedCompactionError> {
    let mut seen = BTreeSet::new();
    for value in values {
        if !seen.insert(value.clone()) {
            return Err(QualifiedCompactionError::DuplicateProtectedReference(
                value.to_string(),
            ));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum QualifiedCompactionError {
    Contract(LaneCContractError),
    CanonicalContract(String),
    CanonicalReplayBindingMismatch,
    CanonicalShadowDigestMismatch,
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    InvalidRetentionLimit,
    InputLimitExceeded,
    ProtectedReferenceLimitExceeded,
    DuplicateProtectedReference(String),
    ProtectedReferencesExceedCapacity,
    ProtectedReferenceLost,
    InvalidLossAccounting,
    InvalidRecord(String),
    EmptyLineage,
    BrokenLineage(String),
    ResurrectionDenied(String),
    TombstoneRetained(String),
    DuplicateRetainedRecord(String),
    SnapshotMismatch,
    InvalidCheckpointIdentity,
    RetainedQueryRegression,
    ReconstructionFailed,
    ContradictionLoss,
    DeletionNonResurrectionFailed,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for QualifiedCompactionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for QualifiedCompactionError {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), QualifiedCompactionError> {
    if digest.is_zero() {
        return Err(QualifiedCompactionError::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_raw_id(bytes: &mut Vec<u8>, value: &str) {
    push_len(bytes, value.len());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "qualified_tests.rs"]
mod tests;
