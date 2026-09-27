//! Admission helpers for the single canonical pipeline.
use super::*;
use codex_hepta_kg::KnowledgeRelationKindV2;
use codex_hepta_kg::KnowledgeRelationQueryV2;
use codex_hepta_kg::query_relations;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

#[path = "canonical_integrity.rs"]
mod integrity;
pub(super) use integrity::validate_candidates;
pub(super) use integrity::validate_selection;

fn push_bytes(out: &mut Vec<u8>, bytes: &[u8]) {
    out.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    out.extend_from_slice(bytes);
}
fn push_digest(out: &mut Vec<u8>, value: Digest32) { out.extend_from_slice(value.as_array()); }

pub(super) fn exercise_policy_digest(policy: &PromptExercisePolicyV1) -> Result<Digest32, CanonicalPromptError> {
    if policy.allowed_boundaries.is_empty() || policy.allowed_boundaries.len() > 11
        || policy.not_before_unix_ms == 0 || policy.valid_until_unix_ms <= policy.not_before_unix_ms {
        return Err(CanonicalPromptError::PolicyInvalid);
    }
    let mut out = b"hepta.prompt-optimizer.exercise-policy.v2".to_vec();
    push_bytes(&mut out, policy.policy_id.as_str().as_bytes());
    for value in [policy.objective_digest, policy.scope_digest, policy.state_digest,
        policy.generation_vector_digest, policy.model_tuple_digest] {
        if value.is_zero() { return Err(CanonicalPromptError::PolicyInvalid); }
        push_digest(&mut out, value);
    }
    let mut tags = policy.allowed_boundaries.iter().map(|boundary| match boundary {
        PromptDecisionBoundaryV1::RequestAccepted => 0_u8,
        PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        PromptDecisionBoundaryV1::BeforePlanning => 2,
        PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        PromptDecisionBoundaryV1::AfterObservation => 5,
        PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        PromptDecisionBoundaryV1::BeforeVerification => 8,
        PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }).collect::<Vec<_>>();
    tags.sort_unstable();
    if tags.windows(2).any(|pair| pair[0] == pair[1]) { return Err(CanonicalPromptError::PolicyInvalid); }
    push_bytes(&mut out, &tags);
    out.extend_from_slice(&policy.wait_value_q32.raw().to_be_bytes());
    out.extend_from_slice(&policy.not_before_unix_ms.to_be_bytes());
    out.extend_from_slice(&policy.valid_until_unix_ms.to_be_bytes());
    Ok(Digest32::of_bytes(&out))
}

fn verify(
    current: &PromptEvidenceSnapshotV1,
    role: LearningEvidenceRoleV1,
    evidence: &SignedLearningEvidenceV1,
    payload: &[u8],
    now: u64,
) -> Result<VerifiedLearningEvidenceV1, CanonicalPromptError> {
    if now >= evidence.expires_at { return Err(CanonicalPromptError::EvidenceExpired); }
    current.verifier.verify(role, evidence, payload, now)
        .map_err(|error| CanonicalPromptError::Evidence(error.to_string()))
}
fn separate(left: &VerifiedLearningEvidenceV1, right: &VerifiedLearningEvidenceV1, now: u64) -> Result<(), CanonicalPromptError> {
    verify_signed_actor_separation(left, right, now)
        .map_err(|error| CanonicalPromptError::Evidence(error.to_string()))
}

pub fn pricing_admission_signing_payload_v1(
    candidates: &EnumeratedPromptCandidatesV1,
    estimates: &[PromptPricingEvidenceV1],
    policy: &PromptPricingPolicyV1,
    scope_digest: Digest32,
) -> Result<Vec<u8>, CanonicalPromptError> {
    validate_candidates(&candidates.inner)?;
    if scope_digest.is_zero() || estimates.len() != candidates.candidates.len() {
        return Err(CanonicalPromptError::Integrity("pricing batch shape"));
    }
    let mut out = b"hepta.prompt-optimizer.bound-pricing-admission.v2".to_vec();
    for value in [candidates.receipt.receipt_digest, candidates.registry_snapshot.snapshot_digest,
        candidates.generation_vector_digest, candidates.model_tuple.digest(),
        candidates.receipt.objective_digest, candidates.receipt.state_digest,
        candidates.receipt.selection_grammar_digest, scope_digest, policy.digest()?] {
        push_digest(&mut out, value);
    }
    out.extend_from_slice(&(estimates.len() as u64).to_be_bytes());
    for (candidate, estimate) in candidates.candidates.iter().zip(estimates) {
        if candidate.factor_id != estimate.factor_id { return Err(CanonicalPromptError::Integrity("pricing order or factor")); }
        push_digest(&mut out, candidate.binding_digest);
        push_bytes(&mut out, &pricing_evidence_signing_payload_v1(estimate));
        push_bytes(&mut out, &estimate.evidence.signing_bytes());
        push_bytes(&mut out, &estimate.evidence.signature);
    }
    Ok(out)
}

pub(super) fn verify_pricing(
    candidates: &EnumeratedPromptCandidatesV1,
    material: &PromptPricingAdmissionV1,
    current: &PromptEvidenceSnapshotV1,
    now: u64,
) -> Result<u64, CanonicalPromptError> {
    validate_candidates(&candidates.inner)?;
    let policy = &current.exercise_policy;
    policy.digest()?;
    if current.verifier.objective_digest() != candidates.receipt.objective_digest
        || policy.objective_digest != candidates.receipt.objective_digest {
        return Err(CanonicalPromptError::ObjectiveMismatch);
    }
    if policy.scope_digest != current.verifier.scope_digest() { return Err(CanonicalPromptError::ScopeMismatch); }
    if policy.state_digest != candidates.receipt.state_digest
        || policy.generation_vector_digest != candidates.generation_vector_digest
        || policy.model_tuple_digest != candidates.model_tuple.digest() {
        return Err(CanonicalPromptError::PolicyChanged);
    }
    if now < policy.not_before_unix_ms || now >= policy.valid_until_unix_ms {
        return Err(CanonicalPromptError::EvidenceExpired);
    }
    let generator = verify(current, LearningEvidenceRoleV1::Generator, &material.completeness_evidence,
        &candidate_completeness_signing_payload_v1(&material.completeness)?, now)?;
    let payload = pricing_admission_signing_payload_v1(candidates, &material.estimates,
        &current.pricing_policy, current.verifier.scope_digest())?;
    let evaluator = verify(current, LearningEvidenceRoleV1::Evaluator, &material.binding_evidence, &payload, now)?;
    separate(&generator, &evaluator, now)?;
    let mut expiry = policy.valid_until_unix_ms.min(material.completeness_evidence.expires_at)
        .min(material.binding_evidence.expires_at);
    for estimate in &material.estimates {
        let evaluator = verify(current, LearningEvidenceRoleV1::Evaluator, &estimate.evidence,
            &pricing_evidence_signing_payload_v1(estimate), now)?;
        separate(&generator, &evaluator, now)?;
        expiry = expiry.min(estimate.evidence.expires_at);
    }
    Ok(expiry)
}

pub(super) fn revalidate_priced(
    priced: &PricedPromptCandidatesV1,
    current: &PromptEvidenceSnapshotV1,
    now: u64,
) -> Result<(), CanonicalPromptError> {
    if current.source_id != priced.source_id { return Err(CanonicalPromptError::SourceChanged); }
    if current.verifier.trust_digest() != priced.trust_digest { return Err(CanonicalPromptError::TrustChanged); }
    if current.verifier.scope_digest() != priced.scope_digest { return Err(CanonicalPromptError::ScopeMismatch); }
    if current.pricing_policy.digest()? != priced.inner.pricing_policy_digest {
        return Err(CanonicalPromptError::PolicyChanged);
    }
    if now >= priced.valid_until_unix_ms { return Err(CanonicalPromptError::EvidenceExpired); }
    let candidates = EnumeratedPromptCandidatesV1 { inner: priced.inner.candidates.clone() };
    verify_pricing(&candidates, &priced.admission, current, now)?;
    let replayed = engine::price_factors_v1(
        candidates.inner, &priced.admission.completeness, &priced.admission.completeness_evidence,
        priced.admission.estimates.clone(), &current.verifier, &current.pricing_policy, now,
    )?;
    if replayed != priced.inner { return Err(CanonicalPromptError::Integrity("pricing replay")); }
    Ok(())
}

pub fn interaction_admission_signing_payload_v1(
    priced: &PricedPromptCandidatesV1,
    pairs: &[PromptPairUtilityEvidenceV1],
    graph: &KnowledgeGenerationV2,
    missing_pairs: PromptMissingPairPolicyV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    if pairs.len() > MAX_CANONICAL_INTERACTION_EDGES as usize {
        return Err(CanonicalPromptError::Integrity("pair bound"));
    }
    let mut out = b"hepta.prompt-optimizer.bound-interaction-admission.v2".to_vec();
    for value in [priced.candidates.receipt.receipt_digest, priced.pricing_set_digest,
        priced.candidates.receipt.objective_digest, priced.scope_digest,
        priced.candidates.model_tuple.digest(), priced.candidates.generation_vector_digest,
        graph.generation_digest, graph.source_snapshot_digest] {
        push_digest(&mut out, value);
    }
    out.push(match missing_pairs {
        PromptMissingPairPolicyV1::RequireExplicit => 0,
        PromptMissingPairPolicyV1::AssumeZeroWithWitness => 1,
    });
    out.extend_from_slice(&(pairs.len() as u64).to_be_bytes());
    let mut previous = None;
    for pair in pairs {
        let key = (&pair.left_factor_id, &pair.right_factor_id);
        if pair.left_factor_id >= pair.right_factor_id || previous.is_some_and(|last| last >= key) {
            return Err(CanonicalPromptError::Integrity("pair order"));
        }
        previous = Some(key);
        push_bytes(&mut out, &pair_utility_evidence_signing_payload_v1(pair));
        push_bytes(&mut out, &pair.evidence.signing_bytes());
        push_bytes(&mut out, &pair.evidence.signature);
    }
    Ok(out)
}

pub(super) fn verify_interactions(
    priced: &PricedPromptCandidatesV1,
    material: &PromptInteractionAdmissionV1,
    current: &PromptEvidenceSnapshotV1,
    now: u64,
) -> Result<u64, CanonicalPromptError> {
    current.graph.validate().map_err(|error| CanonicalPromptError::Corrupt(error.to_string()))?;
    if current.graph.generation_vector_digest != priced.candidates.generation_vector_digest {
        return Err(CanonicalPromptError::GraphChanged);
    }
    let generator = verify(current, LearningEvidenceRoleV1::Generator, &priced.admission.completeness_evidence,
        &candidate_completeness_signing_payload_v1(&priced.admission.completeness)?, now)?;
    let payload = interaction_admission_signing_payload_v1(priced, &material.pairs, &current.graph, material.missing_pairs)?;
    let evaluator = verify(current, LearningEvidenceRoleV1::Evaluator, &material.binding_evidence, &payload, now)?;
    separate(&generator, &evaluator, now)?;
    let mut expiry = material.binding_evidence.expires_at;
    for pair in &material.pairs {
        let evaluator = verify(current, LearningEvidenceRoleV1::Evaluator, &pair.evidence,
            &pair_utility_evidence_signing_payload_v1(pair), now)?;
        separate(&generator, &evaluator, now)?;
        expiry = expiry.min(pair.evidence.expires_at);
    }
    let known = priced.rows.iter().map(|row| row.binding.factor_id.clone()).collect::<BTreeSet<_>>();
    let relations = query_relations(&current.graph, KnowledgeRelationQueryV2 {
        query_id: StableId::new("query:prompt-admission").map_err(|_| CanonicalPromptError::PolicyInvalid)?,
        generation_digest: current.graph.generation_digest,
        seed_node_ids: known.iter().cloned().collect(),
        valid_at_unix_seconds: Some(i64::try_from(now / 1000).map_err(|_| CanonicalPromptError::EvidenceExpired)?),
        relation_kinds: vec![KnowledgeRelationKindV2::PromptRequires, KnowledgeRelationKindV2::PromptConflicts,
            KnowledgeRelationKindV2::PromptComplements, KnowledgeRelationKindV2::PromptSubstitutes,
            KnowledgeRelationKindV2::PromptDominates, KnowledgeRelationKindV2::PromptRedundant,
            KnowledgeRelationKindV2::PromptSupersedes],
        maximum_edges: MAX_CANONICAL_INTERACTION_EDGES,
    }).map_err(|error| CanonicalPromptError::Corrupt(error.to_string()))?;
    if relations.omitted_count != 0 { return Err(CanonicalPromptError::Integrity("incomplete relation projection")); }
    let mut requires = BTreeMap::<StableId, BTreeSet<StableId>>::new();
    let mut conflicts = BTreeSet::new();
    for edge in &relations.edges {
        let left = &edge.identity.source_node_id;
        let right = &edge.identity.target_node_id;
        if edge.identity.relation == KnowledgeRelationKindV2::PromptRequires && known.contains(left) {
            if !known.contains(right) { return Err(CanonicalPromptError::UnsatisfiableConstraints(right.to_string())); }
            requires.entry(left.clone()).or_default().insert(right.clone());
        }
        if known.contains(left) && known.contains(right) && matches!(edge.identity.relation,
            KnowledgeRelationKindV2::PromptConflicts | KnowledgeRelationKindV2::PromptDominates
            | KnowledgeRelationKindV2::PromptRedundant | KnowledgeRelationKindV2::PromptSupersedes) {
            conflicts.insert((left.clone(), right.clone()));
        }
        // Conservatively expire at the first retained support boundary. A fresh
        // generation can be selected again; cached graph claims cannot outlive it.
        for support in &edge.supports {
            if let Some(until) = support.valid_to_unix_seconds {
                let until = u64::try_from(until).ok().and_then(|s| s.checked_mul(1000))
                    .ok_or(CanonicalPromptError::EvidenceExpired)?;
                expiry = expiry.min(until);
            }
        }
    }
    for node in &current.graph.nodes {
        if known.contains(&node.node_id) {
            for support in &node.supports {
                if let Some(until) = support.valid_to_unix_seconds {
                    let until = u64::try_from(until).ok().and_then(|s| s.checked_mul(1000))
                        .ok_or(CanonicalPromptError::EvidenceExpired)?;
                    expiry = expiry.min(until);
                }
            }
        }
    }
    for root in &known {
        let mut closure = BTreeSet::new();
        let mut pending = vec![root.clone()];
        while let Some(node) = pending.pop() {
            if closure.insert(node.clone()) {
                if let Some(children) = requires.get(&node) { pending.extend(children.iter().cloned()); }
            }
        }
        if conflicts.iter().any(|(left, right)| closure.contains(left) && closure.contains(right)) {
            return Err(CanonicalPromptError::UnsatisfiableConstraints(root.to_string()));
        }
    }
    if now >= expiry { return Err(CanonicalPromptError::EvidenceExpired); }
    Ok(expiry)
}
