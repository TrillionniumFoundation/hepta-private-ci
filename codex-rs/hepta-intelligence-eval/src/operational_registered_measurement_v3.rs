//! Deterministic replay of the actual registered sparse parameters on previously
//! authenticated public source rows. It always retains calibration/slow-path.
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::VerifiedCut;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::time::Instant;

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Replay {
    pub rows: u64,
    pub transcript_digest: String,
    pub final_checkpoint_digest: String,
    pub maximum_checkpoint_bytes: u64,
    pub maximum_projection_count: u32,
    pub all_require_calibration: bool,
}
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Execution {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub resident_high_water_bytes: u64,
}

pub(super) fn replay(
    plan: &NeuronGenerationMaterialV2,
    cut: &VerifiedCut,
) -> HostResult<(Replay, Execution)> {
    replay_sparse(
        &plan.native,
        plan.scope,
        plan.body.semantic_digest()?,
        &cut.source_rows,
    )
}

pub(super) fn replay_sparse(
    config: &SparseConfig,
    scope: JournalScope,
    body: Digest32,
    rows: &[(serde_json::Value, bool)],
) -> HostResult<(Replay, Execution)> {
    let mut previous: Option<SparseCheckpoint> = None;
    let mut transcript = b"hepta.registered-operational.sparse-replay.v3\0".to_vec();
    let mut latency = Vec::with_capacity(rows.len());
    let mut checkpoint_bytes = 0;
    let mut projections = 0;
    let mut all_require_calibration = true;
    for (index, (row, _)) in rows.iter().enumerate() {
        let vector = |name: &str| -> HostResult<Vec<i64>> {
            let values = row[name]
                .as_array()
                .ok_or("authenticated numeric sparse input")?;
            if values.len() != config.width {
                return Err("registered input width differs from authenticated source".into());
            }
            values
                .iter()
                .map(|v| v.as_i64().ok_or_else(|| "authenticated Q24 value".into()))
                .collect()
        };
        let sequence = u64::try_from(index)?
            .checked_add(1)
            .ok_or("replay sequence")?;
        let input = SparseTick {
            scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
            ndu_digest: Digest32::of_bytes(b"hepta.registered-operational.public-source-replay.v3"),
            body_digest: body,
            input_digest: row["input_digest"]
                .as_str()
                .ok_or("authenticated source input identity")?
                .parse()?,
            sequence,
            monotonic_micros: sequence,
            drive_q24: vector("drive_q24")?,
            prediction_q24: vector("prediction_q24")?,
        };
        let start = Instant::now();
        let (next, receipt) = sparse_tick(config, &input, previous.as_ref())?;
        latency.push(u64::try_from(start.elapsed().as_micros())?);
        transcript.extend_from_slice(input.input_digest.as_array());
        transcript.extend_from_slice(next.digest().as_array());
        transcript.extend_from_slice(receipt.config_digest.as_array());
        transcript.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
        transcript.extend_from_slice(&receipt.active_fraction_ppm.to_be_bytes());
        transcript.extend_from_slice(&receipt.projection_count.to_be_bytes());
        for value in &receipt.activation_q24 {
            transcript.extend_from_slice(&value.to_be_bytes());
        }
        checkpoint_bytes = checkpoint_bytes.max(u64::try_from(next.bounded_encoded_bytes())?);
        projections = projections.max(receipt.projection_count);
        all_require_calibration &= receipt.requires_calibration;
        previous = Some(next);
    }
    if latency.is_empty() || latency.len() > 2048 {
        return Err("bounded authenticated replay rows".into());
    }
    latency.sort_unstable();
    let percentile = |p: usize| latency[(latency.len() * p).div_ceil(100) - 1];
    let hwm = std::fs::read_to_string("/proc/self/status")?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmHWM:")
                .and_then(|v| v.split_whitespace().next())
                .and_then(|v| v.parse::<u64>().ok())
        })
        .ok_or("actual kernel process high-water resident memory")?
        .checked_mul(1024)
        .ok_or("resident memory overflow")?;
    Ok((
        Replay {
            rows: u64::try_from(latency.len())?,
            transcript_digest: Digest32::of_bytes(&transcript).to_string(),
            final_checkpoint_digest: previous
                .ok_or("complete final sparse checkpoint")?
                .digest()
                .to_string(),
            maximum_checkpoint_bytes: checkpoint_bytes,
            maximum_projection_count: projections,
            all_require_calibration,
        },
        Execution {
            p95_latency_micros: percentile(95),
            p99_latency_micros: percentile(99),
            resident_high_water_bytes: hwm,
        },
    ))
}

#[cfg(test)]
#[path = "operational_registered_measurement_v3_tests.rs"]
mod tests;
