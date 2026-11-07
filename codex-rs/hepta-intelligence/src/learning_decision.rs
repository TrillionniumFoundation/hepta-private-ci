//! Authenticated, finite learning decisions. This pure boundary neither writes a
//! proposal nor selects, installs or rewards a model. The host must retain the
//! plan before execution and obtain inventories from its existing native owners.
//! Signatures authenticate those assertions; they do not prove external facts.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_intelligence_eval::IndependentEvaluationDispositionV1;
use codex_hepta_intelligence_eval::ProductTimingEvidenceV1;
use codex_hepta_intelligence_eval::revalidate_product_qualification_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::verify_signed_independent_roles_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LearningAttemptPhaseV1;
use crate::LearningAttemptStatusV1;
use crate::LearningAttemptV1;
use crate::LearningCycleDispositionV1;
use crate::LearningDecisionAttestationsV1;
use crate::LearningDecisionErrorV1;
use crate::LearningDecisionInputV1;
use crate::LearningDecisionPinsV1;
use crate::LearningDecisionPlanV1;
use crate::LearningDecisionReceiptV1;
use crate::LearningDecisionSummaryV1;
use crate::LearningStopV1;

/// Freeze and independently retain this digest before any search or evaluation.
pub fn learning_decision_plan_digest_v1(
    plan: &LearningDecisionPlanV1,
) -> Result<Digest32, LearningDecisionErrorV1> {
    if !(1..=128).contains(&plan.maximum_candidates)
        || !(1..=4096).contains(&plan.maximum_attempts)
        || plan.maximum_cost_units == 0
        || !(1..=plan.maximum_cost_units).contains(&plan.next_attempt_reservation_units)
    {
        return Err(LearningDecisionErrorV1::Binding("finite budget"));
    }
    let mut bytes = b"hepta.learning-decision.plan.v1\0".to_vec();
    for id in [&plan.cycle_id, &plan.incumbent_id] {
        push_id(&mut bytes, id);
    }
    for digest in [
        plan.incumbent_model_digest,
        plan.protocol_digest,
        plan.objective_digest,
        plan.dataset_digest,
        plan.search_space_digest,
        plan.cost_profile_digest,
    ] {
        if digest.is_zero() {
            return Err(LearningDecisionErrorV1::Binding("plan evidence"));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        u64::from(plan.maximum_candidates),
        u64::from(plan.maximum_attempts),
        plan.maximum_cost_units,
        plan.next_attempt_reservation_units,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Canonical inventory identities for reconciliation by existing owners. This
/// helper is not a completeness certificate or an issuance of trusted pins.
pub fn learning_decision_inventory_v1(
    input: &LearningDecisionInputV1,
) -> Result<LearningDecisionPinsV1, LearningDecisionErrorV1> {
    use LearningDecisionErrorV1::Binding;
    let plan_digest = learning_decision_plan_digest_v1(&input.plan)?;
    if input.candidates.len() > 128 || input.attempts.len() > 4096 {
        return Err(Binding("inventory limit"));
    }
    let mut candidates = b"hepta.learning-decision.candidates.v1\0".to_vec();
    let mut ids = BTreeSet::new();
    let mut models = BTreeSet::new();
    let mut previous = None;
    for candidate in &input.candidates {
        if previous.is_some_and(|id| id >= &candidate.candidate_id)
            || candidate.candidate_id == input.plan.incumbent_id
            || candidate.model_digest.is_zero()
            || candidate.model_digest == input.plan.incumbent_model_digest
            || !models.insert(candidate.model_digest)
        {
            return Err(Binding("candidate inventory or no-op"));
        }
        previous = Some(&candidate.candidate_id);
        ids.insert(&candidate.candidate_id);
        push_id(&mut candidates, &candidate.candidate_id);
        candidates.extend_from_slice(candidate.model_digest.as_array());
        // Include absence explicitly; a qualification cannot silently disappear.
        candidates.push(u8::from(candidate.evaluation.is_some()));
        if let Some(evaluation) = &candidate.evaluation {
            candidates.extend_from_slice(evaluation.qualification.evidence_digest.as_array());
            candidates.extend_from_slice(evaluation.qualification.publication_digest.as_array());
        }
    }
    let mut attempts = b"hepta.learning-decision.attempts.v1\0".to_vec();
    let mut receipts = BTreeSet::new();
    let mut earlier: BTreeMap<&StableId, &LearningAttemptV1> = BTreeMap::new();
    let mut retried = BTreeSet::new();
    previous = None;
    for attempt in &input.attempts {
        if previous.is_some_and(|id| id >= &attempt.attempt_id)
            || attempt.owner_receipt_digest.is_zero()
            || !receipts.insert(attempt.owner_receipt_digest)
            || attempt
                .candidate_id
                .as_ref()
                .is_some_and(|id| !ids.contains(id))
        {
            return Err(Binding("attempt inventory"));
        }
        previous = Some(&attempt.attempt_id);
        push_id(&mut attempts, &attempt.attempt_id);
        attempts.push(u8::from(attempt.retry_of.is_some()));
        if let Some(parent) = &attempt.retry_of {
            let previous = earlier.get(parent).ok_or(Binding("retry predecessor"))?;
            if previous.candidate_id != attempt.candidate_id
                || previous.phase != attempt.phase
                || !matches!(
                    previous.status,
                    LearningAttemptStatusV1::Failed | LearningAttemptStatusV1::Stopped
                )
                || !retried.insert(parent)
            {
                return Err(Binding("retry lineage"));
            }
            push_id(&mut attempts, parent);
        }
        earlier.insert(&attempt.attempt_id, attempt);
        attempts.push(u8::from(attempt.candidate_id.is_some()));
        if let Some(id) = &attempt.candidate_id {
            push_id(&mut attempts, id);
        }
        attempts.extend_from_slice(&[attempt.phase as u8, attempt.status as u8]);
        for cost in attempt.cost_units {
            attempts.push(u8::from(cost.is_some()));
            if let Some(cost) = cost {
                attempts.extend_from_slice(&cost.to_be_bytes());
            }
        }
        attempts.extend_from_slice(attempt.owner_receipt_digest.as_array());
    }
    Ok(LearningDecisionPinsV1 {
        plan_digest,
        candidate_inventory_digest: Digest32::of_bytes(&candidates),
        attempt_inventory_digest: Digest32::of_bytes(&attempts),
    })
}

pub fn learning_decision_signing_payload_v1(
    input: &LearningDecisionInputV1,
) -> Result<Vec<u8>, LearningDecisionErrorV1> {
    let pins = learning_decision_inventory_v1(input)?;
    let mut bytes = b"hepta.learning-decision.terminal.v1\0".to_vec();
    for digest in [
        pins.plan_digest,
        pins.candidate_inventory_digest,
        pins.attempt_inventory_digest,
        input.terminal_evidence_digest,
        input.data_eligibility_evidence_digest,
    ] {
        if digest.is_zero() {
            return Err(LearningDecisionErrorV1::Binding("terminal evidence"));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(input.stop as u8);
    Ok(bytes)
}

pub fn complete_authenticated_learning_decision_v1(
    input: LearningDecisionInputV1,
    expected: LearningDecisionPinsV1,
    attestations: LearningDecisionAttestationsV1,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<LearningDecisionReceiptV1, LearningDecisionErrorV1> {
    use LearningDecisionErrorV1 as E;
    let pins = learning_decision_inventory_v1(&input)?;
    if pins != expected {
        return Err(E::Binding("host-owned plan or inventory"));
    }
    let payload = learning_decision_signing_payload_v1(&input)?;
    let mut verified = Vec::new();
    let mut authentication = payload.clone();
    for (role, attestation) in [
        (LearningEvidenceRoleV1::Generator, &attestations.generator),
        (LearningEvidenceRoleV1::Observer, &attestations.observer),
        (LearningEvidenceRoleV1::Evaluator, &attestations.evaluator),
    ] {
        if attestation.objective_digest != input.plan.objective_digest {
            return Err(E::Binding("objective trust context"));
        }
        let actor = verifier
            .verify(role, attestation, &payload, now)
            .map_err(E::Authentication)?;
        for previous in &verified {
            verify_signed_independent_roles_v1(previous, &actor, now).map_err(E::Authentication)?;
        }
        verified.push(actor);
        authentication.extend_from_slice(&attestation.signing_bytes());
        authentication.extend_from_slice(&attestation.signature);
    }
    let mut eligible_candidate_ids = Vec::new();
    let mut insufficient = input.stop == LearningStopV1::EvidenceIncomplete;
    let by_id: BTreeMap<_, _> = input
        .attempts
        .iter()
        .map(|attempt| (&attempt.attempt_id, attempt))
        .collect();
    let mut recovered = BTreeSet::new();
    for attempt in input
        .attempts
        .iter()
        .filter(|attempt| attempt.status == LearningAttemptStatusV1::Succeeded)
    {
        let mut parent = attempt.retry_of.as_ref();
        while let Some(id) = parent {
            recovered.insert(id);
            parent = by_id[id].retry_of.as_ref();
        }
    }
    let unrecovered_failure = input.attempts.iter().any(|attempt| {
        attempt.status == LearningAttemptStatusV1::Failed
            && !recovered.contains(&attempt.attempt_id)
    });
    for candidate in &input.candidates {
        let Some(evaluation) = &candidate.evaluation else {
            insufficient |= input.stop != LearningStopV1::BudgetStopped;
            for attempt in input
                .attempts
                .iter()
                .filter(|attempt| attempt.candidate_id.as_ref() == Some(&candidate.candidate_id))
            {
                // A successful evaluation without its qualification is missing
                // evidence, never an unperformed evaluation at a budget stop.
                insufficient |= attempt.phase == LearningAttemptPhaseV1::Evaluation
                    && attempt.status == LearningAttemptStatusV1::Succeeded;
            }
            continue;
        };
        let bundle = &evaluation.bundle;
        if bundle.candidate_id != candidate.candidate_id
            || bundle.baseline_id != input.plan.incumbent_id
            || bundle.dataset_digest != input.plan.dataset_digest
            || bundle.objective_digest != input.plan.objective_digest
            || &bundle.generator != verified[0].principal()
            || &bundle.evaluator != verified[2].principal()
        {
            return Err(E::Binding("candidate evaluation lineage"));
        }
        let decision = revalidate_product_qualification_v1(
            &evaluation.qualification,
            bundle.clone(),
            evaluation.metric_roles.clone(),
            &evaluation.evidence,
            ProductTimingEvidenceV1::Qualification,
            verifier,
            now,
        )
        .map_err(E::Evaluation)?;
        match decision.decision.disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
                eligible_candidate_ids.push(candidate.candidate_id.clone())
            }
            IndependentEvaluationDispositionV1::Ineligible => {}
            IndependentEvaluationDispositionV1::InsufficientEvidence => insufficient = true,
        }
        insufficient |= !input.attempts.iter().any(|attempt| {
            attempt.candidate_id.as_ref() == Some(&candidate.candidate_id)
                && attempt.phase == LearningAttemptPhaseV1::Evaluation
                && attempt.status == LearningAttemptStatusV1::Succeeded
        });
    }
    if input.stop == LearningStopV1::NoQualifiedData && !input.candidates.is_empty() {
        return Err(E::Binding("no-qualified-data with candidates"));
    }
    let known_cost_units: u128 = input
        .attempts
        .iter()
        .flat_map(|attempt| attempt.cost_units)
        .flatten()
        .map(u128::from)
        .sum();
    let unknown_cost_fields = input
        .attempts
        .iter()
        .flat_map(|attempt| attempt.cost_units)
        .filter(Option::is_none)
        .count();
    let failed_attempts = input
        .attempts
        .iter()
        .filter(|attempt| attempt.status == LearningAttemptStatusV1::Failed)
        .count();
    let unresolved_attempts = input
        .attempts
        .iter()
        .filter(|attempt| attempt.status == LearningAttemptStatusV1::Unresolved)
        .count();
    insufficient |= unknown_cost_fields != 0 || unresolved_attempts != 0;
    let budget = &input.plan;
    let overrun = known_cost_units > u128::from(budget.maximum_cost_units)
        || input.attempts.len() > budget.maximum_attempts as usize
        || input.candidates.len() > budget.maximum_candidates as usize;
    let candidate_budget_exhausted = input.candidates.len() >= budget.maximum_candidates as usize
        && input
            .candidates
            .iter()
            .all(|candidate| candidate.evaluation.is_some());
    if input.stop == LearningStopV1::BudgetStopped
        && !insufficient
        && !overrun
        && !candidate_budget_exhausted
        && input.attempts.len() < budget.maximum_attempts as usize
        && known_cost_units + u128::from(budget.next_attempt_reservation_units)
            <= u128::from(budget.maximum_cost_units)
    {
        return Err(E::Binding("budget stop before declared boundary"));
    }
    let decision =
        if overrun || unrecovered_failure || input.stop == LearningStopV1::ExecutionFailed {
            LearningCycleDispositionV1::Failed
        } else if insufficient {
            LearningCycleDispositionV1::Inconclusive
        } else if !eligible_candidate_ids.is_empty() {
            LearningCycleDispositionV1::Adoptable
        } else {
            LearningCycleDispositionV1::NoUpdate
        };
    if decision != LearningCycleDispositionV1::Adoptable {
        eligible_candidate_ids.clear();
    }
    authentication.extend_from_slice(verifier.trust_digest().as_array());
    authentication.push(decision as u8);
    let summary = LearningDecisionSummaryV1 {
        decision,
        no_update_reason: (decision == LearningCycleDispositionV1::NoUpdate).then_some(input.stop),
        eligible_candidate_ids,
        retained_incumbent_id: input.plan.incumbent_id.clone(),
        retained_incumbent_model_digest: input.plan.incumbent_model_digest,
        known_cost_units,
        unknown_cost_fields,
        failed_attempts,
        unresolved_attempts,
        pins,
        receipt_digest: Digest32::of_bytes(&authentication),
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(LearningDecisionReceiptV1 {
        summary,
        input,
        attestations,
    })
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
