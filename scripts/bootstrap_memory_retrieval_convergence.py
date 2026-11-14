#!/usr/bin/env python3
"""Apply phase-one memory.retrieval semantic convergence edits.

This bootstrap is intentionally exact: every structural replacement asserts the
expected parent text so source drift fails before compilation.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def save(relative: str, text: str) -> None:
    (ROOT / relative).write_text(text, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    text = load(relative)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one replacement, found {count}: {old[:120]!r}")
    save(relative, text.replace(old, new, 1))


def replace_between(relative: str, start: str, end: str, replacement: str) -> None:
    text = load(relative)
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{relative}: missing start marker {start!r}")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{relative}: missing end marker {end!r}")
    if text.find(start, start_index + 1) >= 0 and text.find(start, start_index + 1) < end_index:
        raise RuntimeError(f"{relative}: ambiguous start marker {start!r}")
    save(relative, text[:start_index] + replacement + text[end_index:])


def rename_contradiction_fields() -> None:
    files = [
        "codex-rs/hepta-memory-retrieval/src/generation_bound.rs",
        "codex-rs/hepta-memory-retrieval/src/generator.rs",
        "codex-rs/hepta-memory-retrieval/src/engram.rs",
        "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs",
        "codex-rs/hepta-memory-retrieval/src/generator_tests.rs",
        "codex-rs/hepta-memory-retrieval/src/engram_tests.rs",
        "codex-rs/hepta-memory-retrieval/src/decision_tests.rs",
        "codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs",
        "codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs",
        "codex-rs/hepta-agentd/src/cognitive_retrieval_learning_tests.rs",
    ]
    for relative in files:
        text = load(relative)
        text = text.replace("contradiction_group_digests", "contradiction_evidence")
        text = text.replace("contradiction_group_digest", "contradiction_evidence")
        text = text.replace("ContradictionGroup", "ContradictionEvidence")
        save(relative, text)


def patch_generation_bound() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/generation_bound.rs"
    text = load(relative)
    text = text.replace(
        'const CANDIDATE_UNION_DOMAIN: &[u8] = b"hepta.retrieval-candidate-union.v1";',
        'const CANDIDATE_UNION_DOMAIN: &[u8] = b"hepta.retrieval-candidate-union.v2";',
    )
    text = text.replace(
        'const RECALL_PACKET_DOMAIN: &[u8] = b"hepta.recall-packet.v1";',
        'const RECALL_PACKET_DOMAIN: &[u8] = b"hepta.recall-packet.v2";',
    )
    marker = "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct MemoryCueV1 {"
    if text.count(marker) != 1:
        raise RuntimeError("generation_bound.rs: MemoryCue marker drift")
    contradiction_types = r'''#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContradictionPolarityV1 {
    Supports,
    Opposes,
}

/// Proposition-scoped contradiction evidence. Two records conflict only when
/// they bind the same proposition and carry opposite polarities. Multiple
/// independent records on the same side are corroboration, not contradiction.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct ContradictionEvidenceV1 {
    pub proposition_digest: Digest32,
    pub polarity: ContradictionPolarityV1,
}

impl ContradictionEvidenceV1 {
    pub(crate) fn validate(&self) -> Result<(), RecallErrorV1> {
        ensure_digest("contradiction_proposition", self.proposition_digest)
    }
}

'''
    text = text.replace(marker, contradiction_types + marker, 1)
    text = text.replace(
        "pub contradiction_evidence: Option<Digest32>,",
        "pub contradiction_evidence: Option<ContradictionEvidenceV1>,",
    )
    text = text.replace(
        "pub contradiction_evidence: Vec<Digest32>,",
        "pub contradiction_evidence: Vec<ContradictionEvidenceV1>,",
    )
    save(relative, text)

    replace_once(
        relative,
        '''        if let Some(group) = self.contradiction_evidence {
            ensure_digest("contradiction_group", group)?;
        }
''',
        '''        if let Some(evidence) = self.contradiction_evidence {
            evidence.validate()?;
        }
''',
    )
    replace_once(
        relative,
        '''            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|digest| digest.is_zero())
            {
''',
        '''            if !is_strictly_sorted_unique(&entry.contradiction_evidence)
                || entry
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
            {
''',
    )
    replace_once(
        relative,
        '''            push_len(&mut bytes, entry.contradiction_evidence.len());
            for digest in &entry.contradiction_evidence {
                push_digest(&mut bytes, *digest);
            }
''',
        '''            push_len(&mut bytes, entry.contradiction_evidence.len());
            for evidence in &entry.contradiction_evidence {
                push_digest(&mut bytes, evidence.proposition_digest);
                bytes.push(contradiction_polarity_code(evidence.polarity));
            }
''',
    )
    replace_once(
        relative,
        '''                || !is_strictly_sorted_unique(&selection.contradiction_evidence)
                || selection
                    .contradiction_evidence
                    .iter()
                    .any(|digest| digest.is_zero())
''',
        '''                || !is_strictly_sorted_unique(&selection.contradiction_evidence)
                || selection
                    .contradiction_evidence
                    .iter()
                    .any(|evidence| evidence.validate().is_err())
''',
    )
    replace_once(
        relative,
        '''            push_len(&mut bytes, selection.contradiction_evidence.len());
            for digest in &selection.contradiction_evidence {
                push_digest(&mut bytes, *digest);
            }
''',
        '''            push_len(&mut bytes, selection.contradiction_evidence.len());
            for evidence in &selection.contradiction_evidence {
                push_digest(&mut bytes, evidence.proposition_digest);
                bytes.push(contradiction_polarity_code(evidence.polarity));
            }
''',
    )
    replace_once(
        relative,
        "    contradiction_evidence: BTreeSet<Digest32>,",
        "    contradiction_evidence: BTreeSet<ContradictionEvidenceV1>,",
    )
    replace_once(
        relative,
        '''        if let Some(group) = candidate.contradiction_evidence {
            builder.contradiction_evidence.insert(group);
        }
''',
        '''        if let Some(evidence) = candidate.contradiction_evidence {
            builder.contradiction_evidence.insert(evidence);
        }
''',
    )
    replace_once(
        relative,
        '''        if let Some(engram) = &self.engram
            && self.disposition == RecallDispositionV1::Recalled
            && usize::try_from(engram.resources.candidate_records).unwrap_or(usize::MAX)
                != candidate_count
        {
            return Err(RecallErrorV1::InvalidEngram(
                "engram candidate count differs from recall packet".to_string(),
            ));
        }
''',
        '''        if let Some(engram) = &self.engram
            && self.disposition == RecallDispositionV1::Recalled
        {
            let engram_candidates =
                usize::try_from(engram.resources.candidate_records).unwrap_or(usize::MAX);
            if engram_candidates < self.selections.len() || engram_candidates > candidate_count {
                return Err(RecallErrorV1::InvalidEngram(
                    "engram candidate count is outside the admitted/full candidate bounds"
                        .to_string(),
                ));
            }
        }
''',
    )

    recall_block = r'''pub(crate) fn score_admitted_entries<'a>(
    entries: &'a [CandidateUnionEntryV1],
    policy: &RetrievalPolicyV1,
) -> Vec<&'a CandidateUnionEntryV1> {
    entries
        .iter()
        .filter(|entry| entry.weighted_score >= policy.minimum_total_score)
        .collect()
}

pub(crate) fn risk_admitted_entries<'a>(
    entries: &[&'a CandidateUnionEntryV1],
    policy: &RetrievalPolicyV1,
) -> Vec<&'a CandidateUnionEntryV1> {
    entries
        .iter()
        .copied()
        .filter(|entry| entry.maximum_ood <= policy.maximum_ood)
        .collect()
}

pub(crate) fn admitted_distinct_channel_count(entries: &[&CandidateUnionEntryV1]) -> usize {
    entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>()
        .len()
}

pub fn recall(
    cue: &MemoryCueV1,
    policy: &RetrievalPolicyV1,
    candidates: Vec<RetrievalChannelCandidateV1>,
) -> Result<RecallPacketV1, RecallErrorV1> {
    let union = build_candidate_union(cue, policy, candidates)?;
    let score_admitted = score_admitted_entries(&union.entries, policy);
    let admitted = risk_admitted_entries(&score_admitted, policy);
    let minimum_channels = usize::try_from(policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let admitted_channels = admitted_distinct_channel_count(&admitted);
    let contradiction_count = contradiction_population_count(&admitted);
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if score_admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if admitted_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if policy.abstain_on_contradiction && contradiction_count > 0 {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else {
        None
    };

    let maximum_results = usize::try_from(policy.maximum_results).unwrap_or(0);
    let (disposition, selections, omitted_count) = match reason {
        Some(reason) => (RecallDispositionV1::Abstained(reason), Vec::new(), 0),
        None => {
            let selections = admitted
                .iter()
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
        distinct_channels: u32::try_from(admitted_channels).unwrap_or(u32::MAX),
        engram: None,
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate()?;
    Ok(packet)
}

'''
    replace_between(relative, "pub fn recall(\n", "struct UnionBuilder {", recall_block)

    contradiction_fn = r'''pub(crate) fn contradiction_population_count(
    entries: &[&CandidateUnionEntryV1],
) -> usize {
    let mut populations = BTreeMap::<Digest32, u8>::new();
    for entry in entries {
        for evidence in &entry.contradiction_evidence {
            let flag = match evidence.polarity {
                ContradictionPolarityV1::Supports => 1,
                ContradictionPolarityV1::Opposes => 2,
            };
            *populations.entry(evidence.proposition_digest).or_insert(0) |= flag;
        }
    }
    populations.values().filter(|flags| **flags == 3).count()
}

'''
    replace_between(
        relative,
        "fn contradiction_population_count(",
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum RecallErrorV1",
        contradiction_fn,
    )
    replace_once(
        relative,
        '''const fn abstention_reason_code(value: RecallAbstentionReasonV1) -> u8 {
''',
        '''const fn contradiction_polarity_code(value: ContradictionPolarityV1) -> u8 {
    match value {
        ContradictionPolarityV1::Supports => 0,
        ContradictionPolarityV1::Opposes => 1,
    }
}

const fn abstention_reason_code(value: RecallAbstentionReasonV1) -> u8 {
''',
    )


def patch_generator() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/generator.rs"
    replace_once(
        relative,
        "use crate::CandidateUnionV1;\n",
        "use crate::CandidateUnionV1;\nuse crate::ContradictionEvidenceV1;\n",
    )
    replace_once(
        relative,
        '''            if let Some(group) = candidate.contradiction_evidence {
                ensure_digest("generator_contradiction_group", group)?;
            }
''',
        '''            if let Some(evidence) = candidate.contradiction_evidence {
                ensure_digest(
                    "generator_contradiction_proposition",
                    evidence.proposition_digest,
                )?;
            }
''',
    )
    replace_once(
        relative,
        "    contradiction_evidence: Option<Digest32>,",
        "    contradiction_evidence: Option<ContradictionEvidenceV1>,",
    )


def patch_engram() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/engram.rs"
    replace_once(
        relative,
        "use crate::build_candidate_union;\n",
        '''use crate::build_candidate_union;
use crate::generation_bound::admitted_distinct_channel_count;
use crate::generation_bound::contradiction_population_count;
use crate::generation_bound::risk_admitted_entries;
use crate::generation_bound::score_admitted_entries;
''',
    )
    replace_once(
        relative,
        '''        for (name, value) in [
            ("leak", self.leak),
            ("lateral_inhibition", self.lateral_inhibition),
            ("minimum_activation", self.minimum_activation),
        ] {
            if value < FixedQ32::ZERO || value > FixedQ32::ONE {
                return Err(EngramErrorV1::ScoreOutOfRange(name));
            }
        }
''',
        '''        for (name, value) in [
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
''',
    )
    replace_once(
        relative,
        '''            if node.activation < FixedQ32::ZERO || node.activation > FixedQ32::ONE {
''',
        '''            if node.activation <= FixedQ32::ZERO || node.activation > FixedQ32::ONE {
''',
    )
    replace_once(
        relative,
        '''        if expanded.contains(&synapse.source_node_id) && expanded.contains(&synapse.target_node_id)
        {
''',
        '''        if synapse.weight != FixedQ32::ZERO
            && expanded.contains(&synapse.source_node_id)
            && expanded.contains(&synapse.target_node_id)
        {
''',
    )
    replace_once(
        relative,
        '''        .filter_map(|(node_id, activation)| {
            (*activation >= policy.minimum_activation).then_some((node_id, activation))
        })
''',
        '''        .filter_map(|(node_id, activation)| {
            (*activation > FixedQ32::ZERO && *activation >= policy.minimum_activation)
                .then_some((node_id, activation))
        })
''',
    )
    replace_once(
        relative,
        '''            synapse.relation == SynapseRelationV1::Contradicts
                && active_ids.contains(&synapse.source_node_id)
''',
        '''            synapse.relation == SynapseRelationV1::Contradicts
                && synapse.weight != FixedQ32::ZERO
                && active_ids.contains(&synapse.source_node_id)
''',
    )
    replace_once(
        relative,
        '''        for synapse in &snapshot.synapses {
            let mut consider = Vec::new();
''',
        '''        for synapse in snapshot
            .synapses
            .iter()
            .filter(|synapse| synapse.weight != FixedQ32::ZERO)
        {
            let mut consider = Vec::new();
''',
    )

    confidence_fn = r'''fn active_confidence(active_nodes: &[ActiveEngramNodeV1]) -> Result<ProbabilityQ32, EngramErrorV1> {
    if active_nodes.is_empty() {
        return Ok(ProbabilityQ32::ZERO);
    }
    let mut activation_total = 0_u128;
    let mut weighted_confidence = 0_u128;
    for node in active_nodes {
        let activation = u128::try_from(node.activation.raw())
            .map_err(|_| EngramErrorV1::Arithmetic)?;
        activation_total = activation_total
            .checked_add(activation)
            .ok_or(EngramErrorV1::Arithmetic)?;
        weighted_confidence = weighted_confidence
            .checked_add(
                activation
                    .checked_mul(u128::from(node.confidence.raw()))
                    .ok_or(EngramErrorV1::Arithmetic)?,
            )
            .ok_or(EngramErrorV1::Arithmetic)?;
    }
    if activation_total == 0 {
        return Err(EngramErrorV1::Arithmetic);
    }
    let raw = weighted_confidence / activation_total;
    ProbabilityQ32::from_raw(u64::try_from(raw).map_err(|_| EngramErrorV1::Arithmetic)?)
        .map_err(|_| EngramErrorV1::Arithmetic)
}

'''
    replace_between(relative, "fn active_confidence(", "fn ratio_probability(", confidence_fn)

    recall_fn = r'''fn build_admitted_union(
    full: &CandidateUnionV1,
    admitted: &[&CandidateUnionEntryV1],
) -> Result<CandidateUnionV1, RecallErrorV1> {
    let entries = admitted.iter().map(|entry| (*entry).clone()).collect::<Vec<_>>();
    let distinct_channels = entries
        .iter()
        .flat_map(|entry| entry.channels.iter().copied())
        .collect::<BTreeSet<_>>()
        .len();
    let mut value = CandidateUnionV1 {
        cue_digest: full.cue_digest,
        policy_digest: full.policy_digest,
        generation_vector_digest: full.generation_vector_digest,
        entries,
        distinct_channels: u32::try_from(distinct_channels).unwrap_or(u32::MAX),
        omitted_by_channel_limits: full.omitted_by_channel_limits,
        union_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.union_digest = value.compute_union_digest();
    value.validate()?;
    Ok(value)
}

pub fn recall_with_engram(
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
    let score_admitted = score_admitted_entries(&union.entries, retrieval_policy);
    let admitted = risk_admitted_entries(&score_admitted, retrieval_policy);
    let admitted_union =
        build_admitted_union(&union, &admitted).map_err(EngramErrorV1::Recall)?;
    let engram = settle_engram(cue, &admitted_union, engram_snapshot, dynamics_policy)?;

    let minimum_channels =
        usize::try_from(retrieval_policy.minimum_distinct_channels).unwrap_or(usize::MAX);
    let admitted_channels = admitted_distinct_channel_count(&admitted);
    let contradiction =
        !engram.contradictions.is_empty() || contradiction_population_count(&admitted) > 0;
    let reason = if union.entries.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if score_admitted.is_empty() {
        Some(RecallAbstentionReasonV1::ScoreBelowFloor)
    } else if admitted.is_empty() {
        Some(RecallAbstentionReasonV1::OutOfDistribution)
    } else if engram.selected_support.is_empty() {
        Some(RecallAbstentionReasonV1::NoCandidate)
    } else if admitted_channels < minimum_channels {
        Some(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    } else if contradiction
        && (retrieval_policy.abstain_on_contradiction
            || dynamics_policy.contradiction_forces_abstention)
    {
        Some(RecallAbstentionReasonV1::ContradictoryEvidence)
    } else {
        None
    };

    let maximum_results = usize::try_from(retrieval_policy.maximum_results).unwrap_or(0);
    let active_strength = active_support_strength(&engram);
    let (disposition, selections, omitted_count) = if let Some(reason) = reason {
        (RecallDispositionV1::Abstained(reason), Vec::new(), 0)
    } else {
        let mut ranked = admitted_union
            .entries
            .iter()
            .filter_map(|entry| {
                let support = support_for_entry(entry);
                let activation = active_strength.get(&support).copied()?;
                Some((entry, activation))
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
        distinct_channels: u32::try_from(admitted_channels).unwrap_or(u32::MAX),
        engram: Some(engram),
        packet_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    packet.packet_digest = packet.compute_packet_digest();
    packet.validate().map_err(EngramErrorV1::Recall)?;
    Ok(packet)
}

'''
    replace_between(relative, "pub fn recall_with_engram(\n", "fn empty_receipt(", recall_fn)


def patch_exports() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/lib.rs"
    replace_once(
        relative,
        "pub use generation_bound::CanonicalRecallShadowContextV1;\n",
        '''pub use generation_bound::CanonicalRecallShadowContextV1;
pub use generation_bound::ContradictionEvidenceV1;
pub use generation_bound::ContradictionPolarityV1;
''',
    )


def patch_owner_adapter() -> None:
    relative = "codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs"
    replace_once(
        relative,
        "use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;\n",
        '''use codex_hepta_memory_retrieval::ContradictionEvidenceV1;
use codex_hepta_memory_retrieval::ContradictionPolarityV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
''',
    )
    replace_once(
        relative,
        'const OWNER_CONTRADICTION_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-contradiction-group.v1";',
        'const OWNER_CONTRADICTION_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-contradiction-proposition.v2";',
    )
    replace_once(
        relative,
        '''                contradiction_evidence: (semantic_channel
                    == RetrievalChannelV1::ContradictionSupport)
                    .then(|| owner_contradiction_evidence(owner_observation_digest)),
''',
        '''                contradiction_evidence: (semantic_channel
                    == RetrievalChannelV1::ContradictionSupport)
                    .then(|| ContradictionEvidenceV1 {
                        proposition_digest: owner_contradiction_proposition_digest(
                            &observation.batch().query_sha256,
                            snapshot_key.vector_digest,
                        ),
                        polarity: ContradictionPolarityV1::Opposes,
                    }),
''',
    )
    replace_between(
        relative,
        "fn owner_contradiction_evidence(",
        "\n#[cfg(test)]",
        r'''fn owner_contradiction_proposition_digest(
    query_digest: &Sha256Digest,
    generation_vector_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(OWNER_CONTRADICTION_DOMAIN);
    bytes.extend_from_slice(query_digest.as_str().as_bytes());
    bytes.extend_from_slice(generation_vector_digest.as_array());
    Digest32::of_bytes(&bytes)
}
''',
    )


def patch_generation_tests() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/generation_bound_tests.rs"
    contradiction_tests = r'''#[test]
fn high_risk_contradiction_forces_abstention() {
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
fn multiple_same_polarity_contradiction_supports_do_not_abstain() {
    let cue = cue();
    let policy = policy();
    let proposition = digest("same-side-proposition");
    let evidence = ContradictionEvidenceV1 {
        proposition_digest: proposition,
        polarity: ContradictionPolarityV1::Opposes,
    };
    let mut first = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    first.contradiction_evidence = Some(evidence);
    let mut second = candidate(record(2), RetrievalChannelV1::Entity, 1);
    second.contradiction_evidence = Some(evidence);
    let packet = recall(&cue, &policy, vec![first, second])
        .unwrap_or_else(|error| panic!("same-side evidence is valid: {error}"));
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections.len(), 2);
}

'''
    replace_between(
        relative,
        "#[test]\nfn high_risk_contradiction_forces_abstention()",
        "#[test]\nfn stale_generation_candidate_is_rejected_before_ranking()",
        contradiction_tests,
    )
    replace_between(
        relative,
        "#[test]\nfn ood_and_insufficient_coverage_abstain_explicitly()",
        "#[test]\nfn tombstones_and_duplicate_channel_candidates_fail_closed()",
        r'''#[test]
fn ood_and_insufficient_coverage_abstain_explicitly() {
    let cue = cue();
    let policy = policy();
    let only_one_channel = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let packet = recall(&cue, &policy, vec![only_one_channel])
        .unwrap_or_else(|error| panic!("coverage abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::InsufficientChannelCoverage)
    );

    let mut ood_policy = policy();
    ood_policy.minimum_distinct_channels = 1;
    ood_policy.channel_weights = vec![RetrievalChannelWeightV1 {
        channel: RetrievalChannelV1::Lexical,
        weight: FixedQ32::ONE,
        maximum_candidates: 16,
    }];
    let mut out_of_distribution = candidate(record(2), RetrievalChannelV1::Lexical, 1);
    out_of_distribution.ood = ProbabilityQ32::ONE;
    let packet = recall(&cue, &ood_policy, vec![out_of_distribution])
        .unwrap_or_else(|error| panic!("ood abstention: {error}"));
    assert_eq!(
        packet.disposition,
        RecallDispositionV1::Abstained(RecallAbstentionReasonV1::OutOfDistribution)
    );
}

''',
    )
    score_marker = "#[test]\nfn public_union_and_packet_validators_reject_structural_tampering()"
    text = load(relative)
    if text.count(score_marker) != 1:
        raise RuntimeError("generation tests: public validator marker drift")
    low_score_test = r'''#[test]
fn low_score_or_high_ood_candidate_cannot_poison_admitted_recall() {
    let cue = cue();
    let mut policy = policy();
    policy.minimum_distinct_channels = 1;
    policy.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    policy.channel_weights = vec![
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::Lexical,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        },
        RetrievalChannelWeightV1 {
            channel: RetrievalChannelV1::ContradictionSupport,
            weight: FixedQ32::ONE,
            maximum_candidates: 16,
        },
    ];
    let high = candidate(record(1), RetrievalChannelV1::Lexical, 1);
    let baseline = recall(&cue, &policy, vec![high.clone()]).expect("baseline");

    let mut poison = candidate(record(2), RetrievalChannelV1::ContradictionSupport, 1);
    poison.normalized_score = FixedQ32::from_raw(1);
    poison.ood = ProbabilityQ32::ONE;
    poison.contradiction_evidence = Some(ContradictionEvidenceV1 {
        proposition_digest: digest("unadmitted-poison"),
        polarity: ContradictionPolarityV1::Opposes,
    });
    let with_poison = recall(&cue, &policy, vec![high, poison]).expect("poison excluded");
    assert_eq!(baseline.disposition, RecallDispositionV1::Recalled);
    assert_eq!(with_poison.disposition, RecallDispositionV1::Recalled);
    assert_eq!(baseline.selections[0].record_id, with_poison.selections[0].record_id);
    assert_eq!(with_poison.omitted_count, 1);
}

'''
    save(relative, text.replace(score_marker, low_score_test + score_marker, 1))

    marker = "fn next_permutation(values: &mut [usize]) -> bool {"
    text = load(relative)
    if text.count(marker) != 1:
        raise RuntimeError("generation tests: permutation marker drift")
    property_test = r'''#[test]
fn property_legal_policy_matrix_is_order_invariant_and_bounded() {
    let cue = cue();
    for maximum_results in 1..=4 {
        for minimum_score in [0_i64, 1, 1_i64 << 30, 1_i64 << 31] {
            for maximum_ood in [1_u64 << 28, 1_u64 << 31, ProbabilityQ32::ONE.raw()] {
                let mut policy = policy();
                policy.maximum_results = maximum_results;
                policy.minimum_distinct_channels = 1;
                policy.minimum_total_score = FixedQ32::from_raw(minimum_score);
                policy.maximum_ood = probability(maximum_ood);
                let candidates = [
                    candidate(record(1), RetrievalChannelV1::Lexical, 1),
                    candidate(record(2), RetrievalChannelV1::Entity, 1),
                    candidate(record(3), RetrievalChannelV1::ContradictionSupport, 1),
                ];
                let mut order = vec![0_usize, 1, 2];
                let mut expected = None;
                loop {
                    let permutation = order
                        .iter()
                        .map(|index| candidates[*index].clone())
                        .collect::<Vec<_>>();
                    let packet = recall(&cue, &policy, permutation).expect("legal policy");
                    assert!(packet.selections.len() <= usize::try_from(maximum_results).unwrap());
                    assert!(
                        packet.selections.len()
                            + usize::try_from(packet.omitted_count).unwrap_or(usize::MAX)
                            <= candidates.len()
                    );
                    if let Some(expected) = &expected {
                        assert_eq!(expected, &packet);
                    } else {
                        expected = Some(packet);
                    }
                    if !next_permutation(&mut order) {
                        break;
                    }
                }
            }
        }
    }
}

'''
    save(relative, text.replace(marker, property_test + marker, 1))


def patch_engram_tests() -> None:
    relative = "codex-rs/hepta-memory-retrieval/src/engram_tests.rs"
    marker = "#[test]\nfn engram_product_hard_limits_are_enforced()"
    text = load(relative)
    if text.count(marker) != 1:
        raise RuntimeError("engram tests: hard limit marker drift")
    tests = r'''#[test]
fn minimum_activation_must_be_strictly_positive() {
    let mut policy = EngramDynamicsPolicyV1::product_default().expect("policy");
    policy.minimum_activation = FixedQ32::ZERO;
    assert_eq!(
        policy.validate(),
        Err(EngramErrorV1::ScoreOutOfRange("minimum_activation"))
    );
}

#[test]
fn zero_activation_never_creates_active_support() {
    let cue = cue();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("zero-activation"),
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
    let policy = EngramDynamicsPolicyV1::product_default().expect("policy");
    let receipt = settle_engram(&cue, &union, &snapshot, &policy).expect("settle");
    assert!(receipt.active_nodes.is_empty());
    assert!(receipt.selected_support.is_empty());
    assert_eq!(receipt.confidence, ProbabilityQ32::ZERO);
}

#[test]
fn zero_weight_contradiction_edge_is_semantically_inert() {
    let cue = cue();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("zero-weight-contradiction"),
        vec![
            node(
                "node:left",
                EngramPopulationV1::SemanticConcept,
                vec![support(1)],
                FixedQ32::ZERO,
            ),
            node(
                "node:right",
                EngramPopulationV1::SemanticConcept,
                vec![support(2)],
                FixedQ32::ZERO,
            ),
        ],
        vec![synapse(
            "node:left",
            "node:right",
            SynapseRelationV1::Contradicts,
            FixedQ32::ZERO,
        )],
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let packet = recall_with_engram(
        &cue,
        &retrieval_policy(2),
        vec![
            candidate(1, FixedQ32::ONE.raw()),
            candidate(2, FixedQ32::ONE.raw()),
        ],
        &snapshot,
        &dynamics,
    )
    .expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    let receipt = packet.engram.expect("engram");
    assert!(receipt.contradictions.is_empty());
    assert_eq!(receipt.resources.traversed_synapses, 0);
}

#[test]
fn confidence_is_activation_weighted() {
    let cue = cue();
    let mut high = node(
        "node:high",
        EngramPopulationV1::SemanticConcept,
        vec![support(1)],
        FixedQ32::ZERO,
    );
    high.confidence = ProbabilityQ32::ONE;
    let mut low = node(
        "node:low",
        EngramPopulationV1::EpisodicBinding,
        vec![support(2)],
        FixedQ32::ZERO,
    );
    low.confidence = ProbabilityQ32::ZERO;
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("weighted-confidence"),
        vec![high, low],
        Vec::new(),
    )
    .expect("snapshot");
    let mut dynamics = EngramDynamicsPolicyV1::product_default().expect("policy");
    dynamics.leak = FixedQ32::ZERO;
    dynamics.lateral_inhibition = FixedQ32::ZERO;
    let union = build_candidate_union(
        &cue,
        &retrieval_policy(2),
        vec![
            candidate(1, FixedQ32::ONE.raw()),
            candidate(2, 1_i64 << 30),
        ],
    )
    .expect("union");
    let receipt = settle_engram(&cue, &union, &snapshot, &dynamics).expect("settle");
    let numerator = receipt.active_nodes.iter().fold(0_u128, |sum, node| {
        sum + u128::try_from(node.activation.raw()).unwrap()
            * u128::from(node.confidence.raw())
    });
    let denominator = receipt.active_nodes.iter().fold(0_u128, |sum, node| {
        sum + u128::try_from(node.activation.raw()).unwrap()
    });
    let expected = ProbabilityQ32::from_raw(u64::try_from(numerator / denominator).unwrap())
        .expect("probability");
    assert_eq!(receipt.confidence, expected);
    assert_ne!(receipt.confidence.raw(), ProbabilityQ32::ONE.raw() / 2);
}

#[test]
fn hnmf_settles_only_policy_admitted_candidates() {
    let cue = cue();
    let snapshot = EngramSnapshotV1::new(
        cue.snapshot_key.vector_digest,
        digest("admitted-only"),
        vec![
            node(
                "node:high",
                EngramPopulationV1::SemanticConcept,
                vec![support(1)],
                FixedQ32::ZERO,
            ),
            node(
                "node:low",
                EngramPopulationV1::SemanticConcept,
                vec![support(2)],
                FixedQ32::ZERO,
            ),
        ],
        Vec::new(),
    )
    .expect("snapshot");
    let mut retrieval = retrieval_policy(1);
    retrieval.minimum_total_score = FixedQ32::from_raw(1_i64 << 31);
    let packet = recall_with_engram(
        &cue,
        &retrieval,
        vec![candidate(1, FixedQ32::ONE.raw()), candidate(2, 1)],
        &snapshot,
        &EngramDynamicsPolicyV1::product_default().expect("dynamics"),
    )
    .expect("recall");
    assert_eq!(packet.disposition, RecallDispositionV1::Recalled);
    assert_eq!(packet.selections[0].record_id, id("memory:1"));
    assert_eq!(packet.omitted_count, 1);
    assert_eq!(packet.engram.expect("engram").resources.candidate_records, 1);
}

'''
    save(relative, text.replace(marker, tests + marker, 1))


def patch_adapter_tests() -> None:
    relative = "codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs"
    replace_once(
        relative,
        "use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;\n",
        '''use codex_hepta_memory_retrieval::ContradictionPolarityV1;
use codex_hepta_memory_retrieval::EngramDynamicsPolicyV1;
''',
    )
    replace_once(
        relative,
        '''    assert!(
        contradiction.candidates[0]
            .contradiction_evidence
            .is_some()
    );
''',
        '''    let evidence = contradiction.candidates[0]
        .contradiction_evidence
        .expect("contradiction evidence");
    assert_eq!(evidence.polarity, ContradictionPolarityV1::Opposes);
    assert!(!evidence.proposition_digest.is_zero());
''',
    )


def assert_no_legacy_names() -> None:
    roots = [
        ROOT / "codex-rs/hepta-memory-retrieval/src",
        ROOT / "codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs",
        ROOT / "codex-rs/hepta-memory/src/cognitive_retrieval_adapter_tests.rs",
        ROOT / "codex-rs/hepta-agentd/src/cognitive_retrieval_learning_tests.rs",
    ]
    for root in roots:
        paths = [root] if root.is_file() else list(root.glob("*.rs"))
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if "contradiction_group_digest" in text or "contradiction_group_digests" in text:
                raise RuntimeError(f"legacy contradiction identifier remains in {path}")


def main() -> None:
    rename_contradiction_fields()
    patch_generation_bound()
    patch_generator()
    patch_engram()
    patch_exports()
    patch_owner_adapter()
    patch_generation_tests()
    patch_engram_tests()
    patch_adapter_tests()
    assert_no_legacy_names()


if __name__ == "__main__":
    main()
