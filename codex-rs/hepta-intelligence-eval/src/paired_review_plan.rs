//! Original unsealed feature inputs for cross-process independent recomputation.
//! This codec never imports caller-supplied clusters or a sealed plan receipt.
use crate::recorded_publication::archive::codec::Reader;
use crate::recorded_publication::archive::codec::Wire;
use crate::recorded_publication::archive::codec::Writer;
use crate::recorded_publication::archive::codec::structure;
use crate::recorded_publication::archive::codec::{self};
use crate::*;

const DOMAIN: &[u8] = b"hepta.eval.paired-supervised.review-plan-inputs.v1";

/// Label-free source and prespecified native inputs. Each recipient derives the
/// complete graph and freezes the existing plan before verifying G/O signatures.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedReviewSourcePlanV1 {
    pub base_plan: CrossFoldPlanV1,
    pub source_scope: TaskSourceScopeV1,
    pub source_records: Vec<TaskSourceRecordV1>,
    pub folds: Vec<TaskCrossFoldInputsV1>,
    pub unscored_source_records: Vec<codex_hepta_types::Digest32>,
    pub tasks: Vec<PairedTaskBindingV1>,
    pub runtime: PairedRuntimeBindingV1,
    pub policy: PairedBenchmarkPolicyV1,
    pub metrics: Vec<PairedMetricContractV1>,
}

impl PairedReviewSourcePlanV1 {
    pub fn freeze(&self) -> Result<PairedSupervisedPlanV1, PairedSupervisedErrorV1> {
        if !self.base_plan.folds.is_empty() {
            return Err(PairedSupervisedErrorV1::Binding(
                "review folds must derive from source",
            ));
        }
        freeze_paired_supervised_plan_v1(PairedSupervisedPlanInputsV1 {
            base_plan: self.base_plan.clone(),
            source: FrozenTaskSourceLineageV1::freeze(&self.source_scope, &self.source_records)?,
            folds: self.folds.clone(),
            unscored_source_records: self.unscored_source_records.clone(),
            tasks: self.tasks.clone(),
            runtime: self.runtime.clone(),
            policy: self.policy.clone(),
            metrics: self.metrics.clone(),
        })
    }

    pub(crate) fn encode(&self) -> codec::Result<Vec<u8>> {
        let mut output = Writer::default();
        output.put(DOMAIN)?;
        self.write(&mut output)?;
        Ok(output.finish())
    }

    pub(crate) fn decode(bytes: &[u8]) -> codec::Result<Self> {
        let mut input = Reader::new(bytes)?;
        if input.take(DOMAIN.len())? != DOMAIN {
            return Err(codec::invalid());
        }
        let value = Self::read(&mut input)?;
        input.finish()?;
        if value.encode()? != bytes {
            return Err(codec::invalid());
        }
        Ok(value)
    }
}

structure!(PairedReviewSourcePlanV1 {
    base_plan,
    source_scope,
    source_records,
    folds,
    unscored_source_records,
    tasks,
    runtime,
    policy,
    metrics
});
structure!(TaskSourceScopeV1 {
    objective_digest,
    task_definition_digest,
    source_archive_digest
});
structure!(TaskSourceRecordV1 {
    source_file_digest,
    source_row_index,
    source_record_digest,
    task_id,
    dependency_ids
});
structure!(TaskCrossFoldInputsV1 {
    fold_id,
    training_records,
    holdout_records,
    training_windows,
    holdout_windows,
    model_digest,
    predictions_digest
});
structure!(CrossFoldPartitionV1 {
    fold_id,
    training_principals,
    training_episodes,
    training_windows,
    holdout_principals,
    holdout_episodes,
    holdout_windows,
    model_digest,
    predictions_digest
});
structure!(CrossFoldPlanV1 {
    plan_id,
    claim_scope,
    candidate_id,
    baseline_id,
    objective_digest,
    dataset_digest,
    estimand_digest,
    metric_contracts,
    family_alpha_ppm,
    simultaneous_comparisons,
    folds,
    final_holdout_window_id,
    final_holdout_digest
});
structure!(MetricContractV1 {
    metric_id,
    direction,
    safety_floor
});
structure!(PairedTaskBindingV1 {
    source_record_digest,
    candidate_request_id,
    baseline_request_id,
    candidate_input_digest,
    baseline_input_digest
});
structure!(PairedRuntimeBindingV1 {
    candidate_artifact_digest,
    deployed_baseline_digest,
    candidate_runtime_digest,
    baseline_runtime_digest,
    task_input_contract_digest
});
structure!(PairedEvidenceMetricsV1 {
    execution_cost,
    retention,
    unlearning
});
structure!(PairedMetricContractV1 {
    contract,
    role,
    kind
});

impl Wire for PairedBenchmarkPolicyV1 {
    fn write(&self, output: &mut Writer) -> codec::Result<()> {
        self.required_evidence_metrics.write(output)?;
        self.output_alphabet.write(output)?;
        self.assumptions_digest.write(output)?;
        u64::try_from(self.minimum_independent_clusters)
            .map_err(|_| codec::invalid())?
            .write(output)?;
        self.maximum_abstain_ppm.write(output)?;
        self.maximum_execution_window_micros.write(output)
    }
    fn read(input: &mut Reader<'_>) -> codec::Result<Self> {
        Ok(Self {
            required_evidence_metrics: Wire::read(input)?,
            output_alphabet: Wire::read(input)?,
            assumptions_digest: Wire::read(input)?,
            minimum_independent_clusters: usize::try_from(u64::read(input)?)
                .map_err(|_| codec::invalid())?,
            maximum_abstain_ppm: Wire::read(input)?,
            maximum_execution_window_micros: Wire::read(input)?,
        })
    }
}
impl Wire for PairedMetricKindV1 {
    fn write(&self, output: &mut Writer) -> codec::Result<()> {
        match self {
            Self::ClassificationAccuracy => 0_u8.write(output),
            Self::ExecutionLatencyMillis { maximum } => {
                1_u8.write(output)?;
                maximum.write(output)
            }
            Self::ObservedBounded { minimum, maximum } => {
                2_u8.write(output)?;
                minimum.write(output)?;
                maximum.write(output)
            }
        }
    }
    fn read(input: &mut Reader<'_>) -> codec::Result<Self> {
        match u8::read(input)? {
            0 => Ok(Self::ClassificationAccuracy),
            1 => Ok(Self::ExecutionLatencyMillis {
                maximum: Wire::read(input)?,
            }),
            2 => Ok(Self::ObservedBounded {
                minimum: Wire::read(input)?,
                maximum: Wire::read(input)?,
            }),
            _ => Err(codec::invalid()),
        }
    }
}
