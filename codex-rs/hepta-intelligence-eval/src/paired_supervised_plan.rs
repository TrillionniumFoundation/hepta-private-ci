//! Frozen full-information benchmark scope, separate from behavior-policy OPE.
//! Source custody must attest the complete graph and eligible task manifest.
//! The graph derives dependency clusters; callers never supply cluster labels.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::CrossFoldPlanReceiptV1;
use crate::CrossFoldPlanV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationClosureError;
use crate::EvaluationDirectionV1;
use crate::FrozenTaskSourceLineageV1;
use crate::MetricContractV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::TaskCrossFoldInputsV1;
use crate::TaskLineageError;
use crate::freeze_cross_fold_plan_v2;
use crate::push_id;

pub(crate) const MAX_PAIRED_TASKS: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PairedMetricKindV1 {
    /// Observer-authenticated correctness; terminal ABSTAIN is incorrect.
    ClassificationAccuracy,
    /// Original monotonic execution cost, derived from the native observation.
    ExecutionLatencyMillis { maximum: FixedQ32 },
    /// An actual scalar observation, including registered cost or retention
    /// measures. Bounds are frozen before execution, not fitted to results.
    ObservedBounded {
        minimum: FixedQ32,
        maximum: FixedQ32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedMetricContractV1 {
    pub contract: MetricContractV1,
    pub role: MetricRoleV2,
    pub kind: PairedMetricKindV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedTaskBindingV1 {
    pub source_record_digest: Digest32,
    pub candidate_request_id: StableId,
    pub baseline_request_id: StableId,
    pub candidate_input_digest: Digest32,
    pub baseline_input_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedRuntimeBindingV1 {
    pub candidate_artifact_digest: Digest32,
    pub deployed_baseline_digest: Digest32,
    pub candidate_runtime_digest: Digest32,
    pub baseline_runtime_digest: Digest32,
    pub task_input_contract_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedEvidenceMetricsV1 {
    pub execution_cost: StableId,
    pub retention: StableId,
    pub unlearning: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedBenchmarkPolicyV1 {
    pub required_evidence_metrics: PairedEvidenceMetricsV1,
    pub output_alphabet: Vec<StableId>,
    pub assumptions_digest: Digest32,
    pub minimum_independent_clusters: usize,
    pub maximum_abstain_ppm: u32,
    pub maximum_execution_window_micros: u64,
}

pub struct PairedSupervisedPlanInputsV1 {
    pub base_plan: CrossFoldPlanV1,
    pub source: FrozenTaskSourceLineageV1,
    /// Actual source memberships and prior training/prediction artifact pins.
    /// No final prediction hash or future event timestamp is invented here.
    pub folds: Vec<TaskCrossFoldInputsV1>,
    /// Complete graph records with no scored/training role, including bridge
    /// claim nodes. The custody owner checks this against its original manifest.
    pub unscored_source_records: Vec<Digest32>,
    pub tasks: Vec<PairedTaskBindingV1>,
    pub runtime: PairedRuntimeBindingV1,
    pub policy: PairedBenchmarkPolicyV1,
    pub metrics: Vec<PairedMetricContractV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedSupervisedPlanV1 {
    pub(crate) frozen: CrossFoldPlanReceiptV1,
    pub(crate) source: FrozenTaskSourceLineageV1,
    pub(crate) tasks: BTreeMap<Digest32, PairedTaskBindingV1>,
    pub(crate) runtime: PairedRuntimeBindingV1,
    pub(crate) policy: PairedBenchmarkPolicyV1,
    pub(crate) metrics: Vec<PairedMetricContractV1>,
    pub(crate) profile_digest: Digest32,
    pub(crate) source_membership_digest: Digest32,
    receipt_seal: Digest32,
}

#[derive(Debug)]
pub enum PairedSupervisedErrorV1 {
    Binding(&'static str),
    Incomplete { tasks: usize, censored: usize },
    InsufficientClusters,
    Arithmetic,
    Lineage(TaskLineageError),
    Closure(EvaluationClosureError),
    Product(crate::ProductEvaluationError),
    Signed(crate::SignedEvaluationError),
}

impl fmt::Display for PairedSupervisedErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for PairedSupervisedErrorV1 {}
impl From<TaskLineageError> for PairedSupervisedErrorV1 {
    fn from(value: TaskLineageError) -> Self {
        Self::Lineage(value)
    }
}
impl From<EvaluationClosureError> for PairedSupervisedErrorV1 {
    fn from(value: EvaluationClosureError) -> Self {
        Self::Closure(value)
    }
}
impl From<crate::ProductEvaluationError> for PairedSupervisedErrorV1 {
    fn from(value: crate::ProductEvaluationError) -> Self {
        Self::Product(value)
    }
}
impl From<crate::SignedEvaluationError> for PairedSupervisedErrorV1 {
    fn from(value: crate::SignedEvaluationError) -> Self {
        Self::Signed(value)
    }
}

pub fn freeze_paired_supervised_plan_v1(
    mut inputs: PairedSupervisedPlanInputsV1,
) -> Result<PairedSupervisedPlanV1, PairedSupervisedErrorV1> {
    if inputs.base_plan.claim_scope != EvaluationClaimScopeV1::Qualification
        || inputs.tasks.is_empty()
        || inputs.tasks.len() > MAX_PAIRED_TASKS
        || inputs.metrics.is_empty()
        || inputs.metrics.len() > 128
        || inputs.base_plan.simultaneous_comparisons < inputs.metrics.len() as u32
        || !(2..=MAX_PAIRED_TASKS).contains(&inputs.policy.minimum_independent_clusters)
        || inputs.policy.maximum_abstain_ppm > 1_000_000
        || inputs.policy.maximum_execution_window_micros == 0
        || inputs.policy.assumptions_digest.is_zero()
    {
        return Err(PairedSupervisedErrorV1::Binding("paired plan bounds/scope"));
    }
    let pins = &inputs.runtime;
    if [
        pins.candidate_artifact_digest,
        pins.deployed_baseline_digest,
        pins.candidate_runtime_digest,
        pins.baseline_runtime_digest,
        pins.task_input_contract_digest,
    ]
    .into_iter()
    .any(Digest32::is_zero)
    {
        return Err(PairedSupervisedErrorV1::Binding("runtime/input pins"));
    }
    inputs.policy.output_alphabet.sort();
    if !(2..=128).contains(&inputs.policy.output_alphabet.len())
        || inputs
            .policy
            .output_alphabet
            .windows(2)
            .any(|pair| pair[0] == pair[1])
    {
        return Err(PairedSupervisedErrorV1::Binding("output alphabet"));
    }
    inputs
        .metrics
        .sort_by_key(|metric| metric.contract.metric_id.clone());
    let mut contracts = inputs.base_plan.metric_contracts.clone();
    contracts.sort_by_key(|contract| contract.metric_id.clone());
    if contracts
        != inputs
            .metrics
            .iter()
            .map(|metric| metric.contract.clone())
            .collect::<Vec<_>>()
    {
        return Err(PairedSupervisedErrorV1::Binding("metric coverage"));
    }
    for metric in &inputs.metrics {
        match metric.kind {
            PairedMetricKindV1::ClassificationAccuracy => {
                if metric.contract.direction != EvaluationDirectionV1::Maximize {
                    return Err(PairedSupervisedErrorV1::Binding("accuracy direction"));
                }
            }
            PairedMetricKindV1::ExecutionLatencyMillis { maximum } => {
                if maximum <= FixedQ32::ZERO
                    || metric.contract.direction != EvaluationDirectionV1::Minimize
                {
                    return Err(PairedSupervisedErrorV1::Binding(
                        "native latency bounds/direction",
                    ));
                }
            }
            PairedMetricKindV1::ObservedBounded { minimum, maximum } => {
                if minimum >= maximum {
                    return Err(PairedSupervisedErrorV1::Binding("observed metric bounds"));
                }
            }
        }
    }
    let source_membership_digest = crate::paired_supervised_scope::validate_membership(&inputs)?;
    crate::paired_supervised_scope::validate_evidence_metrics(&inputs)?;
    let mut final_folds = inputs.folds.iter().filter(|fold| {
        fold.holdout_windows
            .contains(&inputs.base_plan.final_holdout_window_id)
    });
    let final_records: BTreeSet<_> = final_folds
        .next()
        .ok_or(PairedSupervisedErrorV1::Binding("final fold"))?
        .holdout_records
        .iter()
        .copied()
        .collect();
    if final_folds.next().is_some() {
        return Err(PairedSupervisedErrorV1::Binding("final fold"));
    }
    let mut tasks = BTreeMap::new();
    let mut request_ids = BTreeSet::new();
    for task in inputs.tasks {
        inputs.source.record(task.source_record_digest)?;
        if task.candidate_input_digest.is_zero()
            || task.baseline_input_digest.is_zero()
            || !request_ids.insert(task.candidate_request_id.clone())
            || !request_ids.insert(task.baseline_request_id.clone())
            || tasks.insert(task.source_record_digest, task).is_some()
        {
            return Err(PairedSupervisedErrorV1::Binding("paired task identities"));
        }
    }
    if final_records != tasks.keys().copied().collect() {
        return Err(PairedSupervisedErrorV1::Binding("full final task coverage"));
    }
    let profile_digest = profile_digest(
        &inputs.source,
        &tasks,
        &inputs.runtime,
        &inputs.policy,
        &inputs.metrics,
        source_membership_digest,
    );
    let mut estimand = b"hepta.eval.paired-supervised.estimand.v1".to_vec();
    estimand.extend_from_slice(inputs.base_plan.estimand_digest.as_array());
    estimand.extend_from_slice(profile_digest.as_array());
    inputs.base_plan.estimand_digest = Digest32::of_bytes(&estimand);
    let roles = inputs
        .metrics
        .iter()
        .map(|metric| MetricRoleContractV2 {
            metric_id: metric.contract.metric_id.clone(),
            role: metric.role,
        })
        .collect();
    let bound = inputs
        .source
        .bind_cross_fold_plan(inputs.base_plan, inputs.folds)?;
    let frozen = freeze_cross_fold_plan_v2(bound, roles)?;
    let mut plan = PairedSupervisedPlanV1 {
        frozen,
        source: inputs.source,
        tasks,
        runtime: inputs.runtime,
        policy: inputs.policy,
        metrics: inputs.metrics,
        profile_digest,
        source_membership_digest,
        receipt_seal: Digest32::ZERO,
    };
    plan.receipt_seal = plan.seal();
    Ok(plan)
}

impl PairedSupervisedPlanV1 {
    #[must_use]
    pub fn frozen_plan(&self) -> &CrossFoldPlanReceiptV1 {
        &self.frozen
    }
    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }
    #[must_use]
    pub fn source_graph_digest(&self) -> Digest32 {
        self.source.source_graph_digest()
    }
    pub(crate) fn validate(&self) -> Result<(), PairedSupervisedErrorV1> {
        crate::closure::validate_frozen_plan_receipt_integrity(&self.frozen)?;
        if self.profile_digest
            != profile_digest(
                &self.source,
                &self.tasks,
                &self.runtime,
                &self.policy,
                &self.metrics,
                self.source_membership_digest,
            )
            || self.receipt_seal != self.seal()
        {
            return Err(PairedSupervisedErrorV1::Binding("paired plan integrity"));
        }
        Ok(())
    }
    fn seal(&self) -> Digest32 {
        let mut bytes = b"hepta.eval.paired-supervised.plan-receipt.v1".to_vec();
        bytes.extend_from_slice(self.frozen.plan_digest.as_array());
        bytes.extend_from_slice(self.profile_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

fn profile_digest(
    source: &FrozenTaskSourceLineageV1,
    tasks: &BTreeMap<Digest32, PairedTaskBindingV1>,
    runtime: &PairedRuntimeBindingV1,
    policy: &PairedBenchmarkPolicyV1,
    metrics: &[PairedMetricContractV1],
    source_membership_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.eval.paired-supervised.profile.v1".to_vec();
    for digest in [
        source.source_graph_digest(),
        source.scope_digest(),
        runtime.candidate_artifact_digest,
        runtime.deployed_baseline_digest,
        runtime.candidate_runtime_digest,
        runtime.baseline_runtime_digest,
        runtime.task_input_contract_digest,
        policy.assumptions_digest,
        source_membership_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for metric in [
        &policy.required_evidence_metrics.execution_cost,
        &policy.required_evidence_metrics.retention,
        &policy.required_evidence_metrics.unlearning,
    ] {
        push_id(&mut bytes, metric);
    }
    bytes.extend_from_slice(&(policy.minimum_independent_clusters as u64).to_be_bytes());
    bytes.extend_from_slice(&policy.maximum_abstain_ppm.to_be_bytes());
    bytes.extend_from_slice(&policy.maximum_execution_window_micros.to_be_bytes());
    bytes.extend_from_slice(&(policy.output_alphabet.len() as u64).to_be_bytes());
    for label in &policy.output_alphabet {
        push_id(&mut bytes, label);
    }
    bytes.extend_from_slice(&(tasks.len() as u64).to_be_bytes());
    for task in tasks.values() {
        for digest in [
            task.source_record_digest,
            task.candidate_input_digest,
            task.baseline_input_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &task.candidate_request_id);
        push_id(&mut bytes, &task.baseline_request_id);
    }
    bytes.extend_from_slice(&(metrics.len() as u64).to_be_bytes());
    for metric in metrics {
        push_id(&mut bytes, &metric.contract.metric_id);
        bytes.push(match metric.contract.direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        });
        match metric.contract.safety_floor {
            Some(floor) => {
                bytes.push(1);
                bytes.extend_from_slice(&floor.raw().to_be_bytes());
            }
            None => bytes.push(0),
        }
        match metric.role {
            MetricRoleV2::PrimarySuperiority {
                minimum_improvement,
            } => {
                bytes.push(0);
                bytes.extend_from_slice(&minimum_improvement.raw().to_be_bytes());
            }
            MetricRoleV2::NonInferiority { maximum_regression } => {
                bytes.push(1);
                bytes.extend_from_slice(&maximum_regression.raw().to_be_bytes());
            }
            MetricRoleV2::AbsoluteConstraint => bytes.push(2),
        }
        match metric.kind {
            PairedMetricKindV1::ClassificationAccuracy => bytes.push(0),
            PairedMetricKindV1::ExecutionLatencyMillis { maximum } => {
                bytes.push(2);
                bytes.extend_from_slice(&maximum.raw().to_be_bytes());
            }
            PairedMetricKindV1::ObservedBounded { minimum, maximum } => {
                bytes.push(1);
                bytes.extend_from_slice(&minimum.raw().to_be_bytes());
                bytes.extend_from_slice(&maximum.raw().to_be_bytes());
            }
        }
    }
    // v1 rejects every Censored task; no failed output is scored as zero.
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}
