#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(rel: str, old: str, new: str) -> None:
    text = read(rel)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{rel}: expected one occurrence, found {count}: {old[:80]!r}")
    write(rel, text.replace(old, new, 1))


def regex_once(rel: str, pattern: str, replacement: str) -> None:
    text = read(rel)
    rendered, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{rel}: regex matched {count}: {pattern[:100]!r}")
    write(rel, rendered)


def rename_contradiction_fields(rel: str) -> None:
    text = read(rel)
    text = text.replace("contradiction_group_digests", "contradiction_evidence")
    text = text.replace("contradiction_group_digest", "contradiction_evidence")
    write(rel, text)


FIELD_FILES = [
    "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
    "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs",
    "codex-rs/hepta-memory-retrieval/src/generator.rs",
    "codex-rs/hepta-memory-retrieval/src/generator_tests.rs",
    "codex-rs/hepta-memory-retrieval/src/engram.rs",
    "codex-rs/hepta-memory-retrieval/src/engram_tests.rs",
    "codex-rs/hepta-memory-retrieval/src/decision_tests.rs",
    "codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs",
    "codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs",
]
for path in FIELD_FILES:
    rename_contradiction_fields(path)

# ---------------------------------------------------------------------------
# generation_bound: proposition/polarity evidence and policy-admitted risk.
# ---------------------------------------------------------------------------
GB = "codex-rs/hepta-memory-retrieval/src/generation_bound.rs"
replace_once(
    GB,
    """#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCueV1 {""",
    """#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContradictionPolarityV1 {
    Supports,
    Opposes,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContradictionEvidenceV1 {
    pub proposition_digest: Digest32,
    pub polarity: ContradictionPolarityV1,
}

impl ContradictionEvidenceV1 {
    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        ensure_digest("contradiction_proposition", self.proposition_digest)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCueV1 {""",
)
replace_once(GB, "pub contradiction_evidence: Option<Digest32>,", "pub contradiction_evidence: Option<ContradictionEvidenceV1>,")
replace_once(
    GB,
    """        if let Some(group) = self.contradiction_evidence {
            ensure_digest("contradiction_group", group)?;
        }""",
    """        if let Some(evidence) = self.contradiction_evidence {
            evidence.validate()?;
        }""",
)
# Two public receipt surfaces carry canonical evidence sets.
text = read(GB)
text = text.replace("pub contradiction_evidence: Vec<Digest32>,", "pub contradiction_evidence: Vec<ContradictionEvidenceV1>,")
text = text.replace("contradiction_evidence: BTreeSet<Digest32>,", "contradiction_evidence: BTreeSet<ContradictionEvidenceV1>,")
write(GB, text)
replace_once(
    GB,
    """            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|digest| digest.is_zero())
            {
                return Err(RecallErrorV1::NonCanonicalCollection(
                    "union_contradiction_groups",
                ));
            }""",
    """            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
            {
                return Err(RecallErrorV1::NonCanonicalCollection(
                    "union_contradiction_evidence",
                ));
            }""",
)
replace_once(
    GB,
    """            push_len(&mut bytes, entry.contradiction_evidence.len());
            for digest in &entry.contradiction_evidence {
                push_digest(&mut bytes, *digest);
            }""",
    """            push_len(&mut bytes, entry.contradiction_evidence.len());
            for evidence in &entry.contradiction_evidence {
                push_contradiction_evidence(&mut bytes, *evidence);
            }""",
)
replace_once(
    GB,
    """                || !is_strictly_sorted_unique(&selection.contradiction_evidence)
                || selection
                    .contradiction_evidence
                    .iter()
                    .any(|digest| digest.is_zero())""",
    """                || !is_strictly_sorted_unique(&selection.contradiction_evidence)
                || selection
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())""",
)
replace_once(
    GB,
    """            push_len(&mut bytes, selection.contradiction_evidence.len());
            for digest in &selection.contradiction_evidence {
                push_digest(&mut bytes, *digest);
            }""",
    """            push_len(&mut bytes, selection.contradiction_evidence.len());
            for evidence in &selection.contradiction_evidence {
                push_contradiction_evidence(&mut bytes, *evidence);
            }""",
)
replace_once(
    GB,
    """        if let Some(group) = candidate.contradiction_evidence {
            builder.contradiction_evidence.insert(group);
        }""",
    """        if let Some(evidence) = candidate.contradiction_evidence {
            builder.contradiction_evidence.insert(evidence);
        }""",
)
regex_once(
    GB,
    r"pub fn recall\(\n.*?\n\}\n\nstruct UnionBuilder",
    """pub fn recall(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV1, RecallErrorV1> {
    let union = build_candidate_union(cue, policy, candidates)?;
    let admitted = union
        .entries
        .iter()
        .filter(|entry| entry.weighted_score >= policy.minimum_total_score)
        .collect::<Vec<_>>();
    let admitted_channels = admitted
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>();
    let distinct_channels = u32::try_from(admitted_channels.len()).unwrap_or(u32::MAX);
    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let maximum_ood = admitted
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(ProbabilityQ32::ZERO);
    let contradiction_count = contradiction_population_count(admitted.iter().copied());
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if admitted_channels.len() < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if policy.abstain_on_contradiction && contradiction_count > 0 {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new(), 0),
        None => {
            let selections = admitted
                .iter()
                .copied()
                .take(maximum_results)
                .map(|entry| RecallSelectionV1 {
                    record_id: entry.record.record_id.clone(),
                    record_revision: entry.record.revision,
                    record_digest: entry.record.record_digest(),
                    weighted_score: entry.weighted_score,
                    maximum_ood: entry.maximum_ood,
                    channels: entry.channels.clone(),
                    support_digests: entry.support_digests.clone(),
                    contradiction_evidence: entry.contradiction_evidence.clone(),
                })
                .collect::<Vec<_>>();
            let omitted_count = union.entries.len().saturating_sub(selections.len());
            (
                RecallDispositionV1::Recalled,
                selections,
                u32::try_from(omitted_count).unwrap_or(u32::MAX),
            )
        }
    };
    let mut packet = RecallPacketV1 {
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        candidate_union_digest: union.union_digest,
        generation_vector_digest: union.generation_vector_digest,
        disposition,
        selections,
        omitted_count,
        distinct_channels,
        engram: None,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate()?;
    Ok(packet)
}

struct UnionBuilder""",
)
regex_once(
    GB,
    r"fn contradiction_population_count\(.*?\n\}\n\n#\[derive\(Clone, Debug, Eq, PartialEq\)\]\npub enum RecallErrorV1",
    """pub(crate) fn contradiction_population_count<'a>(
    entries: impl IntoIterator<Item = &'a CandidateUnionEntryV1>,
) -> usize {
    let mut populations = BTreeMap::<Digest32, u8>::new();
    for entry in entries {
        for evidence in &entry.contradiction_evidence {
            let mask = match evidence.polarity {
                ContradictionPolarityV1::Supports => 0b01,
                ContradictionPolarityV1::Opposes => 0b10,
            };
            *populations.entry(evidence.proposition_digest).or_insert(0) |= mask;
        }
    }
    populations.values().filter(|mask| **mask == 0b11).count()
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RecallErrorV1""",
)
replace_once(
    GB,
    """fn push_recall_disposition(bytes: &mut Vec<u8>, value: RecallDispositionV1) {""",
    """fn push_contradiction_evidence(bytes: &mut Vec<u8>, value: ContradictionEvidenceV1) {
    push_digest(bytes, value.proposition_digest);
    bytes.push(match value.polarity {
        ContradictionPolarityV1::Supports => 0,
        ContradictionPolarityV1::Opposes => 1,
    });
}

fn push_recall_disposition(bytes: &mut Vec<u8>, value: RecallDispositionV1) {""",
)
replace_once(
    GB,
    """        if let Some(engram) = &self.engram
            && self.disposition == RecallDispositionV1::Recalled
            && usize::try_from(engram.resources.candidate_records).unwrap_or(usize::MAX)
                != candidate_count
        {
            return Err(RecallErrorV1::InvalidEngram(
                "engram candidate count differs from recall packet".to_string(),
            ));
        }""",
    """        if let Some(engram) = &self.engram
            && self.disposition == RecallDispositionV1::Recalled
        {
            let engram_candidate_count =
                usize::try_from(engram.resources.candidate_records).unwrap_or(usize::MAX);
            if engram_candidate_count > candidate_count
                || engram_candidate_count < self.selections.len()
            {
                return Err(RecallErrorV1::InvalidEngram(
                    "engram admitted candidate count is inconsistent with recall packet"
                        .to_string(),
                ));
            }
        }""",
)

# Public exports for the new typed contradiction evidence.
LIB = "codex-rs/hepta-memory-retrieval/src/lib.rs"
replace_once(
    LIB,
    "pub use generation_bound::CandidateUnionEntryV1;",
    "pub use generation_bound::CandidateUnionEntryV1;\npub use generation_bound::ContradictionEvidenceV1;\npub use generation_bound::ContradictionPolarityV1;",
)

# ---------------------------------------------------------------------------
# generator: preserve typed evidence through owner receipts and merging.
# ---------------------------------------------------------------------------
GEN = "codex-rs/hepta-memory-retrieval/src/generator.rs"
replace_once(
    GEN,
    "use crate::CandidateUnionV1;",
    "use crate::CandidateUnionV1;\nuse crate::ContradictionEvidenceV1;",
)
replace_once(
    GEN,
    """            if let Some(group) = candidate.contradiction_evidence {
                ensure_digest("generator_contradiction_group", group)?;
            }""",
    """            if let Some(evidence) = candidate.contradiction_evidence {
                evidence.validate().map_err(GeneratorErrorV1::Recall)?;
            }""",
)
replace_once(GEN, "contradiction_evidence: Option<Digest32>,", "contradiction_evidence: Option<ContradictionEvidenceV1>,")

# ---------------------------------------------------------------------------
# SQLite owner adapter: contradiction support is one-sided evidence about the
# exact request proposition. Multiple same-side records therefore do not conflict.
# ---------------------------------------------------------------------------
ADAPTER = "codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs"
replace_once(
    ADAPTER,
    "use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;",
    "use codex_hepta_memory_retrieval::ContradictionEvidenceV1;\nuse codex_hepta_memory_retrieval::ContradictionPolarityV1;\nuse codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;",
)
text = read(ADAPTER).replace(
    'const OWNER_CONTRADICTION_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-contradiction-group.v1";\n',
    "",
)
write(ADAPTER, text)
replace_once(
    ADAPTER,
    """    let generated = generated_input_from_owner_observation(
        observation,
        authoritative.snapshot_key(),
        authoritative.snapshot(),
    )?;""",
    """    let generated = generated_input_from_owner_observation(
        observation,
        authoritative.snapshot_key(),
        authoritative.snapshot(),
        request_digest,
    )?;""",
)
replace_once(
    ADAPTER,
    """pub(crate) fn generated_input_from_owner_observation(
    observation: &RetrievalObservation,
    snapshot_key: &CognitiveSnapshotKeyV1,
    snapshot: &CognitiveSnapshot,
) -> Result<GeneratedCandidateInputV1, CognitiveStoreError> {""",
    """pub(crate) fn generated_input_from_owner_observation(
    observation: &RetrievalObservation,
    snapshot_key: &CognitiveSnapshotKeyV1,
    snapshot: &CognitiveSnapshot,
    request_digest: Digest32,
) -> Result<GeneratedCandidateInputV1, CognitiveStoreError> {""",
)
replace_once(
    ADAPTER,
    """    snapshot_key
        .validate()
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;""",
    """    snapshot_key
        .validate()
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
    if request_digest.is_zero() {
        return Err(CognitiveStoreError::Invalid(
            "retrieval request proposition digest must be non-zero".to_string(),
        ));
    }""",
)
replace_once(
    ADAPTER,
    """                contradiction_evidence: (semantic_channel
                    == RetrievalChannelV1::ContradictionSupport)
                    .then(|| owner_contradiction_evidence(owner_observation_digest)),""",
    """                contradiction_evidence: (semantic_channel
                    == RetrievalChannelV1::ContradictionSupport)
                    .then_some(ContradictionEvidenceV1 {
                        proposition_digest: request_digest,
                        polarity: ContradictionPolarityV1::Opposes,
                    }),""",
)
regex_once(
    ADAPTER,
    r"\nfn owner_contradiction_evidence\(observation_digest: Digest32\) -> Digest32 \{.*?\n\}\n",
    "\n",
)
AT = "codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs"
text = read(AT)
text, count = re.subn(
    r"generated_input_from_owner_observation\(\s*&observation,\s*&snapshot_key,\s*cut\.snapshot\(\),\s*\)",
    'generated_input_from_owner_observation(\n            &observation,\n            &snapshot_key,\n            cut.snapshot(),\n            Digest32::of_bytes(b"test-retrieval-proposition"),\n        )',
    text,
    flags=re.S,
)
if count != 3:
    raise RuntimeError(f"{AT}: expected three adapter test calls, found {count}")
write(AT, text)

# ---------------------------------------------------------------------------
# engram: positive activation only, zero-weight no-op, admitted-set settling,
# and activation-weighted confidence.
# ---------------------------------------------------------------------------
ENG = "codex-rs/hepta-memory-retrieval/src/engram.rs"
replace_once(
    ENG,
    "use crate::build_candidate_union;",
    "use crate::build_candidate_union;\nuse crate::generation_bound::contradiction_population_count;",
)
replace_once(
    ENG,
    """        for (name, value) in [
            ("leak", self.leak),
            ("lateral_inhibition", self.lateral_inhibition),
            ("minimum_activation", self.minimum_activation),
        ] {
            if value < FixedQ32::ZERO || value > FixedQ32::ONE {
                return Err(EngramErrorV1::ScoreOutOfRange(name));
            }
        }
        Ok(())""",
    """        for (name, value) in [
            ("leak", self.leak),
            ("lateral_inhibition", self.lateral_inhibition),
        ] {
            if value < FixedQ32::ZERO || value > FixedQ32::ONE {
                return Err(EngramErrorV1::ScoreOutOfRange(name));
            }
        }
        if self.minimum_activation <= FixedQ32::ZERO
            || self.minimum_activation > FixedQ32::ONE
        {
            return Err(EngramErrorV1::ScoreOutOfRange("minimum_activation"));
        }
        Ok(())""",
)
replace_once(
    ENG,
    "if node.activation < FixedQ32::ZERO || node.activation > FixedQ32::ONE {",
    "if node.activation <= FixedQ32::ZERO || node.activation > FixedQ32::ONE {",
)
replace_once(
    ENG,
    """pub fn settle_engram(
    cue: &MemoryCueV1,
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,
    policy: &EngramDynamicsPolicyV1,
) -> Result<EngramRecallReceiptV1, EngramErrorV1> {""",
    """pub fn settle_engram(
    cue: &MemoryCueV1,
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,
    policy: &EngramDynamicsPolicyV1,
) -> Result<EngramRecallReceiptV1, EngramErrorV1> {
    settle_engram_with_floor(cue, union, snapshot, policy, FixedQ32::ZERO)
}

fn settle_engram_with_floor(
    cue: &MemoryCueV1,
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,
    policy: &EngramDynamicsPolicyV1,
    minimum_total_score: FixedQ32,
) -> Result<EngramRecallReceiptV1, EngramErrorV1> {""",
)
replace_once(
    ENG,
    """    let candidate_scores = union
        .entries
        .iter()
        .map(|entry| {""",
    """    let candidate_scores = union
        .entries
        .iter()
        .filter(|entry| entry.weighted_score >= minimum_total_score)
        .map(|entry| {""",
)
replace_once(
    ENG,
    "return empty_receipt(union, snapshot, policy);",
    "return empty_receipt(candidate_scores.len(), snapshot, policy);",
)
replace_once(
    ENG,
    """    for synapse in &snapshot.synapses {
        if expanded.contains(&synapse.source_node_id) && expanded.contains(&synapse.target_node_id)
        {""",
    """    for synapse in &snapshot.synapses {
        if synapse.weight != FixedQ32::ZERO
            && expanded.contains(&synapse.source_node_id)
            && expanded.contains(&synapse.target_node_id)
        {""",
)
replace_once(
    ENG,
    """            (*activation >= policy.minimum_activation).then_some((node_id, activation))""",
    """            (*activation > FixedQ32::ZERO && *activation >= policy.minimum_activation)
                .then_some((node_id, activation))""",
)
replace_once(
    ENG,
    """            synapse.relation == SynapseRelationV1::Contradicts
                && active_ids.contains(&synapse.source_node_id)""",
    """            synapse.relation == SynapseRelationV1::Contradicts
                && synapse.weight != FixedQ32::ZERO
                && active_ids.contains(&synapse.source_node_id)""",
)
replace_once(
    ENG,
    "candidate_records: u32::try_from(union.entries.len()).unwrap_or(u32::MAX),",
    "candidate_records: u32::try_from(candidate_scores.len()).unwrap_or(u32::MAX),",
)
regex_once(
    ENG,
    r"pub fn recall_with_engram\(\n.*?\n\}\n\nfn empty_receipt",
    """pub fn recall_with_engram(
    cue: &MemoryCueV1,
    retrieval_policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
    engram_snapshot: &EngramSnapshotV1,
    dynamics_policy: &EngramDynamicsPolicyV1,
) -> Result<RecallPacketV1, EngramErrorV1> {
    cue.validate().map_err(EngramErrorV1::Recall)?;
    retrieval_policy.validate().map_err(EngramErrorV1::Recall)?;
    let union =
        build_candidate_union(cue, retrieval_policy, candidates).map_err(EngramErrorV1::Recall)?;
    let admitted = union
        .entries
        .iter()
        .filter(|entry| entry.weighted_score >= retrieval_policy.minimum_total_score)
        .collect::<Vec<_>>();
    let admitted_channels = admitted
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>();
    let distinct_channels = u32::try_from(admitted_channels.len()).unwrap_or(u32::MAX);
    let engram = settle_engram_with_floor(
        cue,
        &union,
        engram_snapshot,
        dynamics_policy,
        retrieval_policy.minimum_total_score,
    )?;

    let minimum_channels =
        usize::try_from(retrieval_policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let maximum_ood = admitted
        .iter()
        .map(|entry| entry.maximum_ood)
        .max()
        .unwrap_or(ProbabilityQ32::ZERO);
    let contradiction = !engram.contradictions.is_empty()
        || contradiction_population_count(admitted.iter().copied()) > 0;
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if engram.selected_support.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted_channels.len() < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if contradiction
        && (retrieval_policy.abstain_on_contradiction
            || dynamics_policy.contradiction_forces_abstention)
    {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else if maximum_ood > retrieval_policy.maximum_ood {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else {
        None
    };

    let maximum_results = usize::try_from(retrieval_policy.maximum_results).unwrap_or(0);
    let active_strength = active_support_strength(&engram);
    let (disposition, selections, omitted_count) = if let Some(reason) = reason {
        (RecallDispositionV1::Abstained(reason), Vec::new(), 0)
    } else {
        let mut ranked = admitted
            .iter()
            .filter_map(|entry| {
                let support = support_for_entry(entry);
                active_strength
                    .get(&support)
                    .copied()
                    .map(|activation| (*entry, activation))
            })
            .collect::<Vec<_>>();
        ranked.sort_by(|(left, left_activation), (right, right_activation)| {
            right_activation
                .cmp(left_activation)
                .then_with(|| right.weighted_score.cmp(&left.weighted_score))
                .then_with(|| left.record.record_id.cmp(&right.record.record_id))
                .then_with(|| left.record.revision.cmp(&right.record.revision))
        });
        let selections = ranked
            .iter()
            .take(maximum_results)
            .map(|(entry, _)| RecallSelectionV1 {
                record_id: entry.record.record_id.clone(),
                record_revision: entry.record.revision,
                record_digest: entry.record.record_digest(),
                weighted_score: entry.weighted_score,
                maximum_ood: entry.maximum_ood,
                channels: entry.channels.clone(),
                support_digests: entry.support_digests.clone(),
                contradiction_evidence: entry.contradiction_evidence.clone(),
            })
            .collect::<Vec<_>>();
        if selections.is_empty() {
            (
                RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ScoreBelowFloor),
                Vec::new(),
                0,
            )
        } else {
            let omitted_count = u32::try_from(union.entries.len().saturating_sub(selections.len()))
                .unwrap_or(u32::MAX);
            (RecallDispositionV1::Recalled, selections, omitted_count)
        }
    };

    let mut packet = RecallPacketV1 {
        cue_digest: union.cue_digest,
        policy_digest: union.policy_digest,
        candidate_union_digest: union.union_digest,
        generation_vector_digest: union.generation_vector_digest,
        disposition,
        selections,
        omitted_count,
        distinct_channels,
        engram: Some(engram),
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate().map_err(EngramErrorV1::Recall)?;
    Ok(packet)
}

fn empty_receipt""",
)
replace_once(
    ENG,
    """fn empty_receipt(
    union: &CandidateUnionV1,
    snapshot: &EngramSnapshotV1,""",
    """fn empty_receipt(
    candidate_records: usize,
    snapshot: &EngramSnapshotV1,""",
)
replace_once(
    ENG,
    "candidate_records: u32::try_from(union.entries.len()).unwrap_or(u32::MAX),",
    "candidate_records: u32::try_from(candidate_records).unwrap_or(u32::MAX),",
)
replace_once(
    ENG,
    """        for synapse in &snapshot.synapses {
            let mut consider = Vec::new();""",
    """        for synapse in &snapshot.synapses {
            if synapse.weight == FixedQ32::ZERO {
                continue;
            }
            let mut consider = Vec::new();""",
)
regex_once(
    ENG,
    r"fn active_confidence\(active_nodes: &\[ActiveEngramNodeV1\]\) -> Result<ProbabilityQ32, EngramErrorV1> \{.*?\n\}\n\nfn ratio_probability",
    """fn active_confidence(active_nodes: &[ActiveEngramNodeV1]) -> Result<ProbabilityQ32, EngramErrorV1> {
    if active_nodes.is_empty() {
        return Ok(ProbabilityQ32::ZERO);
    }
    let (weighted_confidence, total_activation) = active_nodes.iter().try_fold(
        (0_u128, 0_u128),
        |(weighted, activation), node| {
            let node_activation = u128::try_from(node.activation.raw())
                .map_err(|_| EngramErrorV1::Arithmetic)?;
            if node_activation == 0 {
                return Err(EngramErrorV1::Arithmetic);
            }
            Ok((
                weighted
                    .checked_add(
                        u128::from(node.confidence.raw())
                            .checked_mul(node_activation)
                            .ok_or(EngramErrorV1::Arithmetic)?,
                    )
                    .ok_or(EngramErrorV1::Arithmetic)?,
                activation
                    .checked_add(node_activation)
                    .ok_or(EngramErrorV1::Arithmetic)?,
            ))
        },
    )?;
    let average = weighted_confidence
        .checked_div(total_activation)
        .ok_or(EngramErrorV1::Arithmetic)?;
    ProbabilityQ32::from_raw(u64::try_from(average).map_err(|_| EngramErrorV1::Arithmetic)?)
        .map_err(|_| EngramErrorV1::Arithmetic)
}

fn ratio_probability""",
)
# The typed helper now lives in generation_bound and is shared by both recall paths.
regex_once(
    ENG,
    r"\nfn contradiction_population_count\(entries: &\[CandidateUnionEntryV1\]\) -> usize \{.*?\n\}\n\nfn abs_fixed",
    "\nfn abs_fixed",
)

# ---------------------------------------------------------------------------
# Focused regression and property tests.
# ---------------------------------------------------------------------------
GBT = "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs"
regex_once(
    GBT,
    r"#\[test\]\nfn high_risk_contradiction_forces_abstention\(\) \{.*?\n\}\n\n#\[test\]\nfn stale_generation_candidate",
    """#[test]
fn opposite_polarity_for_one_proposition_forces_abstention() {
    let cue = cue();
    let policy = policy();
    let proposition = digest("contradiction-proposition");
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Supports,
    });
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    });
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("valid abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::ContradictoryEvidence)
    );
    assert!(packet.selections.is_empty());
}

#[test]
fn stale_generation_candidate""",
)
insert = """
#[test]
fn multiple_same_side_contradiction_support_records_do_not_abstain() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    let proposition = digest("same-side-proposition");
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    });
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    });
    let packet = recall(&cue, &policy, vec![first, second]).expect("same-side evidence");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
}

#[test]
fn low_score_ood_and_opposite_evidence_cannot_poison_admitted_result() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 30);
    let proposition = digest("admitted-proposition");
    let mut high = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    high.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Supports,
    });
    let baseline = recall(&cue, &policy, vec![high.clone()]).expect("baseline");

    let mut low = candidate(record(2), RetrievalChannelV1::Entity, 1);
    low.normalized_score = FixedQ32::from_raw(1);
    low.ood = ProbabilityQ32::ONE;
    low.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    });
    let with_low = recall(&cue, &policy, vec![low, high]).expect("admitted recall");
    assert_eq!(with_low.disposition, RecallDispositionV1::Recalled);
    assert_eq!(with_low.selections, baseline.selections);
    assert_eq!(with_low.distinct_channels, baseline.distinct_channels);
    assert_eq!(with_low.omitted_count, 1);
}

#[test]
fn property_legal_policy_matrix_is_permutation_invariant_and_monotone_below_floor() {
    for maximum_results in [1_u32, 2, 3] {
        for floor in [1_i64, 1_i64 << 28, 1_i64 << 30] {
            let cue = cue();
            let mut policy = policy();
            policy.maximum_results = maximum_results;
            policy.minimum_distinct_channels = 1;
            policy.minimum_total_score = FixedQ32::from_raw(floor);
            policy.validate().expect("legal policy");
            let high = candidate(record(1), RetrievalChannelV1::Lexical, 1);
            let medium = candidate(record(2), RetrievalChannelV1::Entity, 1);
            let baseline = recall(&cue, &policy, vec![high.clone(), medium.clone()])
                .expect("baseline");
            let mut low = candidate(record(3), RetrievalChannelV1::ContradictionSupport, 1);
            low.normalized_score = FixedQ32::ZERO;
            low.ood = ProbabilityQ32::ONE;
            let left = recall(&cue, &policy, vec![high.clone(), medium.clone(), low.clone()])
                .expect("left");
            let right = recall(&cue, &policy, vec![low, medium, high]).expect("right");
            assert_eq!(left, right);
            assert_eq!(left.disposition, baseline.disposition);
            assert_eq!(left.selections, baseline.selections);
        }
    }
}

"""
replace_once(GBT, "fn next_permutation(values: &mut [usize]) -> bool {", insert + "fn next_permutation(values: &mut [usize]) -> bool {")

ET = "codex-rs/hepta-memory-retrieval/src/engram_tests.rs"
engram_tests = """
#[test]
fn zero_minimum_activation_is_rejected_and_zero_activation_is_never_active() {
    let mut policy = EngramDynamicsPolicyV1::product_default().expect("policy");
    policy.minimum_activation = FixedQ32::ZERO;
    assert_eq!(
        policy.validate(),
        Err(EngramErrorV1::ScoreOutOfRange("minimum_activation"))
    );

    let cue = cue();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("zero-activation-generation"),
        vec![node(
            "node:zero",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ONE,
        )],
        Vec::new(),
    )
    .expect("snapshot");
    let union = build_candidate_union(
        &cue,
        &retrieval_policy(1),
        vec![candidate(1, FixedQ32::ONE.raw())],
    )
    .expect("union");
    let receipt = settle_engram(
        &cue,
        &union,
        &snapshot,
        &EngramDynamicsPolicyV1::product_default().expect("policy"),
    )
    .expect("settle");
    assert!(receipt.active_nodes.is_empty());
    assert!(receipt.selected_support.is_empty());
}

#[test]
fn zero_weight_contradiction_edge_is_a_semantic_noop() {
    let cue = cue();
    let candidates = vec![
        candidate(1, FixedQ32::ONE.raw()),
        candidate(2, FixedQ32::ONE.raw()),
    ];
    let nodes = vec![
        node(
            "node:left-zero",
            EngramPopulationV1::SemanticConcept,
            vec![support(1)],
            FixedQ32::ZERO,
        ),
        node(
            "node:right-zero",
            EngramPopulationV1::SemanticConcept,
            vec![support(2)],
            FixedQ32::ZERO,
        ),
    ];
    let plain = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("zero-edge-plain"),
        nodes.clone(),
        Vec::new(),
    )
    .expect("plain snapshot");
    let with_zero = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("zero-edge-present"),
        nodes,
        vec![synapse(
            "node:left-zero",
            "node:right-zero",
            SynapseRelationV1::Contradicts,
            FixedQ32::ZERO,
        )],
    )
    .expect("zero snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let left = recall_with_engram(
        &cue,
        &retrieval_policy(2),
        candidates.clone(),
        &plain,
        &dynamics,
    )
    .expect("plain recall");
    let right = recall_with_engram(
        &cue,
        &retrieval_policy(2),
        candidates,
        &with_zero,
        &dynamics,
    )
    .expect("zero-edge recall");
    assert_eq!(left.disposition, right.disposition);
    assert_eq!(left.selections, right.selections);
    assert!(right.engram.as_ref().expect("engram").contradictions.is_empty());
}

#[test]
fn active_confidence_is_activation_weighted() {
    let active = vec![
        ActiveEngramNodeV1 {
            node_id: id("node:strong"),
            population: EngramPopulationV1::SemanticConcept,
            activation: FixedQ32::from_raw(3_i64 << 30),
            confidence: ProbabilityQ32::ONE,
            support: vec![support(1)],
        },
        ActiveEngramNodeV1 {
            node_id: id("node:weak"),
            population: EngramPopulationV1::SemanticConcept,
            activation: FixedQ32::from_raw(1_i64 << 30),
            confidence: ProbabilityQ32::ZERO,
            support: vec![support(2)],
        },
    ];
    assert_eq!(
        active_confidence(&active).expect("confidence"),
        ProbabilityQ32::from_raw(3_u64 << 30).expect("probability")
    );
}

#[test]
fn low_score_candidate_cannot_activate_or_contradict_admitted_hnmf_result() {
    let cue = cue();
    let mut retrieval = retrieval_policy(2);
    retrieval.minimum_total_score = FixedQ32::from_raw(1_i64 << 30);
    let high = candidate(1, FixedQ32::ONE.raw());
    let mut low = candidate(2, 1);
    low.ood = ProbabilityQ32::ONE;
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("admitted-hnmf-generation"),
        vec![
            node(
                "node:admitted",
                EngramPopulationV1::SemanticConcept,
                vec![support(1)],
                FixedQ32::ZERO,
            ),
            node(
                "node:below-floor",
                EngramPopulationV1::SemanticConcept,
                vec![support(2)],
                FixedQ32::ZERO,
            ),
        ],
        vec![synapse(
            "node:admitted",
            "node:below-floor",
            SynapseRelationV1::Contradicts,
            FixedQ32::ONE,
        )],
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.maximum_graph_hops = 0;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let packet = recall_with_engram(&cue, &retrieval, vec![low, high], &snapshot, &dynamics)
        .expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 1);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    let receipt = packet.engram.as_ref().expect("engram");
    assert_eq!(receipt.resources.candidate_records, 1);
    assert!(receipt.contradictions.is_empty());
}

"""
replace_once(
    ET,
    "#[test]\n#[ignore = \"target-host qualification probe; run explicitly with --ignored --nocapture\"]",
    engram_tests + "#[test]\n#[ignore = \"target-host qualification probe; run explicitly with --ignored --nocapture\"]",
)

GT = "codex-rs/hepta-memory-retrieval/src/generator_tests.rs"
append = """

#[test]
fn property_generator_receipt_count_always_matches_candidate_capacity() {
    for count in 0_usize..=16 {
        let candidates = (0..count)
            .map(|index| {
                candidate(
                    record(u64::try_from(index + 1).expect("index")),
                    RetrievalChannelV1::Lexical,
                    u32::try_from(index + 1).expect("rank"),
                    &format!("support-{index}"),
                )
            })
            .collect::<Vec<_>>();
        let batch = batch(
            RetrievalGeneratorOwnerV1::CognitiveLexical,
            candidates,
            RetrievalSourceCompletenessV1::Exhausted,
        );
        batch.validate().expect("count-consistent batch");
        assert_eq!(
            usize::try_from(batch.receipt.candidate_count).expect("count"),
            batch.candidates.len()
        );
    }
}
"""
text = read(GT)
if append.strip() not in text:
    write(GT, text + append)

print("memory.retrieval semantic hardening patch applied")
