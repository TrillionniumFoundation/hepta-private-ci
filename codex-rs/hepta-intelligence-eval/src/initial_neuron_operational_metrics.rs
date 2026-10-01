//! Fixed operational measurements; they grant no candidate superiority or use authority.
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::VerifiedCut;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Gates {
    pub zero_confidence_error_q24: u64,
    pub maximum_in_domain_error_q24: u64,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_accuracy_ppm: u32,
    pub maximum_ece_ppm: u32,
    pub maximum_false_acceptance_ppm: u32,
    pub maximum_p99_latency_micros: u64,
    pub maximum_resident_bytes: u64,
    pub maximum_transient_allocation_bytes: u64,
}
impl Gates {
    pub fn validate(&self) -> HostResult<()> {
        if self.zero_confidence_error_q24 == 0
            || self.maximum_in_domain_error_q24 == 0
            || self.zero_confidence_error_q24 > 1 << 40
            || self.maximum_in_domain_error_q24 > 1 << 40
            || [
                self.minimum_confidence_ppm,
                self.maximum_ood_ppm,
                self.minimum_accuracy_ppm,
                self.maximum_ece_ppm,
                self.maximum_false_acceptance_ppm,
            ]
            .iter()
            .any(|v| *v > 1_000_000)
            || self.maximum_p99_latency_micros == 0
            || self.maximum_p99_latency_micros > 1_000_000
            || self.maximum_resident_bytes == 0
            || self.maximum_resident_bytes > 1 << 30
            || self.maximum_transient_allocation_bytes == 0
            || self.maximum_transient_allocation_bytes > 1 << 28
        {
            return Err("bounded frozen initial operational gates".into());
        }
        Ok(())
    }
}
#[derive(Debug, Serialize)]
pub(super) struct Metrics {
    pub observations: u64,
    pub correct: u64,
    pub accuracy_ppm: u32,
    pub measured_ece_ppm: u32,
    pub measured_false_acceptance_ppm: u32,
    pub abstained: u64,
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub maximum_resident_bytes: u64,
    pub maximum_transient_allocation_bytes: u64,
    pub original_native_executions: u64,
    pub operational_constraints_passed: bool,
}
fn confidence(value: &Value, gates: &Gates) -> HostResult<(u32, bool)> {
    let drive = value["drive_q24"].as_array().ok_or("native drive vector")?;
    let prediction = value["prediction_q24"]
        .as_array()
        .ok_or("native prediction vector")?;
    if drive.len() != 10 || prediction.len() != 10 {
        return Err("exact initial baseline output width".into());
    }
    let mut error = 0;
    for (drive, prediction) in drive.iter().zip(prediction) {
        let delta = i128::from(drive.as_i64().ok_or("native integer drive")?)
            - i128::from(prediction.as_i64().ok_or("native integer prediction")?);
        error = error.max(u64::try_from(delta.unsigned_abs())?);
    }
    let ppm = 1_000_000_u64;
    let confidence =
        ppm.saturating_sub(error.saturating_mul(ppm) / gates.zero_confidence_error_q24);
    let ood = (error.saturating_mul(ppm) / gates.maximum_in_domain_error_q24).min(ppm);
    Ok((
        u32::try_from(confidence)?,
        confidence < u64::from(gates.minimum_confidence_ppm)
            || ood > u64::from(gates.maximum_ood_ppm),
    ))
}
pub(super) fn measure(cut: &VerifiedCut, gates: &Gates) -> HostResult<Metrics> {
    gates.validate()?;
    let mut bins = [(0_u64, 0_u64, 0_u64); 10];
    let mut correct = 0;
    let mut abstained = 0;
    let mut false_acceptance = 0;
    for (value, is_correct) in &cut.source_rows {
        let (confidence, abstain) = confidence(value, gates)?;
        let bin = usize::try_from((confidence / 100_000).min(9))?;
        bins[bin].0 += 1;
        bins[bin].1 += u64::from(confidence);
        bins[bin].2 += u64::from(*is_correct) * 1_000_000;
        correct += u64::from(*is_correct);
        abstained += u64::from(abstain);
        false_acceptance += u64::from(!abstain && !is_correct);
    }
    let count = u64::try_from(cut.source_rows.len())?;
    if count == 0 || cut.original_resources.len() != cut.source_rows.len() * 2 {
        return Err("complete original no-change measurements required".into());
    }
    let accuracy = u32::try_from(correct * 1_000_000 / count)?;
    let ece = u32::try_from(
        bins.iter()
            .map(|(_, confidence, correct)| confidence.abs_diff(*correct))
            .sum::<u64>()
            / count,
    )?;
    let false_acceptance = u32::try_from(false_acceptance * 1_000_000 / count)?;
    let mut latency = Vec::new();
    let mut resident = 0;
    let mut transient = 0;
    for original in &cut.original_resources {
        latency.push(
            original["latency_micros"]
                .as_u64()
                .ok_or("original native latency")?,
        );
        resident = resident.max(
            original["resident_bytes"]
                .as_u64()
                .ok_or("original native resident memory")?,
        );
        transient = transient.max(
            original["transient_allocation_bytes"]
                .as_u64()
                .ok_or("original native allocation")?,
        );
    }
    latency.sort_unstable();
    let percentile = |percent: usize| latency[(latency.len() * percent).div_ceil(100) - 1];
    let p99 = percentile(99);
    Ok(Metrics {
        observations: count,
        correct,
        accuracy_ppm: accuracy,
        measured_ece_ppm: ece,
        measured_false_acceptance_ppm: false_acceptance,
        abstained,
        p95_latency_micros: percentile(95),
        p99_latency_micros: p99,
        maximum_resident_bytes: resident,
        maximum_transient_allocation_bytes: transient,
        original_native_executions: u64::try_from(latency.len())?,
        operational_constraints_passed: accuracy >= gates.minimum_accuracy_ppm
            && ece <= gates.maximum_ece_ppm
            && false_acceptance <= gates.maximum_false_acceptance_ppm
            && p99 <= gates.maximum_p99_latency_micros
            && resident <= gates.maximum_resident_bytes
            && transient <= gates.maximum_transient_allocation_bytes,
    })
}

#[cfg(test)]
#[path = "initial_neuron_operational_metrics_tests.rs"]
mod tests;
