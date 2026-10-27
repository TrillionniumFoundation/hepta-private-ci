//! Research adapter executing the pinned original kernel and typed runtime.
use std::error::Error;
use std::io::{self, BufRead, Write};
use std::time::Instant;

use codex_hepta_neuron::{InhibitoryEdge, SparseConfig, SparseTick, sparse_tick};
use codex_hepta_types::{Digest32, Generation};
use serde::Deserialize;
use serde_json::{Value, json};

#[path = "native_head.rs"]
mod native_head;

const Q: i64 = 1 << 24;

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Request {
    SparseFeatures {
        case: String,
        observations: Vec<f64>,
        times: Vec<f64>,
        mask: Vec<bool>,
        obs_var: Option<Vec<f64>>,
    },
    Pair {
        case: String,
        readback_digest: String,
        feedback_q24: i64,
        reset_before_readout: bool,
    },
    Typed {
        case: String,
        directory: String,
        mean: f64,
        variance: f64,
        lower: f64,
        upper: f64,
        expected_checkpoint: Option<String>,
    },
}

fn config() -> Result<SparseConfig, Box<dyn Error>> {
    Ok(SparseConfig {
        model_digest: Digest32::of_bytes(b"repair.original-neuron.scalar-two-channel.v1"),
        normalization_digest: Digest32::of_bytes(b"q24.unit.feedback.v1"),
        generation: Generation::new(1)?,
        width: 10,
        top_k: 2,
        temporal_decay_q24: 3 * Q / 4,
        inhibition_gain_q24: Q / 4,
        inhibition: vec![
            InhibitoryEdge {
                source: 0,
                target: 1,
                weight_q24: Q / 2,
            },
            InhibitoryEdge {
                source: 1,
                target: 0,
                weight_q24: Q / 2,
            },
        ],
        activity_decay_q24: 3 * Q / 4,
        target_activity_q24: Q / 5,
        threshold_rate_q24: Q / 64,
        threshold_min_q24: 0,
        threshold_max_q24: Q / 2,
        eligibility_decay_q24: Q / 2,
    })
}

fn ticks(
    case: &str,
    drives: Vec<Vec<i64>>,
    times: Vec<u64>,
    reset: bool,
    readback: Digest32,
    prefix_digests: Option<Vec<Digest32>>,
) -> Result<Value, Box<dyn Error>> {
    let cfg = config()?;
    let mut state = None;
    let mut receipts = Vec::new();
    for (stage, (drive, clock)) in drives.iter().zip(times).enumerate() {
        if stage == 1 && reset {
            state = None;
        }
        let sequence = if reset && stage == 1 {
            1
        } else {
            stage as u64 + 1
        };
        let input = SparseTick {
            scope_digest: Digest32::of_bytes(case.as_bytes()),
            objective_digest: Digest32::of_bytes(b"post-delivery-target-free-repair.v1"),
            ndu_digest: Digest32::of_bytes(b"synthetic-delivery-scalar-not-full-NDU.v1"),
            body_digest: Digest32::of_bytes(b"fixed-sparse-mechanism-research.v1"),
            input_digest: prefix_digests.as_ref().map_or_else(
                || Digest32::of_parts(&[readback.as_array(), &[stage as u8]]),
                |values| values[stage],
            ),
            sequence,
            monotonic_micros: clock,
            drive_q24: drive.clone(),
            prediction_q24: vec![0; 10],
        };
        let start = Instant::now();
        let (next, receipt) = sparse_tick(&cfg, &input, state.as_ref())?;
        if receipt.authority.grants_any() || !receipt.requires_calibration {
            return Err("Unexpected original-kernel authority".into());
        }
        receipts.push(json!({"stage":stage,"sequence":next.sequence(),"logical_clock_micros":clock,
            "drive_q24":drive,"activation_q24":receipt.activation_q24,
            "eligibility_q24":next.eligibility_q24(),"threshold_q24":next.thresholds_q24(),
            "checkpoint_before":receipt.checkpoint_before.to_string(),"checkpoint_after":receipt.checkpoint_after.to_string(),
            "temporal_digest":next.temporal_state_digest().to_string(),"activation_digest":next.activation_digest().to_string(),
            "eligibility_digest":next.eligibility_digest().to_string(),"config_digest":receipt.config_digest.to_string(),
            "input_digest":receipt.input_digest.to_string(),"native_ns":start.elapsed().as_nanos(),
            "active_fraction_ppm":receipt.active_fraction_ppm,"projection_count":receipt.projection_count,
            "checkpoint_bounded_bytes":next.bounded_encoded_bytes(),"requires_calibration":true,
            "authority":"DENY_ALL","native_owner_integration":false}));
        state = Some(next);
    }
    let last = receipts.last().ok_or("No observations")?;
    let mut features = Vec::new();
    for name in ["activation_q24", "eligibility_q24"] {
        for value in last[name].as_array().ok_or("Missing state")? {
            features.push(value.as_i64().ok_or("Bad state")? as f64 / Q as f64);
        }
    }
    Ok(
        json!({"case":case,"features":features,"ticks":receipts,"original_sparse_tick_calls":drives.len(),
        "checkpoint_reset_intervention":reset,"native_owner_integration":false,"authority":"DENY_ALL"}),
    )
}

fn run(request: Request) -> Result<Value, Box<dyn Error>> {
    match request {
        Request::Pair {
            case,
            readback_digest,
            feedback_q24,
            reset_before_readout,
        } => {
            if case.is_empty() || !(-Q..=Q).contains(&feedback_q24) {
                return Err("Invalid pair input".into());
            }
            let mut first = vec![0; 10];
            first[0] = (-feedback_q24).max(0);
            first[1] = feedback_q24.max(0);
            first[2] = Q / 4;
            ticks(
                &case,
                vec![first, vec![0; 10]],
                vec![1, 2],
                reset_before_readout,
                readback_digest.parse()?,
                None,
            )
        }
        Request::SparseFeatures {
            case,
            observations,
            times,
            mask,
            obs_var,
        } => {
            let n = observations.len();
            let obs_var = obs_var.unwrap_or_else(|| vec![0.64; n]);
            if case.is_empty()
                || n == 0
                || n > 128
                || times.len() != n
                || mask.len() != n
                || obs_var.len() != n
                || obs_var.iter().any(|v| !v.is_finite() || *v < 0.)
                || observations.iter().any(|x| !x.is_finite())
                || times
                    .iter()
                    .any(|t| !t.is_finite() || *t < 0. || *t > 1_000_000.)
                || times.windows(2).any(|w| w[1] < w[0])
            {
                return Err("Invalid public history".into());
            }
            let mut drives = Vec::new();
            let mut prefix_digests = Vec::new();
            let mut clocks = Vec::new();
            let mut prior = 0.;
            let mut previous_time = 0.;
            for i in 0..n {
                prefix_digests.push(Digest32::of_bytes(&serde_json::to_vec(&json!([
                    &observations[..=i],
                    &times[..=i],
                    &mask[..=i],
                    &obs_var[..=i]
                ]))?));
                let value = if mask[i] { observations[i] } else { 0. };
                let delta = if mask[i] { value - prior } else { 0. };
                let input = [
                    value.max(0.),
                    (-value).max(0.),
                    times[i] - previous_time,
                    if mask[i] { 1. } else { 0. },
                    0.25,
                    delta.max(0.),
                    (-delta).max(0.),
                    (i + 1) as f64 / 8.,
                    value.abs(),
                    obs_var[i],
                ];
                drives.push(
                    input
                        .iter()
                        .map(|x| (x.clamp(-8., 8.) * Q as f64).round_ties_even() as i64)
                        .collect(),
                );
                clocks.push((times[i] * 1_000_000.).round() as u64 + i as u64 + 1);
                if mask[i] {
                    prior = value;
                }
                previous_time = times[i];
            }
            let identity = Digest32::of_bytes(&serde_json::to_vec(&json!([
                &observations,
                &times,
                &mask,
                &obs_var
            ]))?);
            ticks(&case, drives, clocks, false, identity, Some(prefix_digests))
        }
        Request::Typed {
            case,
            directory,
            mean,
            variance,
            lower,
            upper,
            expected_checkpoint,
        } => native_head::run(
            &case,
            &directory,
            [mean, variance, lower, upper],
            expected_checkpoint,
        ),
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut stdout = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let result = serde_json::from_str(&line)
            .map_err(|e| e.into())
            .and_then(run);
        let output = match result {
            Ok(value) => value,
            Err(error) => json!({"error":error.to_string(),"accepted":false}),
        };
        writeln!(stdout, "{output}")?;
        stdout.flush()?;
    }
    Ok(())
}
