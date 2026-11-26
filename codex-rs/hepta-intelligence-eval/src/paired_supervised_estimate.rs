//! Full-information, fixed-horizon cluster bounds over original paired tasks.
//! An independent Observer authenticates the exact cut. Correctness statements
//! come from its private gold custody; this module has no gold or signing key.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::MetricGateV1;
use crate::PairedMetricKindV1;
use crate::PairedRuntimeBindingV1;
use crate::PairedSupervisedErrorV1;
use crate::PairedSupervisedPlanV1;
use crate::push_id;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PairedClassObservationV1 {
    Label {
        class_id: StableId,
        correct: bool,
    },
    Abstain,
    /// Original missing/failed execution, never a fabricated negative label.
    Censored {
        reason: StableId,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedNativeObservationV1 {
    pub request_id: StableId,
    pub input_digest: Digest32,
    pub original_native_observation_digest: Digest32,
    pub started_at_unix_micros: u64,
    pub finished_at_unix_micros: u64,
    /// Measured original monotonic duration. None is unknown, never zero;
    /// cached observations retain the original measurement and event identity.
    pub original_elapsed_micros: Option<u64>,
    pub outcome: PairedClassObservationV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedObservedMetricV1 {
    pub metric_id: StableId,
    pub candidate: Option<FixedQ32>,
    pub baseline: Option<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedTaskObservationV1 {
    pub source_record_digest: Digest32,
    pub candidate: PairedNativeObservationV1,
    pub baseline: PairedNativeObservationV1,
    pub observed_metrics: Vec<PairedObservedMetricV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedObservationCutV1 {
    pub plan_digest: Digest32,
    pub source_graph_digest: Digest32,
    pub runtime: PairedRuntimeBindingV1,
    pub started_at_unix_micros: u64,
    pub finished_at_unix_micros: u64,
    pub rows: Vec<PairedTaskObservationV1>,
    pub retention_receipt_digests: Vec<Digest32>,
    pub unlearning_receipt_digest: Digest32,
}

/// Canonical Observer payload. Original order is bound; estimation sorts rows
/// only after authentication. There is no arbitrary signing endpoint here.
pub fn paired_observation_cut_signing_payload_v1(
    cut: &PairedObservationCutV1,
) -> Result<Vec<u8>, PairedSupervisedErrorV1> {
    if cut.rows.is_empty()
        || cut.rows.len() > crate::paired_supervised_plan::MAX_PAIRED_TASKS
        || cut.retention_receipt_digests.len() > 128
        || cut.rows.iter().any(|row| row.observed_metrics.len() > 128)
    {
        return Err(PairedSupervisedErrorV1::Binding("paired cut row limit"));
    }
    let mut bytes = b"hepta.eval.paired-supervised.observer-cut.v1".to_vec();
    for digest in [
        cut.plan_digest,
        cut.source_graph_digest,
        cut.runtime.candidate_artifact_digest,
        cut.runtime.deployed_baseline_digest,
        cut.runtime.candidate_runtime_digest,
        cut.runtime.baseline_runtime_digest,
        cut.runtime.task_input_contract_digest,
        cut.unlearning_receipt_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&cut.started_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&cut.finished_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&(cut.retention_receipt_digests.len() as u64).to_be_bytes());
    for digest in &cut.retention_receipt_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(cut.rows.len() as u64).to_be_bytes());
    for row in &cut.rows {
        bytes.extend_from_slice(row.source_record_digest.as_array());
        for observation in [&row.candidate, &row.baseline] {
            push_id(&mut bytes, &observation.request_id);
            for digest in [
                observation.input_digest,
                observation.original_native_observation_digest,
            ] {
                bytes.extend_from_slice(digest.as_array());
            }
            bytes.extend_from_slice(&observation.started_at_unix_micros.to_be_bytes());
            bytes.extend_from_slice(&observation.finished_at_unix_micros.to_be_bytes());
            match observation.original_elapsed_micros {
                Some(elapsed) => {
                    bytes.push(1);
                    bytes.extend_from_slice(&elapsed.to_be_bytes());
                }
                None => bytes.push(0),
            }
            match &observation.outcome {
                PairedClassObservationV1::Label { class_id, correct } => {
                    bytes.push(0);
                    push_id(&mut bytes, class_id);
                    bytes.push(u8::from(*correct));
                }
                PairedClassObservationV1::Abstain => bytes.push(1),
                PairedClassObservationV1::Censored { reason } => {
                    bytes.push(2);
                    push_id(&mut bytes, reason);
                }
            }
        }
        bytes.extend_from_slice(&(row.observed_metrics.len() as u64).to_be_bytes());
        for metric in &row.observed_metrics {
            push_id(&mut bytes, &metric.metric_id);
            for value in [metric.candidate, metric.baseline] {
                match value {
                    Some(value) => {
                        bytes.push(1);
                        bytes.extend_from_slice(&value.raw().to_be_bytes());
                    }
                    None => bytes.push(0),
                }
            }
        }
        if bytes.len() > 32 * 1024 * 1024 {
            return Err(PairedSupervisedErrorV1::Binding("paired cut byte limit"));
        }
    }
    Ok(bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedSupervisedEstimateV1 {
    pub(crate) metrics: Vec<MetricGateV1>,
    pub(crate) original_cut: PairedObservationCutV1,
    pub(crate) cluster_count: usize,
    pub(crate) largest_cluster_tasks: usize,
    pub(crate) candidate_abstentions: usize,
    pub(crate) baseline_abstentions: usize,
    pub(crate) evidence_digest: Digest32,
    receipt_seal: Digest32,
}

impl PairedSupervisedEstimateV1 {
    #[must_use]
    pub fn metrics(&self) -> &[MetricGateV1] {
        &self.metrics
    }
    #[must_use]
    pub fn cluster_count(&self) -> usize {
        self.cluster_count
    }
    #[must_use]
    pub fn original_cut_digest(&self) -> Digest32 {
        self.evidence_digest
    }
    pub(crate) fn validate(
        &self,
        plan: &PairedSupervisedPlanV1,
    ) -> Result<(), PairedSupervisedErrorV1> {
        if &estimate_paired_cut(plan, &self.original_cut)? != self {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired estimate integrity",
            ));
        }
        Ok(())
    }
}

pub(crate) fn estimate_paired_cut(
    plan: &PairedSupervisedPlanV1,
    cut: &PairedObservationCutV1,
) -> Result<PairedSupervisedEstimateV1, PairedSupervisedErrorV1> {
    plan.validate()?;
    if cut.plan_digest != plan.frozen.plan_digest
        || cut.source_graph_digest != plan.source_graph_digest()
        || cut.runtime != plan.runtime
        || cut.rows.len() != plan.tasks.len()
        || cut.started_at_unix_micros == 0
        || cut.finished_at_unix_micros < cut.started_at_unix_micros
        || cut.finished_at_unix_micros - cut.started_at_unix_micros
            > plan.policy.maximum_execution_window_micros
    {
        return Err(PairedSupervisedErrorV1::Binding("paired common cut"));
    }
    let expected_metrics: BTreeSet<_> = plan
        .metrics
        .iter()
        .filter_map(|metric| match metric.kind {
            PairedMetricKindV1::ClassificationAccuracy
            | PairedMetricKindV1::ExecutionLatencyMillis { .. } => None,
            PairedMetricKindV1::ObservedBounded { .. } => Some(&metric.contract.metric_id),
        })
        .collect();
    let mut row_ids = BTreeSet::new();
    let mut sizes = BTreeMap::new();
    let mut candidate_abstentions = 0_usize;
    let mut baseline_abstentions = 0_usize;
    let mut censored = 0_usize;
    for row in &cut.rows {
        let task = plan
            .tasks
            .get(&row.source_record_digest)
            .ok_or(PairedSupervisedErrorV1::Binding("unknown source task"))?;
        if !row_ids.insert(row.source_record_digest) {
            return Err(PairedSupervisedErrorV1::Binding("duplicate source task"));
        }
        for (observation, request, input) in [
            (
                &row.candidate,
                &task.candidate_request_id,
                task.candidate_input_digest,
            ),
            (
                &row.baseline,
                &task.baseline_request_id,
                task.baseline_input_digest,
            ),
        ] {
            if &observation.request_id != request
                || observation.input_digest != input
                || observation.original_native_observation_digest.is_zero()
                || observation.started_at_unix_micros < cut.started_at_unix_micros
                || observation.finished_at_unix_micros < observation.started_at_unix_micros
                || observation.finished_at_unix_micros > cut.finished_at_unix_micros
            {
                return Err(PairedSupervisedErrorV1::Binding(
                    "original native observation",
                ));
            }
            if let PairedClassObservationV1::Label { class_id, .. } = &observation.outcome
                && !plan.policy.output_alphabet.contains(class_id)
            {
                return Err(PairedSupervisedErrorV1::Binding(
                    "unregistered output class",
                ));
            }
        }
        if let (
            PairedClassObservationV1::Label {
                class_id: candidate,
                correct: candidate_correct,
            },
            PairedClassObservationV1::Label {
                class_id: baseline,
                correct: baseline_correct,
            },
        ) = (&row.candidate.outcome, &row.baseline.outcome)
            && ((candidate == baseline && candidate_correct != baseline_correct)
                || (candidate != baseline && *candidate_correct && *baseline_correct))
        {
            return Err(PairedSupervisedErrorV1::Binding(
                "paired single gold consistency",
            ));
        }
        let metric_ids: BTreeSet<_> = row
            .observed_metrics
            .iter()
            .map(|metric| &metric.metric_id)
            .collect();
        if metric_ids != expected_metrics || metric_ids.len() != row.observed_metrics.len() {
            return Err(PairedSupervisedErrorV1::Binding("observed metric coverage"));
        }
        let incomplete = row.candidate.original_elapsed_micros.is_none()
            || row.baseline.original_elapsed_micros.is_none()
            || matches!(
                row.candidate.outcome,
                PairedClassObservationV1::Censored { .. }
            )
            || matches!(
                row.baseline.outcome,
                PairedClassObservationV1::Censored { .. }
            )
            || row
                .observed_metrics
                .iter()
                .any(|metric| metric.candidate.is_none() || metric.baseline.is_none());
        censored += usize::from(incomplete);
        candidate_abstentions += usize::from(matches!(
            row.candidate.outcome,
            PairedClassObservationV1::Abstain
        ));
        baseline_abstentions += usize::from(matches!(
            row.baseline.outcome,
            PairedClassObservationV1::Abstain
        ));
        let cluster = &plan.source.record(row.source_record_digest)?.cluster;
        *sizes.entry(cluster).or_insert(0_usize) += 1;
    }
    if censored != 0 {
        return Err(PairedSupervisedErrorV1::Incomplete {
            tasks: cut.rows.len(),
            censored,
        });
    }
    if sizes.len() < plan.policy.minimum_independent_clusters {
        return Err(PairedSupervisedErrorV1::InsufficientClusters);
    }
    if [candidate_abstentions, baseline_abstentions]
        .into_iter()
        .any(|count| {
            count as u128 * 1_000_000
                > u128::from(plan.policy.maximum_abstain_ppm) * cut.rows.len() as u128
        })
    {
        return Err(PairedSupervisedErrorV1::Binding(
            "registered abstention coverage",
        ));
    }
    let cut_digest = Digest32::of_bytes(&paired_observation_cut_signing_payload_v1(cut)?);
    let count = cut.rows.len() as u128;
    let sum_squares: u128 = sizes
        .values()
        .map(|size| *size as u128 * *size as u128)
        .sum();
    let ratio = (4_000_000_u128 * u128::from(plan.frozen.simultaneous_comparisons))
        .div_ceil(u128::from(plan.frozen.family_alpha_ppm));
    let log_upper = u128::from((ratio - 1).ilog2() + 1);
    let mut metrics = Vec::new();
    for metric in &plan.metrics {
        let (minimum, maximum) = match metric.kind {
            PairedMetricKindV1::ClassificationAccuracy => (FixedQ32::ZERO, FixedQ32::ONE),
            PairedMetricKindV1::ExecutionLatencyMillis { maximum } => (FixedQ32::ZERO, maximum),
            PairedMetricKindV1::ObservedBounded { minimum, maximum } => (minimum, maximum),
        };
        let mut sums = [0_i128; 2];
        for row in &cut.rows {
            let values = crate::paired_supervised_values::metric_values(metric, row)?;
            for (sum, value) in sums.iter_mut().zip(values) {
                if value < minimum || value > maximum {
                    return Err(PairedSupervisedErrorV1::Binding(
                        "observed value outside frozen bounds",
                    ));
                }
                *sum = sum
                    .checked_add(i128::from(value.raw()))
                    .ok_or(PairedSupervisedErrorV1::Arithmetic)?;
            }
        }
        let range = u128::try_from(i128::from(maximum.raw()) - i128::from(minimum.raw()))
            .map_err(|_| PairedSupervisedErrorV1::Arithmetic)?;
        let radius = crate::ope::conservative_bounded_radius(range, log_upper, sum_squares, count)
            .map_err(|_| PairedSupervisedErrorV1::Arithmetic)?;
        let intervals = sums
            .map(|sum| {
                crate::paired_supervised_values::bounded_mean(
                    sum,
                    count as i128,
                    radius,
                    minimum,
                    maximum,
                )
            })
            .into_iter()
            .collect::<Result<Vec<_>, _>>()?;
        let mut support = b"hepta.eval.paired-supervised.metric-support.v1".to_vec();
        support.extend_from_slice(plan.profile_digest.as_array());
        support.extend_from_slice(cut_digest.as_array());
        push_id(&mut support, &metric.contract.metric_id);
        metrics.push(MetricGateV1 {
            metric_id: metric.contract.metric_id.clone(),
            direction: metric.contract.direction,
            candidate: intervals[0],
            baseline: intervals[1],
            safety_floor: metric.contract.safety_floor,
            support_digest: Digest32::of_bytes(&support),
        });
    }
    let mut receipt = PairedSupervisedEstimateV1 {
        metrics,
        original_cut: cut.clone(),
        cluster_count: sizes.len(),
        largest_cluster_tasks: sizes.values().copied().max().unwrap_or(0),
        candidate_abstentions,
        baseline_abstentions,
        evidence_digest: cut_digest,
        receipt_seal: Digest32::ZERO,
    };
    let mut seal = b"hepta.eval.paired-supervised.cluster-estimate.v1".to_vec();
    seal.extend_from_slice(plan.frozen.plan_digest.as_array());
    seal.extend_from_slice(cut_digest.as_array());
    for metric in &receipt.metrics {
        push_id(&mut seal, &metric.metric_id);
        for interval in [metric.candidate, metric.baseline] {
            seal.extend_from_slice(&interval.lower.raw().to_be_bytes());
            seal.extend_from_slice(&interval.upper.raw().to_be_bytes());
        }
    }
    receipt.receipt_seal = Digest32::of_bytes(&seal);
    Ok(receipt)
}
