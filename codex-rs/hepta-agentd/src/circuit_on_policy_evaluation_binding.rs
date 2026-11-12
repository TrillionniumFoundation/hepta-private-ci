//! Exact profile, original Training signature and frozen plan bindings.

use std::collections::BTreeSet;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::VerifiedLearningEvidenceV1;
use codex_hepta_types::Digest32;

use super::Error;
use super::OriginalCircuitOnPolicyCohortConfigV1;
use super::OriginalCircuitOnPolicyCohortV1;
use super::OriginalCircuitEvaluationSourceOwnersV1;
use super::contract::MAX_SOURCES;
use crate::CellEvaluationPlanV1;

pub(super) fn validate_configuration(
    owners: &OriginalCircuitEvaluationSourceOwnersV1,
    config: &OriginalCircuitOnPolicyCohortConfigV1,
) -> Result<Digest32, Error> {
    let rule = &config.rule;
    let digest = rule.canonical_digest()?;
    let member = std::iter::once(config.registration.primary())
        .chain(config.registration.retention())
        .find(|member| member.plan_id == rule.plan_id)
        .ok_or(Error::Binding("original registered panel member"))?;
    let actual: BTreeSet<_> = owners
        .sources
        .iter()
        .map(|source| source.run_id.clone())
        .collect();
    if member.task_digest != rule.task_digest
        || member.cohort_rule_digest != digest
        || config.training.request.evaluation_profile != config.registration.evaluation_profile()
        || config.candidate.receipt() != config.training.receipts.get(2).ok_or(Error::Binding("actual original T receipt"))?
        || config.candidate.attestation() != &config.training_evidence
        || config.training.request.envelope.objective_digest != rule.objective_digest
        || config.freeze_plan.snapshot_id != rule.snapshot_id
        || config.freeze_plan.objective_digest != rule.objective_digest
        || config.freeze_plan.inclusion_policy_digest != digest
        || config.freeze_evidence.principal_id != config.training.owners.evaluator
        || owners.ledger.verifier().trust_digest() != config.verifier.trust_digest()
        || owners.ledger.verifier().objective_digest() != rule.objective_digest
        || owners.sources.is_empty()
        || owners.sources.len() > MAX_SOURCES
        || actual.len() != owners.sources.len()
        || actual != rule.run_ids()
        || actual.contains(&config.training.request.source_run_id)
    {
        return Err(Error::Binding(
            "same original profile, complete sources and independent B",
        ));
    }
    for source in &owners.sources {
        let input = rule.source_input(&source.run_id)?;
        if source.identity.agent_id.as_str() != input.scope.agent_id.as_str() {
            return Err(Error::Binding("same original preregistered Source identity"));
        }
    }
    super::protocol::candidate_definition(config)?;
    Ok(digest)
}

pub(super) struct CandidateBinding {
    pub(super) candidate: Digest32,
    pub(super) baseline: Digest32,
    pub(super) generator: VerifiedLearningEvidenceV1,
}

pub(super) fn authenticate_training(
    config: &OriginalCircuitOnPolicyCohortConfigV1,
    current: u64,
) -> Result<CandidateBinding, Error> {
    let original = LearningIterationCoordinatorV1::from_snapshot(config.training.clone())?;
    config.scope.validate_snapshot(&config.training)?;
    if original.next_stage() != Some(LearningIterationStageV1::Evaluation)
        || config.training.receipts.len() != 3
        || config.training.owners.evidence_trust_digest != config.verifier.trust_digest()
        || config.training.request.envelope.objective_digest != config.verifier.objective_digest()
        || current >= config.training.request.envelope.expiry_unix_seconds
    {
        return Err(Error::Binding(
            "original Candidate Training cut and work window",
        ));
    }
    let receipt = &config.training.receipts[2];
    let LearningIterationObservationV1::Training { candidate, .. } = &receipt.observation else {
        return Err(Error::Binding("NoUpdate is not a Candidate evaluation"));
    };
    if receipt.actor_id != config.training.owners.trainer
        || config.training_evidence.principal_id != receipt.actor_id
        || config.training_evidence.issued_at != receipt.observed_unix_seconds
        || receipt.observed_unix_seconds >= config.rule.candidate_plan.fold.evaluation_start
    {
        return Err(Error::Binding(
            "original Generator completed before evaluation window",
        ));
    }
    let generator = config.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &config.training_evidence,
        &learning_iteration_receipt_signing_bytes_v1(receipt)?,
        current,
    )?;
    let candidate = candidate
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    let baseline = config
        .training
        .request
        .selected_bundle
        .digest()
        .map_err(codex_hepta_learning_artifacts::LearningIterationError::from)?;
    if candidate == baseline
        || config.candidate.bundle().digest().map_err(codex_hepta_learning_artifacts::LearningIterationError::from)? != candidate
        || config.candidate.receipt() != receipt
        || config.candidate.attestation() != &config.training_evidence
        || config.candidate.model().components() != &config.candidate.bundle().components
    {
        return Err(Error::Binding(
            "Candidate and retained baseline are distinct",
        ));
    }
    Ok(CandidateBinding {
        candidate,
        baseline,
        generator,
    })
}

pub(super) fn require_plan(
    original: &OriginalCircuitOnPolicyCohortV1,
    plan: &CellEvaluationPlanV1,
) -> Result<(), Error> {
    let rule = &original.config.rule;
    let product = plan.product_plan();
    let frozen = &product.frozen_plan;
    let dataset = original.observed_dataset()?;
    let record = plan.record();
    let training = authenticate_training(&original.config, super::now()?)?;
    if original.fenced
        || frozen.plan_id != rule.plan_id
        || frozen.objective_digest != rule.objective_digest
        || frozen.dataset_digest != dataset.snapshot.dataset_digest
        || frozen.final_holdout_digest != original.observed_manifest_digest()?
        || frozen.final_holdout_window_id != rule.holdout_window_id
        || frozen.authority.grants_any()
        || product.candidate_temporal_plan_digest != rule.candidate_plan.plan_digest
        || product.baseline_temporal_plan_digest != rule.baseline_plan.plan_digest
        || product.comparison_mode()
            != &codex_hepta_intelligence_eval::ProductComparisonModeV1::PairedOnPolicy(
                original.observed_pairing_contract()?.clone())
        || record.learning_evaluation_profile
            != Some(
                original
                    .config
                    .registration
                    .evaluation_profile()
                    .into_array(),
            )
        || record.candidate.manifest.bundle_digest != training.candidate.into_array()
        || record.fixed_expert.manifest.bundle_digest != training.baseline.into_array()
        || record.candidate.cost.identity().task_digest != rule.task_digest.into_array()
        || record.fixed_expert.cost.identity().task_digest != rule.task_digest.into_array()
    {
        return Err(Error::Binding(
            "actual frozen Cell plan, cohort and original candidate",
        ));
    }
    // These two existing Cell task cost cuts are not an aggregate cost claim
    // about every historical/held-out member in the cohort.
    Ok(())
}


/// Fill identifiers only from the frozen rule, original ledger and signed T.
/// The two real outcomes never enter this derivation or choose the candidate.
pub(super) fn pairing_contract(
    config: &OriginalCircuitOnPolicyCohortConfigV1,
    ledger: &codex_hepta_learning_ledger::LedgerWriter,
    owners: &[crate::OriginalCircuitEvaluationSourceV1],
    training: &CandidateBinding,
) -> Result<codex_hepta_intelligence_eval::OnPolicyPairingContractV1, Error> {
    use codex_hepta_intelligence_eval::OnPolicyArmBindingV1;
    use codex_hepta_intelligence_eval::OnPolicyPairContractV1;
    use codex_hepta_intelligence_eval::OnPolicyPairingContractV1;
    use codex_hepta_types::StableId;
    let protocol_digest = config.rule.protocol.canonical_digest()?;
    let mut pairs = Vec::with_capacity(config.rule.pairs.len());
    for pair in &config.rule.pairs {
        let principal_lineage = StableId::new(format!("principal:{}", pair.input.scope.principal_digest))
            .map_err(|_| Error::Binding("original principal lineage"))?;
        let arm = |episode: &crate::OriginalCircuitEvaluationEpisodeV1, model_digest|
            -> Result<OnPolicyArmBindingV1, Error>
        {
            let source = owners.iter().find(|owner| owner.run_id == episode.behavior_run_id)
                .ok_or(Error::Binding("original arm Source identity"))?;
            let run = crate::circuit_learning_run_id_v1(
                ledger, &source.identity.agent_id, &episode.episode_id)
                .map_err(|_| Error::Binding("actual original ledger-derived run"))?;
            if run != episode.behavior_run_id {
                return Err(Error::Binding("frozen arm names its actual original run"));
            }
            Ok(OnPolicyArmBindingV1 {
                decision_id: run,
                principal_lineage: principal_lineage.clone(),
                episode_lineage: episode_lineage(ledger, &episode.episode_id)?,
                behavior_run_id: episode.behavior_run_id.clone(),
                model_digest,
            })
        };
        pairs.push(OnPolicyPairContractV1 {
            pair_id: pair.pair_id.clone(),
            input_digest: super::contract::input_digest(&pair.input)?,
            protocol_digest,
            candidate: arm(&pair.candidate, training.candidate)?,
            baseline: arm(&pair.baseline, training.baseline)?,
        });
    }
    pairs.sort_by(|left, right| left.pair_id.cmp(&right.pair_id));
    let pairing = OnPolicyPairingContractV1 { pairs };
    pairing.digest().map_err(|_| Error::Binding("complete frozen paired comparison contract"))?;
    Ok(pairing)
}

pub(super) fn episode_lineage(
    ledger: &codex_hepta_learning_ledger::LedgerWriter,
    episode: &codex_hepta_types::StableId,
) -> Result<codex_hepta_types::StableId, Error> {
    codex_hepta_types::StableId::new(format!(
        "episode:{}",
        Digest32::of_parts(&[
            b"hepta.circuit.original-evaluation-episode.v1\0",
            ledger.binding_digest().as_array(),
            episode.as_str().as_bytes(),
        ])
    )).map_err(|_| Error::Binding("original episode lineage"))
}
