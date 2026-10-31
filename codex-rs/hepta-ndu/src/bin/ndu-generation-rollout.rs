//! Bounded stdin/stdout adapter for offline NDU joint-rollout evaluation.
//! This executable loads no model and opens no effect or durable-store port.

use std::error::Error;
use std::io::Read;

use codex_hepta_ndu::GENERATION_ROLLOUT_MAX_BYTES;
use codex_hepta_ndu::GenerationRolloutPinsV1;
use codex_hepta_ndu::evaluate_generation_rollout_v1;

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 3 {
        return Err("usage: ndu-generation-rollout OBJECTIVE_SHA256 SOURCE_BUNDLE_SHA256 MODEL_SNAPSHOT_SHA256 < input.tsv".into());
    }
    let pins = GenerationRolloutPinsV1 {
        objective_digest: args[0].parse()?,
        source_bundle_digest: args[1].parse()?,
        model_snapshot_digest: args[2].parse()?,
    };
    let mut input = String::new();
    std::io::stdin()
        .lock()
        .take((GENERATION_ROLLOUT_MAX_BYTES + 1) as u64)
        .read_to_string(&mut input)?;
    let receipt = evaluate_generation_rollout_v1(&input, pins)?;
    let base = &receipt.evaluation.base;
    // StableId grammar and Digest32 display are JSON-safe ASCII; no free-form
    // input is interpolated. Fixed-point integers are emitted without rounding.
    let advisory = base.advisory_recommendation.as_ref().map_or_else(
        || "null".to_owned(),
        |value| format!("\"{}\"", value.as_str()),
    );
    let evaluated = base.evaluated_candidates.iter().map(|candidate| {
        let resources = candidate.resource.iter().map(|axis| {
            format!("\"{}\":{}", axis.axis.as_str(), axis.value.raw())
        }).collect::<Vec<_>>().join(",");
        format!(
            "{{\"candidate_id\":\"{}\",\"utility_q32\":{},\"risk_q32\":{},\"resource_q32\":{{{resources}}},\"support_digest\":\"{}\"}}",
            candidate.candidate_id.as_str(), candidate.utility[0].value.raw(),
            candidate.risk[0].value.raw(), candidate.support_digest,
        )
    }).collect::<Vec<_>>().join(",");
    let rejected = base
        .rejected_candidates
        .iter()
        .map(|candidate| {
            let reasons = candidate
                .reasons
                .iter()
                .map(|reason| format!("\"{reason:?}\""))
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "{{\"candidate_id\":\"{}\",\"reasons\":[{reasons}]}}",
                candidate.candidate_id.as_str()
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    println!(
        "{{\"schema\":\"hepta.ndu.generation-rollout-receipt.v1\",\"input_digest\":\"{}\",\"objective_digest\":\"{}\",\"source_bundle_digest\":\"{}\",\"model_snapshot_digest\":\"{}\",\"episode_id\":\"{}\",\"subject_class\":\"Episode\",\"generation\":{},\"required_modality_mask\":{},\"disposition\":\"{:?}\",\"advisory_recommendation\":{advisory},\"utility_profile_digest\":\"{}\",\"evaluation_policy_digest\":\"{}\",\"evaluation_digest_v2\":\"{}\",\"evaluated_candidates\":[{evaluated}],\"rejected_candidates\":[{rejected}],\"native_policy_evaluator\":true,\"observation_attestation_verified\":false,\"production_authority\":false,\"authority\":\"DENY_ALL\"}}",
        receipt.input_digest,
        pins.objective_digest,
        pins.source_bundle_digest,
        pins.model_snapshot_digest,
        receipt.episode_id.as_str(),
        base.generation.get(),
        receipt.required_modality_mask,
        base.disposition,
        base.utility_profile_digest,
        receipt.evaluation.evaluation_policy_digest,
        receipt.evaluation.evaluation_digest_v2,
    );
    Ok(())
}
