//! Canonical input DATA for the independent process. No owner, completion or
//! native evaluation receipt can be constructed from these serialized rows.
#![cfg(test)]

use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::OriginalBusinessCase;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;

pub(super) const ROWS: usize = 256;
pub(super) const ACTIONS: [&str; 2] = ["persist", "skip"];
pub(super) const FINAL_WINDOW: &str = "ordinary-b-original-future-window";
pub(super) const TRAIN_WINDOW: &str = "ordinary-b-earlier-training-window";
pub(super) const ONE: i64 = 1_i64 << 32;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TrainingRow {
    pub(super) decision_id: String,
    pub(super) principal_lineage: String,
    pub(super) episode_lineage: String,
    pub(super) window_id: String,
    pub(super) action_id: String,
    pub(super) outcome_q32: i64,
    pub(super) observed_at_seconds: u64,
    pub(super) original_evidence: [u8; 32],
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CohortRow {
    pub(super) decision: String,
    pub(super) principal: String,
    pub(super) episode: String,
    pub(super) window: String,
    pub(super) cluster: String,
}

#[derive(Serialize)]
pub(super) struct ActionData {
    pub(super) action_id: String,
    pub(super) behavior_probability_q32: u64,
    pub(super) candidate_probability_q32: u64,
    pub(super) baseline_probability_q32: u64,
}

#[derive(Serialize)]
pub(super) struct HeldoutRow {
    pub(super) decision_id: String,
    pub(super) principal_lineage: String,
    pub(super) episode_lineage: String,
    pub(super) window_id: String,
    pub(super) cluster_id: String,
    pub(super) decision_at_seconds: u64,
    pub(super) complete_candidates: bool,
    pub(super) chosen_action: String,
    pub(super) actions: Vec<ActionData>,
    pub(super) finalized_outcome_q32: i64,
    pub(super) observed_at_seconds: u64,
    pub(super) original_outcome_evidence: [u8; 32],
}

#[derive(Serialize)]
pub(super) struct SourceData {
    pub(super) schema: u8,
    pub(super) purpose: &'static str,
    pub(super) objective: [u8; 32],
    pub(super) unit_profile: [u8; 32],
    pub(super) candidate_bundle: [u8; 32],
    pub(super) baseline_bundle: [u8; 32],
    pub(super) original_dataset: [u8; 32],
    pub(super) registered_at_seconds: u64,
    pub(super) collected_after_seconds: u64,
    pub(super) training: Vec<TrainingRow>,
    pub(super) heldout: Vec<HeldoutRow>,
    pub(super) snapshot_ids: Vec<String>,
    pub(super) future_window_ids: Vec<String>,
}

impl SourceData {
    pub(super) fn policy_payload(&self) -> std::io::Result<Vec<u8>> {
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
        .map_err(std::io::Error::other)?;
        Ok([
            b"hepta.root.independent-b.original-policies.v1\0".as_slice(),
            Digest32::of_bytes(&body).as_array(),
        ]
        .concat())
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct BaselineBytes {
    pub(super) base: Vec<u8>,
    pub(super) encoder: Vec<u8>,
    pub(super) heads: Vec<u8>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ProducerData {
    pub(super) schema: u8,
    pub(super) case: OriginalBusinessCase,
    pub(super) initial: [u8; 32],
    pub(super) objective: [u8; 32],
    pub(super) unit_profile: [u8; 32],
    pub(super) protocol: [u8; 32],
    pub(super) baseline_bundle: [u8; 32],
    pub(super) baseline: BaselineBytes,
    pub(super) input: Vec<u8>,
    pub(super) training: Vec<TrainingRow>,
    pub(super) cohort: Vec<CohortRow>,
    pub(super) training_watermark: u64,
    pub(super) evaluation_start: u64,
    pub(super) outcome_watermark: u64,
    pub(super) expires_at_seconds: u64,
    pub(super) business_directory: PathBuf,
    pub(super) trust: LearningTrustPayloadV1,
    pub(super) generator_key: [u8; 32],
    pub(super) observer_key: [u8; 32],
}

pub(super) fn cohort() -> Vec<CohortRow> {
    (0..ROWS)
        .map(|index| CohortRow {
            decision: format!("ordinary-b-heldout-{index}"),
            principal: format!("ordinary-b-independent-principal-{index}"),
            episode: format!("ordinary-b-independent-episode-{index}"),
            window: FINAL_WINDOW.into(),
            cluster: format!("ordinary-b-independent-cluster-{index}"),
        })
        .collect()
}

pub(super) fn cohort_digest(
    objective: [u8; 32],
    unit_profile: [u8; 32],
    rows: &[CohortRow],
) -> std::io::Result<Digest32> {
    let cohort: Vec<_> = rows
        .iter()
        .map(|row| {
            (
                &row.decision,
                &row.principal,
                &row.episode,
                &row.window,
                &row.cluster,
                ACTIONS.to_vec(),
            )
        })
        .collect();
    let bytes =
        serde_json::to_vec(&(objective, unit_profile, cohort)).map_err(std::io::Error::other)?;
    Ok(Digest32::of_parts(&[
        b"hepta.root.independent-b.original-cohort.v2\0",
        &bytes,
    ]))
}
