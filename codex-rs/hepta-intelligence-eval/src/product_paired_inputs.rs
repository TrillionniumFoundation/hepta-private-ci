//! Exact joins and deterministic on-policy checks over the two original arms.
//! These checks preserve source identities. Authenticity of the supplied source
//! evidence is established by the original producer, not by a checksum here.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::MAX_PAIRS;
use super::OnPolicyArmBindingV1;
use super::OnPolicyArmProvenanceV1;
use super::OnPolicyEvaluationArmInputsV1;
use super::OnPolicyPairContractV1;
use super::OnPolicyPairingContractV1;
use super::OnPolicyTemporalComparisonInputsV1;
use super::ProductEvaluationError;
use crate::ClusterAssignment;
use crate::CrossFoldPlanReceiptV1;
use crate::HeldOutTarget;
use crate::OpeRow;

fn invalid(reason: &'static str) -> ProductEvaluationError {
    ProductEvaluationError::Binding(reason)
}

pub(super) fn validate_pair_contract(
    pairing: &OnPolicyPairingContractV1,
) -> Result<(), ProductEvaluationError> {
    let first = pairing.pairs.first().ok_or_else(|| invalid("empty paired cohort"))?;
    if pairing.pairs.len() > MAX_PAIRS {
        return Err(invalid("paired cohort bound"));
    }
    let mut pairs = BTreeSet::new();
    let mut decisions = BTreeSet::new();
    let mut episodes = BTreeSet::new();
    let mut runs = BTreeSet::new();
    for pair in &pairing.pairs {
        if !pairs.insert(&pair.pair_id)
            || pair.input_digest.is_zero()
            || pair.protocol_digest.is_zero()
            || pair.candidate.principal_lineage != pair.baseline.principal_lineage
            || pair.candidate.model_digest.is_zero()
            || pair.baseline.model_digest.is_zero()
            || pair.candidate.model_digest == pair.baseline.model_digest
            || pair.candidate.model_digest != first.candidate.model_digest
            || pair.baseline.model_digest != first.baseline.model_digest
        {
            return Err(invalid("frozen original paired identities and protocol"));
        }
        for arm in [&pair.candidate, &pair.baseline] {
            if !decisions.insert(&arm.decision_id)
                || !episodes.insert(&arm.episode_lineage)
                || !runs.insert(&arm.behavior_run_id)
            {
                return Err(invalid("distinct original paired decisions episodes and runs"));
            }
        }
    }
    Ok(())
}

struct ArmIndex<'a> {
    targets: BTreeMap<&'a StableId, &'a HeldOutTarget>,
    observations: BTreeMap<&'a StableId, &'a OpeRow>,
    assignments: BTreeMap<&'a StableId, &'a ClusterAssignment>,
    provenance: BTreeMap<&'a StableId, &'a OnPolicyArmProvenanceV1>,
}

impl<'a> ArmIndex<'a> {
    fn new(
        arm: &'a OnPolicyEvaluationArmInputsV1,
        count: usize,
    ) -> Result<Self, ProductEvaluationError> {
        if arm.targets.len() != count
            || arm.observations.len() != count
            || arm.assignments.len() != count
            || arm.provenance.len() != count
        {
            return Err(invalid("complete paired arm cohort"));
        }
        let indexed = Self {
            targets: arm.targets.iter().map(|row| (&row.decision_id, row)).collect(),
            observations: arm.observations.iter().map(|row| (&row.decision_id, row)).collect(),
            assignments: arm.assignments.iter().map(|row| (&row.decision_id, row)).collect(),
            provenance: arm.provenance.iter().map(|row| (&row.decision_id, row)).collect(),
        };
        if indexed.targets.len() != count
            || indexed.observations.len() != count
            || indexed.assignments.len() != count
            || indexed.provenance.len() != count
        {
            return Err(invalid("bijective original paired arm identities"));
        }
        Ok(indexed)
    }
}

#[derive(Default)]
struct EvidenceIdentities {
    sources: BTreeSet<[u8; 32]>,
    executions: BTreeSet<[u8; 32]>,
    outcomes: BTreeSet<[u8; 32]>,
}

fn validate_arm<'a>(
    pair: &OnPolicyPairContractV1,
    binding: &OnPolicyArmBindingV1,
    arm: &ArmIndex<'a>,
    frozen: &CrossFoldPlanReceiptV1,
    evidence: &mut EvidenceIdentities,
) -> Result<&'a HeldOutTarget, ProductEvaluationError> {
    let target = *arm.targets.get(&binding.decision_id)
        .ok_or_else(|| invalid("original paired target"))?;
    let row = *arm.observations.get(&binding.decision_id)
        .ok_or_else(|| invalid("original paired observation"))?;
    let assignment = *arm.assignments.get(&binding.decision_id)
        .ok_or_else(|| invalid("original paired assignment"))?;
    let provenance = *arm.provenance.get(&binding.decision_id)
        .ok_or_else(|| invalid("original paired provenance"))?;
    if target.principal_lineage != binding.principal_lineage
        || target.episode_lineage != binding.episode_lineage
        || target.window_id != frozen.final_holdout_window_id
        || assignment.cluster_id != binding.principal_lineage
        || provenance.episode_lineage != binding.episode_lineage
        || provenance.behavior_run_id != binding.behavior_run_id
        || provenance.model_digest != binding.model_digest
        || provenance.input_digest != pair.input_digest
        || provenance.protocol_digest != pair.protocol_digest
        || provenance.checkpoint_before != Digest32::ZERO
        || provenance.source_evidence_digest.is_zero()
        || provenance.execution_evidence_digest.is_zero()
        || row.outcome_evidence.is_zero()
        || !evidence.sources.insert(*provenance.source_evidence_digest.as_array())
        || !evidence.executions.insert(*provenance.execution_evidence_digest.as_array())
        || !evidence.outcomes.insert(*row.outcome_evidence.as_array())
    {
        return Err(invalid("original paired source execution and fresh empty state"));
    }
    if !row.complete_candidates
        || row.finalized_outcome.is_none()
        || target.actions.is_empty()
        || target.actions.len() > 128
        || row.actions.len() != target.actions.len()
    {
        return Err(invalid("complete paired on-policy outcome and actions"));
    }
    let actions: BTreeSet<_> = target.actions.iter().collect();
    if actions.len() != target.actions.len() || !actions.contains(&row.chosen_action) {
        return Err(invalid("paired supported action set"));
    }
    let mut seen = BTreeSet::new();
    for action in &row.actions {
        let expected = if action.action_id == row.chosen_action {
            i128::from(FixedQ32::ONE.raw())
        } else {
            0
        };
        if !seen.insert(&action.action_id)
            || !actions.contains(&action.action_id)
            || action.behavior_probability != action.evaluation_probability
            || i128::from(action.behavior_probability.raw()) != expected
        {
            return Err(invalid("actual deterministic on-policy probabilities"));
        }
    }
    Ok(target)
}

pub(super) fn validate_released_inputs(
    frozen: &CrossFoldPlanReceiptV1,
    pairing: &OnPolicyPairingContractV1,
    inputs: &OnPolicyTemporalComparisonInputsV1,
) -> Result<Digest32, ProductEvaluationError> {
    validate_pair_contract(pairing)?;
    if inputs.training.len() > 100_000
        || inputs.snapshot_ids.is_empty()
        || inputs.future_window_ids.is_empty()
    {
        return Err(invalid("paired earlier training and evidence identities"));
    }
    let candidate = ArmIndex::new(&inputs.candidate, pairing.pairs.len())?;
    let baseline = ArmIndex::new(&inputs.baseline, pairing.pairs.len())?;
    let mut evidence = EvidenceIdentities::default();
    let mut action_cells = 0_usize;
    for pair in &pairing.pairs {
        let left = validate_arm(pair, &pair.candidate, &candidate, frozen, &mut evidence)?;
        let right = validate_arm(pair, &pair.baseline, &baseline, frozen, &mut evidence)?;
        let left_actions: BTreeSet<_> = left.actions.iter().collect();
        let right_actions: BTreeSet<_> = right.actions.iter().collect();
        if left_actions != right_actions {
            return Err(invalid("same frozen paired action protocol"));
        }
        action_cells = action_cells.checked_add(left.actions.len())
            .filter(|value| *value <= 262_144)
            .ok_or_else(|| invalid("paired action cell bound"))?;
    }
    released_inputs_digest(pairing, inputs)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    super::super::push_id(bytes, id);
}

fn push_count(bytes: &mut Vec<u8>, count: usize) -> Result<(), ProductEvaluationError> {
    let count = u32::try_from(count).map_err(|_| invalid("paired input count"))?;
    bytes.extend_from_slice(&count.to_be_bytes());
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, ids: &[StableId]) -> Result<(), ProductEvaluationError> {
    push_count(bytes, ids.len())?;
    let mut sorted: Vec<_> = ids.iter().collect();
    sorted.sort();
    for id in sorted { push_id(bytes, id); }
    Ok(())
}

fn released_inputs_digest(
    pairing: &OnPolicyPairingContractV1,
    inputs: &OnPolicyTemporalComparisonInputsV1,
) -> Result<Digest32, ProductEvaluationError> {
    let mut bytes = b"hepta.intelligence-eval.paired-on-policy-inputs.v1".to_vec();
    bytes.extend_from_slice(pairing.digest()?.as_array());
    let mut training: Vec<_> = inputs.training.iter().collect();
    training.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    push_count(&mut bytes, training.len())?;
    for sample in training {
        let mut row = b"paired-earlier-training.v1".to_vec();
        for id in [&sample.decision_id, &sample.principal_lineage, &sample.episode_lineage,
            &sample.window_id, &sample.action_id] { push_id(&mut row, id); }
        row.extend_from_slice(&sample.outcome.raw().to_be_bytes());
        row.extend_from_slice(&sample.observed_at.to_be_bytes());
        row.extend_from_slice(sample.evidence_digest.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&row).as_array());
    }
    for (tag, arm) in [(0_u8, &inputs.candidate), (1_u8, &inputs.baseline)] {
        bytes.push(tag);
        push_arm(&mut bytes, arm)?;
    }
    push_ids(&mut bytes, &inputs.snapshot_ids)?;
    push_ids(&mut bytes, &inputs.future_window_ids)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn push_arm(
    bytes: &mut Vec<u8>,
    arm: &OnPolicyEvaluationArmInputsV1,
) -> Result<(), ProductEvaluationError> {
    let mut targets: Vec<_> = arm.targets.iter().collect();
    targets.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    push_count(bytes, targets.len())?;
    for target in targets {
        let mut row = b"paired-target.v1".to_vec();
        for id in [&target.decision_id, &target.principal_lineage,
            &target.episode_lineage, &target.window_id] { push_id(&mut row, id); }
        row.extend_from_slice(&target.decision_at.to_be_bytes());
        push_ids(&mut row, &target.actions)?;
        bytes.extend_from_slice(Digest32::of_bytes(&row).as_array());
    }
    let mut observations: Vec<_> = arm.observations.iter().collect();
    observations.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    push_count(bytes, observations.len())?;
    for observation in observations {
        let mut row = b"paired-observed-outcome.v1".to_vec();
        push_id(&mut row, &observation.decision_id);
        push_id(&mut row, &observation.chosen_action);
        row.push(u8::from(observation.complete_candidates));
        let mut actions: Vec<_> = observation.actions.iter().collect();
        actions.sort_by(|a, b| a.action_id.cmp(&b.action_id));
        push_count(&mut row, actions.len())?;
        for action in actions {
            push_id(&mut row, &action.action_id);
            row.extend_from_slice(&action.behavior_probability.raw().to_be_bytes());
            row.extend_from_slice(&action.evaluation_probability.raw().to_be_bytes());
            row.extend_from_slice(&action.predicted_outcome.raw().to_be_bytes());
        }
        let outcome = observation.finalized_outcome
            .ok_or_else(|| invalid("paired finalized outcome"))?;
        row.extend_from_slice(&outcome.raw().to_be_bytes());
        row.extend_from_slice(&observation.outcome_observed_at.to_be_bytes());
        row.extend_from_slice(observation.outcome_evidence.as_array());
        row.extend_from_slice(observation.outcome_model_evidence.as_array());
        bytes.extend_from_slice(Digest32::of_bytes(&row).as_array());
    }
    let mut assignments: Vec<_> = arm.assignments.iter().collect();
    assignments.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    push_count(bytes, assignments.len())?;
    for assignment in assignments {
        let mut row = b"paired-original-cluster.v1".to_vec();
        push_id(&mut row, &assignment.decision_id);
        push_id(&mut row, &assignment.cluster_id);
        bytes.extend_from_slice(Digest32::of_bytes(&row).as_array());
    }
    let mut provenance: Vec<_> = arm.provenance.iter().collect();
    provenance.sort_by(|a, b| a.decision_id.cmp(&b.decision_id));
    push_count(bytes, provenance.len())?;
    for original in provenance {
        let mut row = b"paired-original-run-provenance.v1".to_vec();
        for id in [&original.decision_id, &original.episode_lineage,
            &original.behavior_run_id] { push_id(&mut row, id); }
        for digest in [original.model_digest, original.input_digest,
            original.protocol_digest, original.checkpoint_before,
            original.source_evidence_digest, original.execution_evidence_digest] {
            row.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(Digest32::of_bytes(&row).as_array());
    }
    Ok(())
}
