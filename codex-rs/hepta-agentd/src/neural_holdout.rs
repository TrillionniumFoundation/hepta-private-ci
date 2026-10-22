//! Real neural forwards at the original FinalHoldoutProvider boundary.
//! The original runner owns consumption, OPE/intervals and qualification. This
//! adapter owns only bounded frozen scoring material and exact inference
//! observations. It issues no selection, installation or independent-efficacy
//! claim; its inference ports must retain their original journal and FinalUse.

use std::sync::Arc;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::NeuralCognitiveInferencePortV1;
use crate::NeuralCognitivePinV1;
use crate::NeuralCognitiveRequestV1;

#[path = "neural_holdout_material.rs"]
mod material;
pub use material::NeuralHoldoutMaterialV1;
pub use material::NeuralHoldoutTaskV1;

/// Existing inference-owner endpoint and its exact captured parameter bytes.
/// Construct/warm the endpoint under the original resource and FinalUse owner;
/// this adapter cannot authorize or cold-load a model on the caller's behalf.
pub struct NeuralHoldoutRuntimeV1 {
    pub pin: NeuralCognitivePinV1,
    pub parameters: Vec<u8>,
    pub inference: Arc<dyn NeuralCognitiveInferencePortV1>,
}

/// Scorer-owned comparison evidence; expected actions never enter a model.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuralHoldoutObservationV1 {
    pub decision_id: StableId,
    pub query_digest: Digest32,
    pub candidate_scores_q32: [i64; 2],
    pub baseline_scores_q32: [i64; 2],
    pub candidate_choice: StableId,
    pub baseline_choice: StableId,
    pub logged_action: StableId,
    pub logged_correct: bool,
    pub candidate_correct: bool,
    pub baseline_correct: bool,
    pub candidate_receipt_digest: Digest32,
    pub baseline_receipt_digest: Digest32,
    pub decision_at: u64,
    pub outcome_observed_at: u64,
    pub evidence_digest: Digest32,
}

pub struct NeuralFinalHoldoutProviderV1 {
    material: NeuralHoldoutMaterialV1,
    plan_digest: Digest32,
    manifest_digest: Digest32,
    dataset: DatasetSnapshotReceiptV3,
    ledger: LedgerSnapshot,
    candidate: NeuralHoldoutRuntimeV1,
    baseline: NeuralHoldoutRuntimeV1,
    released: bool,
    observations: Vec<NeuralHoldoutObservationV1>,
}

impl NeuralFinalHoldoutProviderV1 {
    pub fn new(
        material: NeuralHoldoutMaterialV1,
        plan: &eval::ProductFrozenEvaluationPlanV1,
        dataset: DatasetSnapshotReceiptV3,
        ledger: LedgerSnapshot,
        candidate: NeuralHoldoutRuntimeV1,
        baseline: NeuralHoldoutRuntimeV1,
    ) -> Result<Self, String> {
        let manifest_digest = material.manifest_digest()?;
        let training = material::training(&dataset, &ledger, now_micros()?)?;
        if material.candidate != candidate.pin
            || material.baseline != baseline.pin
            || material.candidate.dataset_digest != dataset.snapshot.dataset_digest
            || material.candidate.objective_digest != dataset.snapshot.objective_digest
            || plan.frozen_plan.dataset_digest != dataset.snapshot.dataset_digest
            || plan.frozen_plan.objective_digest != dataset.snapshot.objective_digest
            || plan.frozen_plan.final_holdout_digest != manifest_digest
            || plan.frozen_plan.final_holdout_window_id != material.final_window_id
            || material.final_window_id == dataset.snapshot.snapshot_id
            || material.holdout_snapshot_id == dataset.snapshot.snapshot_id
            || plan.frozen_plan.authority.grants_any()
        {
            return Err(
                "neural holdout differs from its frozen model, dataset or runner plan".to_owned(),
            );
        }
        for runtime in [&candidate, &baseline] {
            if runtime.parameters.is_empty()
                || runtime.parameters.len() > 16 * 1024 * 1024
                || Digest32::of_bytes(&runtime.parameters) != runtime.pin.payload_digest
            {
                return Err("neural holdout parameter identity/size mismatch".to_owned());
            }
        }
        for task in &material.tasks {
            if training.iter().any(|row| {
                row.decision_id == task.decision_id
                    || row.principal_lineage == task.principal_lineage
                    || row.episode_lineage == task.episode_lineage
            }) {
                return Err("neural holdout overlaps frozen estimator training lineage".to_owned());
            }
        }
        if material
            .actions
            .iter()
            .any(|action| !training.iter().any(|row| &row.action_id == action))
        {
            return Err("neural holdout action lacks original training support".to_owned());
        }
        Ok(Self {
            material,
            plan_digest: plan.frozen_plan.plan_digest,
            manifest_digest,
            dataset,
            ledger,
            candidate,
            baseline,
            released: false,
            observations: Vec::new(),
        })
    }

    pub fn observations(&self) -> &[NeuralHoldoutObservationV1] {
        &self.observations
    }
}

impl eval::FinalHoldoutProviderV1 for NeuralFinalHoldoutProviderV1 {
    fn manifest_digest(&mut self) -> Result<Digest32, eval::ProductProviderErrorV1> {
        Ok(self.manifest_digest)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &eval::FinalHoldoutJournalReceiptV1,
    ) -> Result<eval::TemporalComparisonInputsV1, eval::ProductProviderErrorV1> {
        use eval::ProductProviderErrorV1::Indeterminate;
        use eval::ProductProviderErrorV1::Rejected;
        if self.released
            || receipt.disposition != eval::HoldoutUseDispositionV1::Recorded
            || receipt.sequence == 0
            || receipt.record_digest.is_zero()
            || receipt.head_digest.is_zero()
            || receipt.use_receipt.plan_digest != self.plan_digest
            || receipt.use_receipt.holdout_digest != self.manifest_digest
            || receipt.use_receipt.final_holdout_window_id != self.material.final_window_id
            || receipt.use_receipt.objective_digest != self.material.candidate.objective_digest
            || receipt.use_receipt.dataset_digest != self.material.candidate.dataset_digest
            || receipt.use_receipt.disposition != eval::HoldoutUseDispositionV1::Recorded
            || receipt.use_receipt.authority.grants_any()
            || receipt.authority.grants_any()
        {
            return Err(Rejected);
        }
        // A partial execution never earns a retry or a complete estimator input.
        // The original runner has already durably consumed the frozen holdout.
        self.released = true;
        let training = material::training(
            &self.dataset,
            &self.ledger,
            now_micros().map_err(|_| Rejected)?,
        )
        .map_err(|_| Rejected)?;
        let behavior_probability = ProbabilityQ32::from_raw(1 << 31).map_err(|_| Rejected)?;
        let mut inputs = eval::TemporalComparisonInputsV1 {
            training,
            targets: Vec::new(),
            candidate_observations: Vec::new(),
            baseline_observations: Vec::new(),
            assignments: Vec::new(),
            snapshot_ids: vec![
                self.dataset.snapshot.snapshot_id.clone(),
                self.material.holdout_snapshot_id.clone(),
            ],
            future_window_ids: vec![self.material.final_window_id.clone()],
        };
        let started = Instant::now();
        for task in &self.material.tasks {
            if started.elapsed().as_secs() >= 120 {
                return Err(Indeterminate);
            }
            let decision_at = now_micros().map_err(|_| Indeterminate)?;
            if decision_at <= self.dataset.snapshot.outcome_watermark {
                return Err(Rejected);
            }
            let query_digest = Digest32::of_bytes(task.query.as_bytes());
            let request = |pin: &NeuralCognitivePinV1| NeuralCognitiveRequestV1 {
                owner_id: self.material.owner_id.clone(),
                body_generation: self.material.body_generation,
                pin: pin.clone(),
                query: task.query.clone(),
                query_digest,
                action_ids: self.material.actions.to_vec(),
            };
            // Alternate the frozen execution order without changing either
            // model's input or the logged-action policy after seeing outcomes.
            let (candidate, baseline) = if inputs.targets.len().is_multiple_of(2) {
                let candidate = execute(&self.candidate, request(&self.candidate.pin))
                    .map_err(|_| Indeterminate)?;
                let baseline = execute(&self.baseline, request(&self.baseline.pin))
                    .map_err(|_| Indeterminate)?;
                (candidate, baseline)
            } else {
                let baseline = execute(&self.baseline, request(&self.baseline.pin))
                    .map_err(|_| Indeterminate)?;
                let candidate = execute(&self.candidate, request(&self.candidate.pin))
                    .map_err(|_| Indeterminate)?;
                (candidate, baseline)
            };
            let outcome_observed_at = now_micros().map_err(|_| Indeterminate)?;
            if outcome_observed_at < decision_at || started.elapsed().as_secs() >= 120 {
                return Err(Indeterminate);
            }
            let winner = |scores: [i64; 2]| usize::from(scores[1] > scores[0]);
            let candidate_choice = self.material.actions[winner(candidate.0)].clone();
            let baseline_choice = self.material.actions[winner(baseline.0)].clone();
            let logged = Digest32::of_parts(&[
                b"hepta.neural-holdout.bernoulli.v1\0",
                &self.material.logging_seed,
                task.decision_id.as_str().as_bytes(),
            ]);
            let logged_action =
                self.material.actions[usize::from(logged.as_array()[0] & 1)].clone();
            let logged_correct = logged_action == task.expected_action;
            let bytes = serde_json::to_vec(&(
                self.manifest_digest.to_string(),
                self.plan_digest.to_string(),
                receipt.head_digest.to_string(),
                task.decision_id.as_str(),
                query_digest.to_string(),
                candidate.0,
                baseline.0,
                candidate.1.to_string(),
                baseline.1.to_string(),
                logged_action.as_str(),
                logged_correct,
                decision_at,
                outcome_observed_at,
            ))
            .map_err(|_| Indeterminate)?;
            let evidence_digest = Digest32::of_bytes(&bytes);
            let row = |choice: &StableId| eval::OpeRow {
                decision_id: task.decision_id.clone(),
                chosen_action: logged_action.clone(),
                complete_candidates: true,
                actions: self
                    .material
                    .actions
                    .iter()
                    .map(|action| eval::OpeAction {
                        action_id: action.clone(),
                        behavior_probability,
                        evaluation_probability: if action == choice {
                            ProbabilityQ32::ONE
                        } else {
                            ProbabilityQ32::ZERO
                        },
                        predicted_outcome: FixedQ32::ZERO,
                    })
                    .collect(),
                finalized_outcome: Some(if logged_correct {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                }),
                outcome_observed_at,
                outcome_evidence: evidence_digest,
                outcome_model_evidence: Digest32::ZERO,
            };
            inputs.candidate_observations.push(row(&candidate_choice));
            inputs.baseline_observations.push(row(&baseline_choice));
            inputs.targets.push(eval::HeldOutTarget {
                decision_id: task.decision_id.clone(),
                principal_lineage: task.principal_lineage.clone(),
                episode_lineage: task.episode_lineage.clone(),
                window_id: self.material.final_window_id.clone(),
                decision_at,
                actions: self.material.actions.to_vec(),
            });
            inputs.assignments.push(eval::ClusterAssignment {
                decision_id: task.decision_id.clone(),
                cluster_id: task.cluster_id.clone(),
            });
            self.observations.push(NeuralHoldoutObservationV1 {
                decision_id: task.decision_id.clone(),
                query_digest,
                candidate_scores_q32: candidate.0,
                baseline_scores_q32: baseline.0,
                candidate_correct: candidate_choice == task.expected_action,
                baseline_correct: baseline_choice == task.expected_action,
                candidate_choice,
                baseline_choice,
                logged_action,
                logged_correct,
                candidate_receipt_digest: candidate.1,
                baseline_receipt_digest: baseline.1,
                decision_at,
                outcome_observed_at,
                evidence_digest,
            });
        }
        Ok(inputs)
    }
}

fn execute(
    runtime: &NeuralHoldoutRuntimeV1,
    request: NeuralCognitiveRequestV1,
) -> Result<([i64; 2], Digest32), String> {
    let observation = runtime.inference.execute(&request, &runtime.parameters)?;
    if observation.request != request
        || observation.authority != AuthorityPosture::DENY_ALL
        || observation.execution_receipt_digest.is_zero()
    {
        return Err("neural comparison observation binding mismatch".to_owned());
    }
    let scores = observation
        .scores_q32
        .ok_or("neural comparison abstained")?;
    let scores: [i64; 2] = scores
        .try_into()
        .map_err(|_| "neural comparison incomplete scores")?;
    Ok((scores, observation.execution_receipt_digest))
}

fn now_micros() -> Result<u64, String> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_micros(),
    )
    .map_err(|error| error.to_string())
}
