//! The unchanged bounded optimizer, supplied by either the original source
//! reader or the same Prepared operation. Every path validates before compute
//! and after the actual candidate or NoUpdate result, without cached admission.

use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use super::*;

impl CellQ24SingleHeadTrainingPlanV1 {
    pub(crate) fn fit_with_original_source(
        &self,
        batch: CellQ24TrainingBatchV1,
        rule: CellQ24SgdRuleV1,
        cancellation: &AtomicBool,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<CellQ24TrainingOutcomeV1, CellQ24TrainingErrorV1> {
        use CellQ24TrainingErrorV1::Binding;
        let started = Instant::now();
        let optimizer = self.validate_fit_input_with_source(&batch, rule, source)?;
        let plan = self;
        let budget = &plan.prefix.request.budget;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Binding("system clock"))?;
        let remaining = Duration::from_secs(plan.prefix.request.envelope.expiry_unix_seconds)
            .checked_sub(now)
            .ok_or(CellQ24TrainingErrorV1::DeadlineExceeded)?;
        let limit = remaining.min(Duration::from_millis(budget.maximum_training_milliseconds));
        let check = || {
            if cancellation.load(Ordering::Acquire) {
                Err(CellQ24TrainingErrorV1::Cancelled)
            } else if started.elapsed() >= limit {
                Err(CellQ24TrainingErrorV1::DeadlineExceeded)
            } else {
                Ok(())
            }
        };
        check()?;
        let mut features = Vec::with_capacity(batch.samples.len());
        for sample in &batch.samples {
            check()?;
            features.push((plan.baseline.hidden(&sample.input), sample.target));
        }
        let row = match plan.head {
            CellQ24PrivateHeadV1::Drive { index } => usize::from(index),
            CellQ24PrivateHeadV1::Prediction { index } => {
                plan.baseline.output_width() + usize::from(index)
            }
        };
        let start = row * plan.baseline.heads.cols;
        let end = start + plan.baseline.heads.cols;
        let mut heads = plan.baseline.heads.clone();
        let before = squared_error(&heads.values[start..end], &features);
        let mut steps = 0;
        for _ in 0..rule.epochs {
            for (hidden, target) in &features {
                check()?;
                let weights = &mut heads.values[start..end];
                let error = i128::from(codec::row_output(weights, hidden)) - i128::from(*target);
                for (weight, value) in weights.iter_mut().zip(hidden) {
                    // |eta*error*hidden| <= 128*Q^3 < 2^80; i128 is sufficient.
                    let delta = i128::from(rule.learning_rate_q24) * error * i128::from(*value)
                        / (i128::from(codec::Q) * i128::from(codec::Q));
                    *weight = (i128::from(*weight) - delta)
                        .clamp(-i128::from(LIMIT), i128::from(LIMIT))
                        as i64;
                }
                steps += 1;
            }
        }
        check()?;
        let after = squared_error(&heads.values[start..end], &features);
        let update_rule = cell_q24_single_head_update_rule_v1(
            &plan.prefix.request.selected_bundle,
            plan.head,
            optimizer,
        )?;
        let metrics = CellQ24TrainingMetricsV1 {
            batch_digest: batch.digest,
            optimizer_rule: optimizer,
            update_rule,
            optimizer_steps: steps,
            squared_error_before_q48: before,
            squared_error_after_q48: after,
            elapsed_microseconds: u64::try_from(started.elapsed().as_micros())
                .map_err(|_| Binding("elapsed cost overflow"))?,
        };
        let source_bundle = plan
            .prefix
            .request
            .selected_bundle
            .digest()
            .map_err(|_| Binding("baseline bundle"))?;
        if heads == plan.baseline.heads {
            OriginalQ24DatasetReadV1::require_current_batch(source, &batch)?;
            check()?;
            return Ok(CellQ24TrainingOutcomeV1::NoUpdate {
                retained_bundle: source_bundle,
                metrics,
            });
        }
        let mut candidate = plan.rebuild_candidate(heads.encode(), metrics)?;
        candidate.metrics.elapsed_microseconds = u64::try_from(started.elapsed().as_micros())
            .map_err(|_| Binding("elapsed cost overflow"))?;
        OriginalQ24DatasetReadV1::require_current_batch(source, &batch)?;
        check()?;
        Ok(CellQ24TrainingOutcomeV1::Candidate(Box::new(candidate)))
    }
}

fn squared_error(weights: &[i64], features: &[(Vec<i64>, i64)]) -> u128 {
    features
        .iter()
        .map(|(input, target)| {
            let error = i128::from(codec::row_output(weights, input)) - i128::from(*target);
            (error * error) as u128
        })
        .sum()
}
