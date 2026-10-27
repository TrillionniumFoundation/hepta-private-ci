//! Target-free research bridge to the original Hepta Q24 sparse_tick.
//! This binary has no training, target, model-loading, or effect-owner interface.

use std::error::Error;
use std::io::{self, BufRead, Write};
use std::time::Instant;

use codex_hepta_neuron::{InhibitoryEdge, SparseConfig, SparseTick, sparse_tick};
use codex_hepta_types::{Digest32, Generation};
use serde::Deserialize;
use serde_json::{Value, json};

const Q: i64 = 1 << 24;
const WIDTH: usize = 20;
const MAX_FEATURES: usize = 8;
const SOURCE_PIN: &str = "63f198ad85cfa2aa579032256355f446cfe793a0";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    case: String,
    readback_digest: String,
    features_q24: Vec<i64>,
    next_features_q24: Option<Vec<i64>>,
    reset_before_readout: bool,
}

fn run(request: Request) -> Result<Value, Box<dyn Error>> {
    if request.case.is_empty()
        || request.case.len() > 256
        || !(1..=MAX_FEATURES).contains(&request.features_q24.len())
        || request
            .features_q24
            .iter()
            .any(|value| !(-Q..=Q).contains(value))
    {
        return Err("Invalid bounded public feature input".into());
    }
    if let Some(next) = &request.next_features_q24
        && (next.len() != request.features_q24.len()
            || next.iter().any(|value| !(-Q..=Q).contains(value)))
    {
        return Err("Next public observation must have the same bounded feature shape".into());
    }
    let readback: Digest32 = request.readback_digest.parse()?;
    let config = SparseConfig {
        model_digest: Digest32::of_bytes(b"hepta.parameter-field-bridge.signed-eight-channel.v1"),
        normalization_digest: Digest32::of_bytes(b"q24.public-observations.unit-interval.v1"),
        generation: Generation::new(1)?,
        width: WIDTH,
        top_k: 4,
        temporal_decay_q24: 3 * Q / 4,
        inhibition_gain_q24: Q / 4,
        inhibition: (0..MAX_FEATURES)
            .flat_map(|index| {
                [
                    InhibitoryEdge {
                        source: 2 * index,
                        target: 2 * index + 1,
                        weight_q24: Q / 2,
                    },
                    InhibitoryEdge {
                        source: 2 * index + 1,
                        target: 2 * index,
                        weight_q24: Q / 2,
                    },
                ]
            })
            .collect(),
        activity_decay_q24: 3 * Q / 4,
        target_activity_q24: Q / 5,
        threshold_rate_q24: Q / 64,
        threshold_min_q24: 0,
        threshold_max_q24: Q / 2,
        eligibility_decay_q24: Q / 2,
    };
    let scope = Digest32::of_bytes(request.case.as_bytes());
    let mut state = None;
    let mut receipts = Vec::new();
    for stage in 0_u64..2 {
        if stage == 1 && request.reset_before_readout {
            state = None;
        }
        let mut drive = vec![0; WIDTH];
        let features = if stage == 0 {
            Some(&request.features_q24)
        } else {
            request.next_features_q24.as_ref()
        };
        if let Some(features) = features {
            for (index, value) in features.iter().enumerate() {
                drive[2 * index] = (-value).max(0);
                drive[2 * index + 1] = (*value).max(0);
            }
            drive[2 * MAX_FEATURES] = Q / 4;
        }
        // Omission of the second event keeps the original zero-drive readout.
        // With two events, reset removes only history; new features still enter.
        let sequence = if stage == 0 || request.reset_before_readout {
            1
        } else {
            2
        };
        let input = SparseTick {
            scope_digest: scope,
            objective_digest: Digest32::of_bytes(
                b"hepta.parameter-field-bridge.fixed-observed-outcome.v1",
            ),
            ndu_digest: Digest32::of_bytes(b"target-free-research-features-not-full-NDU.v1"),
            body_digest: Digest32::of_bytes(b"original-sparse-kernel.fixed-research-profile.v1"),
            input_digest: Digest32::of_parts(&[readback.as_array(), &stage.to_be_bytes()]),
            sequence,
            monotonic_micros: stage + 1,
            drive_q24: drive.clone(),
            prediction_q24: vec![0; WIDTH],
        };
        let started = Instant::now();
        let (next, receipt) = sparse_tick(&config, &input, state.as_ref())?;
        let native_ns = started.elapsed().as_nanos();
        if receipt.authority.grants_any() || !receipt.requires_calibration {
            return Err("Original research kernel unexpectedly authorized effects".into());
        }
        receipts.push(json!({
            "stage": stage,
            "sequence": next.sequence(),
            "logical_clock_micros": stage + 1,
            "fresh_public_observation": features.is_some(),
            "drive_q24": drive,
            "activation_q24": receipt.activation_q24,
            "eligibility_q24": next.eligibility_q24(),
            "threshold_q24": next.thresholds_q24(),
            "checkpoint_before": receipt.checkpoint_before.to_string(),
            "checkpoint_after": receipt.checkpoint_after.to_string(),
            "temporal_digest": next.temporal_state_digest().to_string(),
            "activation_digest": next.activation_digest().to_string(),
            "eligibility_digest": next.eligibility_digest().to_string(),
            "config_digest": receipt.config_digest.to_string(),
            "input_digest": receipt.input_digest.to_string(),
            "native_ns": native_ns,
            "active_fraction_ppm": receipt.active_fraction_ppm,
            "projection_count": receipt.projection_count,
            "checkpoint_bounded_bytes": next.bounded_encoded_bytes(),
            "requires_calibration": receipt.requires_calibration,
            "authority": "DENY_ALL",
            "native_owner_integration": false
        }));
        state = Some(next);
    }
    Ok(json!({
        "schema": "hepta.parameter-field-bridge.native.v1",
        "case": request.case,
        "source_pin": SOURCE_PIN,
        "feature_count": request.features_q24.len(),
        "next_public_observation_provided": request.next_features_q24.is_some(),
        "ticks": receipts,
        "checkpoint_reset_intervention": request.reset_before_readout,
        "original_sparse_tick_calls": 2,
        "native_owner_integration": false
    }))
}

fn main() -> Result<(), Box<dyn Error>> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.len() > 4096 {
            return Err("Input exceeds bounded research request size".into());
        }
        let response = run(serde_json::from_str(&line)?)?;
        writeln!(stdout, "{response}")?;
        stdout.flush()?;
    }
    Ok(())
}
