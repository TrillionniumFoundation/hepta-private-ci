//! Original B data conversion, not admission or an independent-role capability.
//! The Root custodian authenticates the complete source and the separate policy
//! statement before conversion. Scores, missing outcomes and caller predictions
//! cannot be converted into probabilities, labels or model evidence here.

use std::collections::BTreeSet;
use std::io;

use codex_hepta_intelligence_eval::ClusterAssignment;
use codex_hepta_intelligence_eval::HeldOutTarget;
use codex_hepta_intelligence_eval::OpeAction;
use codex_hepta_intelligence_eval::OpeRow;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const MAX_BYTES: usize = 1_048_576;
const MAX_ROWS: usize = 2_048;
const MAX_ACTIONS: usize = 128;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalHoldoutSourceData {
    pub(super) schema: u8,
    pub(super) purpose: String,
    pub(super) objective: [u8; 32],
    pub(super) unit_profile: [u8; 32],
    pub(super) candidate_bundle: [u8; 32],
    pub(super) baseline_bundle: [u8; 32],
    pub(super) original_dataset: [u8; 32],
    pub(super) registered_at_seconds: u64,
    pub(super) collected_after_seconds: u64,
    training: Vec<TrainingRow>,
    heldout: Vec<HeldoutRow>,
    snapshot_ids: Vec<String>,
    future_window_ids: Vec<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TrainingRow {
    decision_id: String,
    principal_lineage: String,
    episode_lineage: String,
    window_id: String,
    action_id: String,
    outcome_q32: i64,
    observed_at_seconds: u64,
    original_evidence: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct HeldoutRow {
    decision_id: String,
    principal_lineage: String,
    episode_lineage: String,
    window_id: String,
    cluster_id: String,
    decision_at_seconds: u64,
    complete_candidates: bool,
    chosen_action: String,
    actions: Vec<OriginalPolicyAction>,
    finalized_outcome_q32: i64,
    observed_at_seconds: u64,
    original_outcome_evidence: [u8; 32],
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OriginalPolicyAction {
    action_id: String,
    behavior_probability_q32: u64,
    candidate_probability_q32: u64,
    baseline_probability_q32: u64,
}

impl OriginalHoldoutSourceData {
    pub(super) fn decode(bytes: &[u8]) -> io::Result<Self> {
        if bytes.is_empty() || bytes.len() > MAX_BYTES {
            return Err(io::Error::other("bounded original B source required"));
        }
        let data: Self = serde_json::from_slice(bytes).map_err(io::Error::other)?;
        if serde_json::to_vec(&data).map_err(io::Error::other)? != bytes
            || data.schema != 1
            || data.purpose != "runtime.learning.independent-b-source.v1"
            || [
                data.objective,
                data.unit_profile,
                data.candidate_bundle,
                data.baseline_bundle,
                data.original_dataset,
            ]
            .contains(&[0; 32])
            || data.registered_at_seconds == 0
            || data.collected_after_seconds <= data.registered_at_seconds
            || data.training.is_empty()
            || data.heldout.is_empty()
            || data.training.len() > MAX_ROWS
            || data.heldout.len() > MAX_ROWS
        {
            return Err(io::Error::other("canonical original B source differs"));
        }
        Ok(data)
    }

    /// This signed statement excludes outcome labels. Its original Generator
    /// must attest the complete behavior and both evaluation policies; the
    /// independent Observer attests the complete source separately.
    pub(super) fn policy_payload(&self) -> io::Result<Vec<u8>> {
        let rows: Vec<_> = self
            .heldout
            .iter()
            .map(|row| {
                (
                    &row.decision_id,
                    row.decision_at_seconds,
                    row.complete_candidates,
                    &row.chosen_action,
                    &row.actions,
                )
            })
            .collect();
        let body = serde_json::to_vec(&(
            self.objective,
            self.unit_profile,
            self.candidate_bundle,
            self.baseline_bundle,
            rows,
        ))
        .map_err(io::Error::other)?;
        Ok([
            b"hepta.root.independent-b.original-policies.v1\0".as_slice(),
            Digest32::of_bytes(&body).as_array(),
        ]
        .concat())
    }

    /// The manifest names the original held-out cohort and action universe,
    /// without allowing its labels to enter preregistration or fitting.
    pub(super) fn manifest_digest(&self) -> io::Result<Digest32> {
        let cohort: Vec<_> = self
            .heldout
            .iter()
            .map(|row| {
                (
                    &row.decision_id,
                    &row.principal_lineage,
                    &row.episode_lineage,
                    &row.window_id,
                    &row.cluster_id,
                    row.decision_at_seconds,
                    row.actions
                        .iter()
                        .map(|action| &action.action_id)
                        .collect::<Vec<_>>(),
                )
            })
            .collect();
        Ok(Digest32::of_parts(&[
            b"hepta.root.independent-b.original-cohort.v1\0",
            &serde_json::to_vec(&(self.objective, self.unit_profile, cohort))
                .map_err(io::Error::other)?,
        ]))
    }

    pub(super) fn inputs(&self) -> io::Result<TemporalComparisonInputsV1> {
        let mut decisions = BTreeSet::new();
        let mut training = Vec::with_capacity(self.training.len());
        for row in &self.training {
            let decision_id = id(&row.decision_id)?;
            if !decisions.insert(decision_id.clone())
                || row.original_evidence == [0; 32]
                || row.observed_at_seconds == 0
                || row.observed_at_seconds >= self.collected_after_seconds
            {
                return Err(io::Error::other("original B training lineage differs"));
            }
            training.push(OutcomeTrainingSample {
                decision_id,
                principal_lineage: id(&row.principal_lineage)?,
                episode_lineage: id(&row.episode_lineage)?,
                window_id: id(&row.window_id)?,
                action_id: id(&row.action_id)?,
                outcome: normalized_original(row.outcome_q32)?,
                observed_at: row.observed_at_seconds,
                evidence_digest: Digest32::from_array(row.original_evidence),
            });
        }
        let mut targets = Vec::with_capacity(self.heldout.len());
        let mut candidate_observations = Vec::with_capacity(self.heldout.len());
        let mut baseline_observations = Vec::with_capacity(self.heldout.len());
        let mut assignments = Vec::with_capacity(self.heldout.len());
        for row in &self.heldout {
            let decision_id = id(&row.decision_id)?;
            if !decisions.insert(decision_id.clone())
                || !row.complete_candidates
                || row.actions.is_empty()
                || row.actions.len() > MAX_ACTIONS
                || row.original_outcome_evidence == [0; 32]
                || row.decision_at_seconds < self.collected_after_seconds
                || row.observed_at_seconds < row.decision_at_seconds
            {
                return Err(io::Error::other("original B held-out lineage differs"));
            }
            let mut action_ids = BTreeSet::new();
            let mut candidate = Vec::with_capacity(row.actions.len());
            let mut baseline = Vec::with_capacity(row.actions.len());
            let mut totals = [0_u64; 3];
            for action in &row.actions {
                let action_id = id(&action.action_id)?;
                if !action_ids.insert(action_id.clone()) {
                    return Err(io::Error::other("duplicate original B action"));
                }
                let raw = [
                    action.behavior_probability_q32,
                    action.candidate_probability_q32,
                    action.baseline_probability_q32,
                ];
                let probabilities = raw.map(ProbabilityQ32::from_raw);
                let [behavior, left, right] = probabilities;
                let behavior = behavior.map_err(io::Error::other)?;
                let left = left.map_err(io::Error::other)?;
                let right = right.map_err(io::Error::other)?;
                for (sum, value) in totals.iter_mut().zip(raw) {
                    *sum = sum
                        .checked_add(value)
                        .ok_or_else(|| io::Error::other("B probability overflow"))?;
                }
                if behavior == ProbabilityQ32::ZERO
                    && (left != ProbabilityQ32::ZERO || right != ProbabilityQ32::ZERO)
                {
                    return Err(io::Error::other("unsupported original B policy action"));
                }
                let base = OpeAction {
                    action_id,
                    behavior_probability: behavior,
                    evaluation_probability: left,
                    predicted_outcome: FixedQ32::ZERO,
                };
                candidate.push(base.clone());
                baseline.push(OpeAction {
                    evaluation_probability: right,
                    ..base
                });
            }
            if totals != [ProbabilityQ32::ONE.raw(); 3] {
                return Err(io::Error::other(
                    "complete original B distributions required",
                ));
            }
            let chosen_action = id(&row.chosen_action)?;
            if !action_ids.contains(&chosen_action) {
                return Err(io::Error::other("original chosen B action is absent"));
            }
            targets.push(HeldOutTarget {
                decision_id: decision_id.clone(),
                principal_lineage: id(&row.principal_lineage)?,
                episode_lineage: id(&row.episode_lineage)?,
                window_id: id(&row.window_id)?,
                decision_at: row.decision_at_seconds,
                actions: action_ids.into_iter().collect(),
            });
            assignments.push(ClusterAssignment {
                decision_id: decision_id.clone(),
                cluster_id: id(&row.cluster_id)?,
            });
            // The native temporal runner replaces these two prediction-only
            // placeholders using its actual training-only fitted model.
            let observation = OpeRow {
                decision_id,
                chosen_action,
                complete_candidates: true,
                actions: candidate,
                finalized_outcome: Some(normalized_original(row.finalized_outcome_q32)?),
                outcome_observed_at: row.observed_at_seconds,
                outcome_evidence: Digest32::from_array(row.original_outcome_evidence),
                outcome_model_evidence: Digest32::ZERO,
            };
            candidate_observations.push(observation.clone());
            baseline_observations.push(OpeRow {
                actions: baseline,
                ..observation
            });
        }
        Ok(TemporalComparisonInputsV1 {
            training,
            targets,
            candidate_observations,
            baseline_observations,
            assignments,
            snapshot_ids: unique_ids(&self.snapshot_ids)?,
            future_window_ids: unique_ids(&self.future_window_ids)?,
        })
    }
}

fn id(value: &str) -> io::Result<StableId> {
    if value.len() > 128 {
        return Err(io::Error::other("bounded original B identity required"));
    }
    StableId::new(value).map_err(io::Error::other)
}

fn unique_ids(values: &[String]) -> io::Result<Vec<StableId>> {
    if values.is_empty() || values.len() > MAX_ROWS {
        return Err(io::Error::other("bounded original B lineage required"));
    }
    let ids = values
        .iter()
        .map(|value| id(value))
        .collect::<io::Result<Vec<_>>>()?;
    if ids.iter().collect::<BTreeSet<_>>().len() != ids.len() {
        return Err(io::Error::other("duplicate original B lineage"));
    }
    Ok(ids)
}

fn normalized_original(raw: i64) -> io::Result<FixedQ32> {
    let original = FixedQ32::from_raw(raw);
    if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&original) {
        return Err(io::Error::other(
            "original B outcome is outside its [0,1] unit",
        ));
    }
    Ok(original)
}

#[cfg(test)]
#[path = "authority_host_q24_evaluation_source_tests.rs"]
mod tests;
