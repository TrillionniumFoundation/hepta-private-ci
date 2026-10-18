//! Scalar derivation from authenticated original native observations.
use crate::EvaluationIntervalV1;
use crate::PairedClassObservationV1;
use crate::PairedMetricContractV1;
use crate::PairedMetricKindV1;
use crate::PairedSupervisedErrorV1;
use crate::PairedTaskObservationV1;
use codex_hepta_types::FixedQ32;

pub(crate) fn metric_values(
    metric: &PairedMetricContractV1,
    row: &PairedTaskObservationV1,
) -> Result<[FixedQ32; 2], PairedSupervisedErrorV1> {
    match metric.kind {
        PairedMetricKindV1::ClassificationAccuracy => Ok([
            correctness(&row.candidate.outcome)?,
            correctness(&row.baseline.outcome)?,
        ]),
        PairedMetricKindV1::ExecutionLatencyMillis { .. } => {
            let duration = |value: Option<u64>| -> Result<FixedQ32, PairedSupervisedErrorV1> {
                let micros = value.ok_or(PairedSupervisedErrorV1::Binding(
                    "unknown original monotonic cost",
                ))?;
                // Integer Q32 milliseconds. At most one Q32 unit is discarded;
                // the existing outward confidence radius reserves eight units.
                let raw = u128::from(micros) * (1_u128 << 32) / 1_000;
                Ok(FixedQ32::from_raw(
                    i64::try_from(raw).map_err(|_| PairedSupervisedErrorV1::Arithmetic)?,
                ))
            };
            Ok([
                duration(row.candidate.original_elapsed_micros)?,
                duration(row.baseline.original_elapsed_micros)?,
            ])
        }
        PairedMetricKindV1::ObservedBounded { .. } => {
            let observed = row
                .observed_metrics
                .iter()
                .find(|value| value.metric_id == metric.contract.metric_id)
                .ok_or(PairedSupervisedErrorV1::Binding("missing observed metric"))?;
            Ok([
                observed
                    .candidate
                    .ok_or(PairedSupervisedErrorV1::Binding("missing candidate metric"))?,
                observed
                    .baseline
                    .ok_or(PairedSupervisedErrorV1::Binding("missing baseline metric"))?,
            ])
        }
    }
}

fn correctness(outcome: &PairedClassObservationV1) -> Result<FixedQ32, PairedSupervisedErrorV1> {
    match outcome {
        PairedClassObservationV1::Label { correct, .. } => Ok(if *correct {
            FixedQ32::ONE
        } else {
            FixedQ32::ZERO
        }),
        PairedClassObservationV1::Abstain => Ok(FixedQ32::ZERO),
        PairedClassObservationV1::Censored { .. } => Err(PairedSupervisedErrorV1::Binding(
            "censored correctness has no scalar",
        )),
    }
}

pub(crate) fn bounded_mean(
    sum: i128,
    count: i128,
    radius: i128,
    minimum: FixedQ32,
    maximum: FixedQ32,
) -> Result<EvaluationIntervalV1, PairedSupervisedErrorV1> {
    let floor = sum.div_euclid(count);
    let ceiling = floor + i128::from(sum.rem_euclid(count) != 0);
    let lower = (floor - radius).max(i128::from(minimum.raw()));
    let upper = (ceiling + radius).min(i128::from(maximum.raw()));
    Ok(EvaluationIntervalV1 {
        lower: FixedQ32::from_raw(
            i64::try_from(lower).map_err(|_| PairedSupervisedErrorV1::Arithmetic)?,
        ),
        upper: FixedQ32::from_raw(
            i64::try_from(upper).map_err(|_| PairedSupervisedErrorV1::Arithmetic)?,
        ),
    })
}
