//! Independent, bounded canonical metadata encoding. No receipt-seal codec.
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::ProductEvaluationError;
use super::ProductEvaluationPolicyContextV2 as Context;
use super::ProductEvaluationPolicyInputV2 as Input;
use crate::ClusterConfidencePlan;
use crate::CrossFoldPartitionV1;
use crate::EvaluationClaimScopeV1;
use crate::EvaluationDirectionV1;
use crate::MetricContractV1;
use crate::MetricRoleContractV2;
use crate::MetricRoleV2;
use crate::OpePlan;
use crate::ProductMetricSourceContractV1;
use crate::ProductMetricSourceV1;
use crate::TemporalEvaluationPlan;
use crate::TemporalFoldPlan;

const PREFIX: &[u8] = b"hepta.intelligence-eval.product-evaluation-policy.v2\0";
const MAX_BYTES: usize = 131_072;
const MAX_METRICS: usize = 128;
const MAX_FOLDS: usize = 32;
const MAX_LINEAGE: usize = 1_000_000;

fn invalid() -> ProductEvaluationError {
    ProductEvaluationError::Binding("policy metadata encoding")
}

struct Writer {
    bytes: Vec<u8>,
}

impl Writer {
    fn push(&mut self, value: &[u8]) -> Result<(), ProductEvaluationError> {
        let length = self.bytes.len().checked_add(value.len()).ok_or_else(invalid)?;
        if length > MAX_BYTES {
            return Err(invalid());
        }
        self.bytes.extend_from_slice(value);
        Ok(())
    }

    fn byte(&mut self, value: u8) -> Result<(), ProductEvaluationError> {
        self.push(&[value])
    }

    fn u32(&mut self, value: u32) -> Result<(), ProductEvaluationError> {
        self.push(&value.to_be_bytes())
    }

    fn u64(&mut self, value: u64) -> Result<(), ProductEvaluationError> {
        self.push(&value.to_be_bytes())
    }

    fn usize(&mut self, value: usize) -> Result<(), ProductEvaluationError> {
        self.u64(u64::try_from(value).map_err(|_| invalid())?)
    }

    fn digest(&mut self, value: Digest32) -> Result<(), ProductEvaluationError> {
        self.push(value.as_array())
    }

    fn fixed(&mut self, value: FixedQ32) -> Result<(), ProductEvaluationError> {
        self.push(&value.raw().to_be_bytes())
    }

    fn id(&mut self, value: &StableId) -> Result<(), ProductEvaluationError> {
        let raw = value.as_str().as_bytes();
        if !(1..=128).contains(&raw.len()) {
            return Err(invalid());
        }
        self.push(&u16::try_from(raw.len()).map_err(|_| invalid())?.to_be_bytes())?;
        self.push(raw)
    }

    fn count(&mut self, value: usize, limit: usize) -> Result<(), ProductEvaluationError> {
        if value > limit {
            return Err(invalid());
        }
        self.u32(u32::try_from(value).map_err(|_| invalid())?)
    }

    fn ids(&mut self, values: &[StableId]) -> Result<(), ProductEvaluationError> {
        self.count(values.len(), MAX_LINEAGE)?;
        for value in values {
            self.id(value)?;
        }
        Ok(())
    }

    fn temporal(&mut self, plan: &TemporalEvaluationPlan) -> Result<(), ProductEvaluationError> {
        self.digest(plan.plan_digest)?;
        self.id(&plan.evaluation_id)?;
        self.digest(plan.objective_digest)?;
        self.digest(plan.fold.plan_digest)?;
        self.id(&plan.fold.fold_id)?;
        self.u64(plan.fold.training_watermark)?;
        self.u64(plan.fold.evaluation_start)?;
        self.usize(plan.fold.minimum_per_action)?;
        self.digest(plan.ope.plan_digest)?;
        self.u64(plan.ope.outcome_watermark)?;
        self.usize(plan.ope.minimum_rows)?;
        self.fixed(plan.ope.minimum_ess)?;
        self.fixed(plan.ope.maximum_weight)?;
        self.digest(plan.confidence.plan_digest)?;
        self.digest(plan.confidence.assumptions_digest)?;
        self.u32(plan.confidence.family_alpha_ppm)?;
        self.u32(plan.confidence.simultaneous_comparisons)?;
        self.usize(plan.confidence.minimum_clusters)
    }
}

pub(super) fn encode(context: &Context, input: &Input) -> Result<Vec<u8>, ProductEvaluationError> {
    let mut out = Writer { bytes: Vec::new() };
    out.push(PREFIX)?;
    out.id(&context.plan_id)?;
    out.digest(context.objective_digest)?;
    out.u32(context.family_alpha_ppm)?;
    out.u32(context.simultaneous_comparisons)?;
    out.id(&context.final_holdout_window_id)?;
    out.temporal(&context.candidate_temporal)?;
    out.temporal(&context.baseline_temporal)?;
    out.byte(match input.claim_scope {
        EvaluationClaimScopeV1::Qualification => 0,
        EvaluationClaimScopeV1::SystemLongitudinal => 1,
    })?;
    out.digest(input.base_estimand_digest)?;
    out.id(&input.baseline_id)?;
    out.count(input.metric_contracts.len(), MAX_METRICS)?;
    for metric in &input.metric_contracts {
        out.id(&metric.metric_id)?;
        out.byte(match metric.direction {
            EvaluationDirectionV1::Maximize => 0,
            EvaluationDirectionV1::Minimize => 1,
        })?;
        match metric.safety_floor {
            None => out.byte(0)?,
            Some(value) => {
                out.byte(1)?;
                out.fixed(value)?;
            }
        }
    }
    out.count(input.metric_roles.len(), MAX_METRICS)?;
    for role in &input.metric_roles {
        out.id(&role.metric_id)?;
        match role.role {
            MetricRoleV2::PrimarySuperiority { minimum_improvement } => {
                out.byte(0)?;
                out.fixed(minimum_improvement)?;
            }
            MetricRoleV2::NonInferiority { maximum_regression } => {
                out.byte(1)?;
                out.fixed(maximum_regression)?;
            }
            MetricRoleV2::AbsoluteConstraint => out.byte(2)?,
        }
    }
    out.count(input.metric_sources.len(), MAX_METRICS)?;
    for source in &input.metric_sources {
        out.id(&source.metric_id)?;
        out.byte(match source.source {
            ProductMetricSourceV1::Ips => 0,
            ProductMetricSourceV1::Snips => 1,
            ProductMetricSourceV1::DoublyRobust => 2,
        })?;
    }
    out.count(input.folds.len(), MAX_FOLDS)?;
    for fold in &input.folds {
        out.id(&fold.fold_id)?;
        for values in [
            &fold.training_principals, &fold.training_episodes, &fold.training_windows,
            &fold.holdout_principals, &fold.holdout_episodes, &fold.holdout_windows,
        ] {
            out.ids(values)?;
        }
        out.digest(fold.model_digest)?;
        out.digest(fold.predictions_digest)?;
    }
    Ok(out.bytes)
}

struct Reader<'a> {
    bytes: &'a [u8],
}

impl<'a> Reader<'a> {
    fn take(&mut self, size: usize) -> Result<&'a [u8], ProductEvaluationError> {
        let (value, rest) = self.bytes.split_at_checked(size).ok_or_else(invalid)?;
        self.bytes = rest;
        Ok(value)
    }

    fn byte(&mut self) -> Result<u8, ProductEvaluationError> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32, ProductEvaluationError> {
        Ok(u32::from_be_bytes(self.take(4)?.try_into().map_err(|_| invalid())?))
    }

    fn u64(&mut self) -> Result<u64, ProductEvaluationError> {
        Ok(u64::from_be_bytes(self.take(8)?.try_into().map_err(|_| invalid())?))
    }

    fn usize(&mut self) -> Result<usize, ProductEvaluationError> {
        usize::try_from(self.u64()?).map_err(|_| invalid())
    }

    fn digest(&mut self) -> Result<Digest32, ProductEvaluationError> {
        Ok(Digest32::from_array(self.take(32)?.try_into().map_err(|_| invalid())?))
    }

    fn fixed(&mut self) -> Result<FixedQ32, ProductEvaluationError> {
        Ok(FixedQ32::from_raw(i64::from_be_bytes(
            self.take(8)?.try_into().map_err(|_| invalid())?,
        )))
    }

    fn id(&mut self) -> Result<StableId, ProductEvaluationError> {
        let length = usize::from(u16::from_be_bytes(
            self.take(2)?.try_into().map_err(|_| invalid())?,
        ));
        if !(1..=128).contains(&length) {
            return Err(invalid());
        }
        let value = std::str::from_utf8(self.take(length)?).map_err(|_| invalid())?;
        StableId::new(value).map_err(|_| invalid())
    }

    fn count(&mut self, limit: usize, minimum_bytes: usize) -> Result<usize, ProductEvaluationError> {
        let count = usize::try_from(self.u32()?).map_err(|_| invalid())?;
        let lower = count.checked_mul(minimum_bytes).ok_or_else(invalid)?;
        if count > limit || lower > self.bytes.len() {
            return Err(invalid());
        }
        Ok(count)
    }

    fn ids(&mut self) -> Result<Vec<StableId>, ProductEvaluationError> {
        let count = self.count(MAX_LINEAGE, 3)?;
        let mut values = Vec::with_capacity(count);
        for _ in 0..count {
            values.push(self.id()?);
        }
        Ok(values)
    }

    fn temporal(&mut self) -> Result<TemporalEvaluationPlan, ProductEvaluationError> {
        Ok(TemporalEvaluationPlan {
            plan_digest: self.digest()?,
            evaluation_id: self.id()?,
            objective_digest: self.digest()?,
            fold: TemporalFoldPlan {
                plan_digest: self.digest()?,
                fold_id: self.id()?,
                training_watermark: self.u64()?,
                evaluation_start: self.u64()?,
                minimum_per_action: self.usize()?,
            },
            ope: OpePlan {
                plan_digest: self.digest()?,
                outcome_watermark: self.u64()?,
                minimum_rows: self.usize()?,
                minimum_ess: self.fixed()?,
                maximum_weight: self.fixed()?,
            },
            confidence: ClusterConfidencePlan {
                plan_digest: self.digest()?,
                assumptions_digest: self.digest()?,
                family_alpha_ppm: self.u32()?,
                simultaneous_comparisons: self.u32()?,
                minimum_clusters: self.usize()?,
            },
        })
    }
}

pub(super) fn decode(bytes: &[u8]) -> Result<(Context, Input), ProductEvaluationError> {
    if bytes.len() > MAX_BYTES {
        return Err(invalid());
    }
    let mut source = Reader { bytes };
    if source.take(PREFIX.len())? != PREFIX {
        return Err(invalid());
    }
    let context = Context {
        plan_id: source.id()?,
        objective_digest: source.digest()?,
        family_alpha_ppm: source.u32()?,
        simultaneous_comparisons: source.u32()?,
        final_holdout_window_id: source.id()?,
        candidate_temporal: source.temporal()?,
        baseline_temporal: source.temporal()?,
    };
    let claim_scope = match source.byte()? {
        0 => EvaluationClaimScopeV1::Qualification,
        1 => EvaluationClaimScopeV1::SystemLongitudinal,
        _ => return Err(invalid()),
    };
    let base_estimand_digest = source.digest()?;
    let baseline_id = source.id()?;
    let count = source.count(MAX_METRICS, 5)?;
    let mut metric_contracts = Vec::with_capacity(count);
    for _ in 0..count {
        let metric_id = source.id()?;
        let direction = match source.byte()? {
            0 => EvaluationDirectionV1::Maximize,
            1 => EvaluationDirectionV1::Minimize,
            _ => return Err(invalid()),
        };
        let safety_floor = match source.byte()? {
            0 => None,
            1 => Some(source.fixed()?),
            _ => return Err(invalid()),
        };
        metric_contracts.push(MetricContractV1 { metric_id, direction, safety_floor });
    }
    let count = source.count(MAX_METRICS, 4)?;
    let mut metric_roles = Vec::with_capacity(count);
    for _ in 0..count {
        let metric_id = source.id()?;
        let role = match source.byte()? {
            0 => MetricRoleV2::PrimarySuperiority { minimum_improvement: source.fixed()? },
            1 => MetricRoleV2::NonInferiority { maximum_regression: source.fixed()? },
            2 => MetricRoleV2::AbsoluteConstraint,
            _ => return Err(invalid()),
        };
        metric_roles.push(MetricRoleContractV2 { metric_id, role });
    }
    let count = source.count(MAX_METRICS, 4)?;
    let mut metric_sources = Vec::with_capacity(count);
    for _ in 0..count {
        let metric_id = source.id()?;
        let value = match source.byte()? {
            0 => ProductMetricSourceV1::Ips,
            1 => ProductMetricSourceV1::Snips,
            2 => ProductMetricSourceV1::DoublyRobust,
            _ => return Err(invalid()),
        };
        metric_sources.push(ProductMetricSourceContractV1 { metric_id, source: value });
    }
    let count = source.count(MAX_FOLDS, 91)?;
    let mut folds = Vec::with_capacity(count);
    for _ in 0..count {
        folds.push(CrossFoldPartitionV1 {
            fold_id: source.id()?,
            training_principals: source.ids()?,
            training_episodes: source.ids()?,
            training_windows: source.ids()?,
            holdout_principals: source.ids()?,
            holdout_episodes: source.ids()?,
            holdout_windows: source.ids()?,
            model_digest: source.digest()?,
            predictions_digest: source.digest()?,
        });
    }
    if !source.bytes.is_empty() {
        return Err(invalid());
    }
    Ok((context, Input {
        claim_scope, base_estimand_digest, baseline_id,
        metric_contracts, metric_roles, metric_sources, folds,
    }))
}
