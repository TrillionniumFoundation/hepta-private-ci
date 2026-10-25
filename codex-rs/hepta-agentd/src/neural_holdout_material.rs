//! Frozen scoring material for the original neural comparison provider.
//! Expected actions remain in this owner and are never part of a model request.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval::OutcomeTrainingSample;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_against_ledger_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::NeuralCognitivePinV1;

/// One prespecified task. The scorer owns `expected_action`; inference receives
/// only `query` and the material's common, complete action vocabulary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralHoldoutTaskV1 {
    pub decision_id: StableId,
    pub principal_lineage: StableId,
    pub episode_lineage: StableId,
    pub cluster_id: StableId,
    pub query: String,
    pub expected_action: StableId,
}

/// A bounded two-action comparison, frozen before either model is evaluated.
/// The original custodian must draw the logging seed without outcome-based
/// search before committing this material. A seed/digest is not evidence of
/// independent administration, prospective efficacy, or product qualification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralHoldoutMaterialV1 {
    pub owner_id: AgentId,
    pub body_generation: u64,
    pub candidate: NeuralCognitivePinV1,
    pub baseline: NeuralCognitivePinV1,
    pub logging_seed: [u8; 32],
    pub actions: [StableId; 2],
    pub final_window_id: StableId,
    pub holdout_snapshot_id: StableId,
    pub tasks: Vec<NeuralHoldoutTaskV1>,
}

impl NeuralHoldoutMaterialV1 {
    pub fn manifest_digest(&self) -> Result<Digest32, String> {
        if self.body_generation == 0
            || !(2..=32).contains(&self.tasks.len())
            || self.logging_seed == [0; 32]
            || self.actions[0] >= self.actions[1]
            || self.candidate.generation.get()
                != self
                    .baseline
                    .generation
                    .get()
                    .checked_add(1)
                    .ok_or("neural generation overflow")?
            || self.candidate.family_digest != self.baseline.family_digest
            || self.candidate.objective_digest != self.baseline.objective_digest
        {
            return Err("neural holdout identity, lineage, vocabulary or task bound".to_owned());
        }
        for pin in [&self.candidate, &self.baseline] {
            if [
                pin.payload_digest,
                pin.objective_digest,
                pin.dataset_digest,
                pin.family_digest,
                pin.execution_profile_digest,
            ]
            .into_iter()
            .any(Digest32::is_zero)
            {
                return Err("neural holdout has an empty immutable model pin".to_owned());
            }
        }
        let mut decisions = BTreeSet::new();
        let mut queries = BTreeSet::new();
        for task in &self.tasks {
            if task.query.is_empty()
                || task.query.len() > 2048
                || !self.actions.contains(&task.expected_action)
                || !decisions.insert(&task.decision_id)
                || !queries.insert(&task.query)
            {
                return Err("neural holdout contains an invalid or repeated task".to_owned());
            }
        }
        let pin = |pin: &NeuralCognitivePinV1| {
            serde_json::json!({
                "payload":pin.payload_digest.to_string(), "objective":pin.objective_digest.to_string(),
                "dataset":pin.dataset_digest.to_string(), "generation":pin.generation.get(),
                "family":pin.family_digest.to_string(), "execution_profile":pin.execution_profile_digest.to_string(),
            })
        };
        let tasks = self.tasks.iter().map(|task| serde_json::json!({
            "decision":task.decision_id.as_str(), "principal":task.principal_lineage.as_str(),
            "episode":task.episode_lineage.as_str(), "cluster":task.cluster_id.as_str(),
            "query":&task.query, "expected_action":task.expected_action.as_str(),
        })).collect::<Vec<_>>();
        let material = serde_json::json!({
            "schema":"hepta-neural-two-action-holdout-v1", "choice":"argmax-stable-first-v1",
            "logging":"sha256-seeded-bernoulli-half-v1", "owner":self.owner_id.as_str(),
            "body_generation":self.body_generation, "candidate":pin(&self.candidate), "baseline":pin(&self.baseline),
            "seed":self.logging_seed, "actions":self.actions.iter().map(StableId::as_str).collect::<Vec<_>>(),
            "window":self.final_window_id.as_str(), "snapshot":self.holdout_snapshot_id.as_str(), "tasks":tasks,
        });
        serde_json::to_vec(&material)
            .map(|bytes| Digest32::of_bytes(&bytes))
            .map_err(|error| error.to_string())
    }
}

/// Derive nuisance-estimator training only from the original frozen ledger.
/// This does not train the neural model. Legacy/ambiguous/corrected outcome
/// histories are not silently projected into this narrow authenticated profile.
pub(super) fn training(
    dataset: &DatasetSnapshotReceiptV3,
    snapshot: &LedgerSnapshot,
    now: u64,
) -> Result<Vec<OutcomeTrainingSample>, String> {
    verify_dataset_snapshot_receipt_against_ledger_v3(dataset, snapshot, now)
        .map_err(|error| error.to_string())?;
    if snapshot.records().len() > 512 {
        return Err("neural comparison ledger exceeds bound".to_owned());
    }
    let sources = dataset
        .snapshot
        .source_record_digests
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    let mut decisions = BTreeMap::new();
    let mut outcomes = Vec::new();
    for record in snapshot
        .records()
        .iter()
        .filter(|record| sources.contains(&record.event_digest))
    {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(decision) => {
                if decision.objective_digest != dataset.snapshot.objective_digest
                    || decision.authentication_digest.is_zero()
                    || decisions
                        .insert(decision.episode_id.clone(), decision)
                        .is_some()
                {
                    return Err("neural comparison decision provenance mismatch".to_owned());
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(outcome) => {
                outcomes.push((record.event_digest, outcome))
            }
            LedgerEvent::Decision(_) | LedgerEvent::Outcome(_) => {
                return Err(
                    "neural comparison requires authenticated original ledger outcomes".to_owned(),
                );
            }
            LedgerEvent::RetrievalAssignment(_)
            | LedgerEvent::Credit(_)
            | LedgerEvent::PromptDelivery(_)
            | LedgerEvent::Revocation(_)
            | LedgerEvent::CreditBatchV2(_)
            | LedgerEvent::UnlearningLineageV1(_) => {}
        }
    }
    if !(2..=128).contains(&outcomes.len()) {
        return Err("neural comparison training outcome bound".to_owned());
    }
    let mut episodes = BTreeSet::new();
    let mut samples = Vec::new();
    for (evidence_digest, outcome) in outcomes {
        let decision = decisions
            .get(&outcome.episode_id)
            .ok_or("neural comparison outcome lacks its frozen decision")?;
        let observed_at = outcome
            .observed_at
            .ok_or("neural comparison pending observation")?;
        let finalized_at = outcome
            .finalized_at
            .ok_or("neural comparison unfinalized outcome")?;
        let value = outcome.value.ok_or("neural comparison missing outcome")?;
        if outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
            || outcome.authentication_digest.is_zero()
            || outcome.correction_predecessor.is_some()
            || !episodes.insert(&outcome.episode_id)
            || !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&value)
            || observed_at > dataset.snapshot.outcome_watermark
            || finalized_at > dataset.snapshot.outcome_watermark
        {
            return Err(
                "neural comparison outcome is not an unambiguous frozen terminal observation"
                    .to_owned(),
            );
        }
        samples.push(OutcomeTrainingSample {
            decision_id: decision.record_id.clone(),
            principal_lineage: decision.generator_id.clone(),
            episode_lineage: outcome.episode_id.clone(),
            window_id: dataset.snapshot.snapshot_id.clone(),
            action_id: decision.selected_candidate_id.clone(),
            outcome: value,
            observed_at,
            evidence_digest,
        });
    }
    samples.sort_by(|left, right| left.decision_id.cmp(&right.decision_id));
    Ok(samples)
}
