//! Research bridge to the exact original sparse_tick. No Agentd or admission.
use std::error::Error;
use std::io::BufRead;
use std::io::Write;
use std::io::{self};
use std::time::Instant;

use codex_hepta_neuron::InhibitoryEdge;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

const Q: i64 = 1 << 24;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    case: String,
    readback_digest: String,
    feedback_q24: i64,
    reset_before_readout: bool,
}

fn run(request: Request) -> Result<Value, Box<dyn Error>> {
    if !(-Q..=Q).contains(&request.feedback_q24) || request.case.is_empty() {
        return Err("Invalid public research input".into());
    }
    let readback: Digest32 = request.readback_digest.parse()?;
    let config = SparseConfig {
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
    };
    let scope = Digest32::of_bytes(request.case.as_bytes());
    let mut state = None;
    let mut receipts = Vec::new();
    for stage in 0..2 {
        if stage == 1 && request.reset_before_readout {
            state = None;
        }
        let mut drive = vec![0; 10];
        if stage == 0 {
            drive[0] = (-request.feedback_q24).max(0);
            drive[1] = request.feedback_q24.max(0);
            drive[2] = Q / 4;
        }
        // Stage two receives no fresh scalar or modality feature. Only prior
        // checkpoint numerical state can carry the feedback into its features.
        let sequence = if stage == 0 || request.reset_before_readout {
            1
        } else {
            2
        };
        let input = SparseTick {
            scope_digest: scope,
            objective_digest: Digest32::of_bytes(b"post-delivery-target-free-repair.v1"),
            ndu_digest: Digest32::of_bytes(b"synthetic-delivery-scalar-not-full-NDU.v1"),
            body_digest: Digest32::of_bytes(b"fixed-sparse-mechanism-research.v1"),
            input_digest: Digest32::of_parts(&[readback.as_array(), &[stage as u8]]),
            sequence,
            monotonic_micros: stage + 1,
            drive_q24: drive.clone(),
            prediction_q24: vec![0; 10],
        };
        let started = Instant::now();
        let (next, receipt) = sparse_tick(&config, &input, state.as_ref())?;
        let native_ns = started.elapsed().as_nanos();
        if receipt.authority.grants_any() || !receipt.requires_calibration {
            return Err("Research mechanism unexpectedly authorized effects".into());
        }
        receipts.push(json!({
            "stage": stage, "sequence": next.sequence(), "logical_clock_micros": stage + 1,
            "drive_q24": drive, "activation_q24": receipt.activation_q24,
            "eligibility_q24": next.eligibility_q24(), "threshold_q24": next.thresholds_q24(),
            "checkpoint_before": receipt.checkpoint_before.to_string(),
            "checkpoint_after": receipt.checkpoint_after.to_string(),
            "temporal_digest": next.temporal_state_digest().to_string(),
            "activation_digest": next.activation_digest().to_string(),
            "eligibility_digest": next.eligibility_digest().to_string(),
            "config_digest": receipt.config_digest.to_string(),
            "input_digest": receipt.input_digest.to_string(),
            "native_ns": native_ns, "active_fraction_ppm": receipt.active_fraction_ppm,
            "projection_count": receipt.projection_count,
            "checkpoint_bounded_bytes": next.bounded_encoded_bytes(),
            "requires_calibration": receipt.requires_calibration,
            "authority": "DENY_ALL", "native_owner_integration": false
        }));
        state = Some(next);
    }
    Ok(json!({"case": request.case, "ticks": receipts,
        "checkpoint_reset_intervention": request.reset_before_readout,
        "original_sparse_tick_calls": 2, "native_owner_integration": false}))
}

fn main() -> Result<(), Box<dyn Error>> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    for line in stdin.lock().lines() {
        let result = run(serde_json::from_str(&line?)?)?;
        writeln!(stdout, "{result}")?;
        stdout.flush()?;
    }
    Ok(())
}
