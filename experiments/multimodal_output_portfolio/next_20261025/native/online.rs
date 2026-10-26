//! Conditional NDU choice through the unmodified Agentd owner and original gates.
//! Derived from closure_20261025/native/online.rs; old frozen execution is retained.
mod dynamics_profile;
mod head;
mod measure;
mod online_bootstrap;
mod online_log;
mod online_port;
mod runtime_profile;
mod stream_io;
mod value_head;

use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreV1;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use codex_native_owner_bridge::plasticity_modulator_digest_v1;
use hepta_online_agentd_owner::AgentdNeuronOwner;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;
use std::io::BufRead;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;
use stream_io::Result;
use stream_io::SEGMENT;
use stream_io::file;

#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;
const Q: i64 = 1 << 24;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Spec {
    schema: String,
    pins: runtime_profile::Pins,
    weights_path: String,
    predictor_path: String,
    predictor_sha256: String,
    selection: String,
    calibration_path: String,
    verification_path: String,
    observer_path: String,
    observer_sha256: String,
    max_native_ticks: u64,
    registration: Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate {
    action: String,
    features: Vec<i64>,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Decide {
        request_id: String,
        generation: u64,
        weights_sha256: String,
        objective_digest: String,
        prefix_digest: String,
        candidates: Vec<Candidate>,
    },
    Observe {
        request_id: String,
        decision_digest: String,
        selected_action: String,
        receipt_path: String,
        receipt_sha256: String,
    },
    Cancel {
        request_id: String,
        decision_digest: String,
    },
    Status,
    Shutdown,
}

fn checked(path: &str, digest: &str) -> Result<Vec<u8>> {
    let bytes = std::fs::read(path)?;
    if Digest32::of_bytes(&bytes).to_string() != digest {
        return Err("Pinned input file changed".into());
    }
    Ok(bytes)
}

type Owner = AgentdNeuronOwner<FileAnchorWitnessStore, online_port::Control>;

struct Controller {
    owner: Owner,
    config: NeuronRuntimeConfigV1,
    root: PathBuf,
    scope: JournalScope,
    subject: StableId,
    history: online_log::History,
    ndu: NduProjectionStoreV1,
    observer: String,
    maximum: u64,
    started: Instant,
    time_base: u64,
    last_time: u64,
    process_ticks: usize,
    process_peak: usize,
    tick_samples: Vec<NeuronResourceSampleV1>,
    transition_started: bool,
    selection: String,
}

impl Controller {
    fn status(&mut self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        let resource = if self.tick_samples.is_empty() {
            Value::Null
        } else {
            let summary =
                summarize_resource_samples(&self.tick_samples, &self.config.resource_envelope)?;
            json!({"sample_count": summary.sample_count, "p95_execution_micros": summary.p95_execution_micros,
                "p99_execution_micros": summary.p99_execution_micros,
                "maximum_transient_allocation_bytes": summary.maximum_transient_allocation_bytes,
                "maximum_checkpoint_bytes": summary.maximum_checkpoint_bytes,
                "maximum_write_amplification_ppm": summary.maximum_write_amplification_ppm,
                "pilot_ceiling_passed_for_supplied_samples": summary.pilot_ceiling_passed_for_supplied_samples,
                "sample_set_digest": summary.sample_set_digest.to_string()})
        };
        Ok(json!({"native_sequence": anchor.map_or(0, |a| a.sequence),
            "anchor": anchor.map(|a| a.checkpoint_digest.to_string()), "history_digest": self.history.last.to_string(),
            "objective_digest": self.scope.objective_digest.to_string(), "modulator": self.history.modulator.to_string(),
            "pending": self.history.pending, "requests": self.history.requests.len(), "outcomes": self.history.outcomes,
            "weights_decoded_in_process": 1, "model_forwards_in_process": self.owner.inference_control_mut().forwards,
            "training_steps": 0, "native_value_layers_loaded": true, "selection": self.selection, "ticks_in_process": self.process_ticks, "whole_owner_peak_bytes": self.process_peak,
            "native_resource_summary_passed": resource["pilot_ceiling_passed_for_supplied_samples"],
            "native_resource_summary": resource, "authority": "deny_all", "daemon_deployment": false}))
    }

    fn append(&mut self, mut event: Value) -> Result<Digest32> {
        self.transition_started = true;
        event["native_sequence"] = json!(
            self.owner
                .runtime()
                .current_anchor()?
                .map_or(0, |a| a.sequence)
        );
        event["monotonic_micros"] = json!(self.last_time);
        event["modulator"] = json!(self.history.modulator.to_string());
        self.history.append(event)
    }

    fn command(&mut self, command: Command) -> Result<Value> {
        match command {
            Command::Status => self.status(),
            Command::Shutdown => {
                if self.history.pending.is_some() {
                    return Err("Pending outcome or cancellation required".into());
                }
                self.status()
            }
            Command::Decide {
                request_id,
                generation,
                weights_sha256,
                objective_digest,
                prefix_digest,
                candidates,
            } => {
                if self.history.pending.is_some() || self.history.requests.contains(&request_id) {
                    return Err("Pending outcome or repeated request".into());
                }
                if generation != self.config.generation.get()
                    || weights_sha256 != self.config.weights_digest.to_string()
                    || objective_digest != self.scope.objective_digest.to_string()
                    || prefix_digest.parse::<Digest32>()?.is_zero()
                    || candidates.len() != 5
                    || self.history.native_sequence + 5 > self.maximum
                {
                    return Err(
                        "Request identity, candidate set or bounded lifetime rejected".into(),
                    );
                }
                StableId::new(request_id.clone())?;
                for (i, candidate) in candidates.iter().enumerate() {
                    if candidate.action
                        != [
                            "stop",
                            "refine_semantic",
                            "refine_image",
                            "refine_text",
                            "couple",
                        ][i]
                        || candidate.features.len() != 511
                        || candidate
                            .features
                            .iter()
                            .any(|v| !(-8 * Q..=8 * Q).contains(v))
                        || value_head::ValueHead::action(&candidate.features)? != i
                        || candidate.features[510] != Q
                        || candidate.features[478..510]
                            .iter()
                            .any(|v| !(-Q..=Q).contains(v))
                    {
                        return Err("Invalid public prefix or action encoding".into());
                    }
                }
                if candidates.iter().skip(1).any(|c| {
                    c.features[..476] != candidates[0].features[..476]
                        || c.features[478..] != candidates[0].features[478..]
                }) {
                    return Err("Candidate actions do not share the same public prefix".into());
                }
                let began = Instant::now();
                let mut evaluated = Vec::new();
                for candidate in candidates {
                    self.transition_started = true;
                    let count = self
                        .owner
                        .runtime()
                        .current_anchor()?
                        .map_or(0, |a| a.sequence);
                    if count > 0 && count % SEGMENT as u64 == 0 {
                        self.owner.runtime_mut().rollover(
                            file(
                                &self
                                    .root
                                    .join(format!("neuron-{:04}.journal", count / SEGMENT as u64)),
                            )?,
                            SEGMENT,
                        )?;
                    }
                    let previous = self
                        .owner
                        .runtime()
                        .current_anchor()?
                        .map_or(Digest32::ZERO, |a| a.checkpoint_digest);
                    self.last_time = self.time_base + self.started.elapsed().as_micros() as u64 + 1;
                    let input = NeuronTickInputV1 {
                        tick_id: StableId::new(format!("{request_id}.{}", candidate.action))?,
                        subject_id: self.subject.clone(),
                        logical_sequence: count + 1,
                        monotonic_time_micros: self.last_time,
                        checkpoint_digest: previous,
                        input_feature_digest: canonical_feature_vector_digest_v1(
                            &candidate.features,
                        ),
                        feature_vector_q24: candidate.features,
                        objective_digest: self.scope.objective_digest,
                        ndu_snapshot_digest: self.history.modulator,
                        body_generation: Some(1),
                        modulator_digest: Some(self.history.modulator),
                    };
                    let baseline = measure::start_window();
                    let outer = Instant::now();
                    let result = self.owner.tick(input)?;
                    let owner_micros = outer.elapsed().as_micros();
                    let peak = measure::peak_delta(baseline);
                    self.process_peak = self.process_peak.max(peak);
                    self.process_ticks += 1;
                    let receipt = self
                        .owner
                        .inference_control_mut()
                        .last_receipt
                        .take()
                        .ok_or("Missing actual feature receipt")?;
                    let moments = self
                        .owner
                        .inference_control_mut()
                        .last_moments
                        .take()
                        .ok_or("Missing actual native conditional moments")?;
                    let raw_probabilities = self
                        .owner
                        .inference_control_mut()
                        .last_raw_probabilities
                        .take()
                        .ok_or("Missing actual native admission predictions")?;
                    let admitted = !result.tick.abstain
                        && peak as u64 <= self.config.resource_envelope.transient_allocation_bytes;
                    self.tick_samples.push(NeuronResourceSampleV1 {
                        host_profile_digest: self.config.device_digest,
                        exact_candidate_digest: self.config.model_manifest_digest,
                        observed_at_micros: self.last_time,
                        receipt: result.tick.resource_receipt.clone(),
                    });
                    evaluated.push(json!({"action": candidate.action, "admitted": admitted,
                        "ndu_moments": moments.iter().map(f64::to_string).collect::<Vec<_>>(),
                        "raw_probabilities": raw_probabilities.iter().map(f64::to_string).collect::<Vec<_>>(),
                        "numeric_log_encoding": "roundtrip-f64-decimal-strings",
                        "probability_q24": receipt.prediction_q24[0], "forecast_q24": receipt.prediction_q24[1..],
                        "confidence_ppm": result.tick.confidence_ppm, "ood_ppm": result.tick.ood_ppm,
                        "native_abstain": result.tick.abstain, "feature_receipt": receipt.receipt_digest.to_string(),
                        "request_digest": receipt.request_digest.to_string(), "native_sequence": count + 1,
                        "anchor": result.tick.checkpoint_after.to_string(), "prior_modulator": self.history.modulator.to_string(),
                        "owner_micros": owner_micros, "owner_peak_bytes": peak,
                        "native_execution_micros": result.tick.resource_receipt.execution_micros,
                        "native_transient_bytes": result.tick.resource_receipt.transient_allocation_bytes,
                        "native_checkpoint_bytes": result.tick.resource_receipt.checkpoint_bytes,
                        "native_write_amplification_ppm": result.tick.resource_receipt.write_amplification_ppm}));
                }
                if evaluated
                    .iter()
                    .any(|v| v["ndu_moments"] != evaluated[0]["ndu_moments"])
                {
                    return Err("Shared public value inputs yielded different predictions".into());
                }
                let feasible =
                    |v: &&Value| v["admitted"] == true && v["action"] != "refine_semantic";
                let selected = if self.selection == "correctness" {
                    evaluated
                        .iter()
                        .filter(feasible)
                        .max_by_key(|v| {
                            (
                                v["probability_q24"].as_i64().unwrap_or(i64::MIN),
                                match v["action"].as_str() {
                                    Some("refine_text") => 4,
                                    Some("couple") => 3,
                                    Some("refine_image") => 2,
                                    Some("stop") => 1,
                                    _ => 0,
                                },
                            )
                        })
                        .and_then(|v| v["action"].as_str())
                        .map(str::to_string)
                } else {
                    let mut best = f64::INFINITY;
                    let mut choice = None;
                    for (index, candidate) in evaluated.iter().enumerate() {
                        let value = candidate["ndu_moments"][index]
                            .as_str()
                            .ok_or("Missing actual native moment")?
                            .parse::<f64>()?;
                        if !value.is_finite() || value <= 0.0 {
                            return Err("Invalid actual native moment".into());
                        }
                        if index != 1 && candidate["admitted"] == true && value < best {
                            best = value;
                            choice = candidate["action"].as_str().map(str::to_string);
                        }
                    }
                    choice
                };
                let event = json!({"kind": "decision", "request_id": request_id, "prefix_digest": prefix_digest,
                    "selected_action": selected, "candidates": evaluated,
                    "selection": self.selection, "stop_retains_actual_current_draft": true, "all_actions_independently_qualified": true,
                    "cost_semantics": "gamma2; per-action .002 already in frozen conditional targets", "decision_micros": began.elapsed().as_micros(),
                    "future_observation_available": false, "authority": "deny_all"});
                let digest = self.append(event.clone())?;
                Ok(
                    json!({"decision": event, "decision_digest": digest.to_string(), "status": self.status()?}),
                )
            }
            Command::Observe {
                request_id,
                decision_digest,
                selected_action,
                receipt_path,
                receipt_sha256,
            } => {
                if self.history.pending.as_ref()
                    != Some(&(
                        request_id.clone(),
                        decision_digest.clone(),
                        selected_action.clone(),
                    ))
                {
                    return Err("Outcome is not bound to the pending decision".into());
                }
                let receipt: Value =
                    serde_json::from_slice(&checked(&receipt_path, &receipt_sha256)?)?;
                if receipt["request_id"] != request_id
                    || receipt["decision_digest"] != decision_digest
                    || receipt["action"] != selected_action
                    || receipt["observer_sha256"] != self.observer
                    || receipt["generation_started_ns"].as_u64().is_none_or(|t| {
                        t <= receipt["decision_received_ns"].as_u64().unwrap_or(u64::MAX)
                    })
                    || receipt["observed_ns"].as_u64().is_none_or(|t| {
                        t <= receipt["generation_started_ns"]
                            .as_u64()
                            .unwrap_or(u64::MAX)
                    })
                {
                    return Err("Observed outcome identity or causal order rejected".into());
                }
                let utility = receipt["utility_q32"]
                    .as_i64()
                    .ok_or("Missing observed utility")?;
                if !(-(1_i64 << 32)..=(1_i64 << 32)).contains(&utility) {
                    return Err("Observed utility outside registered bounded score".into());
                }
                for kind in ["image", "text"] {
                    checked(
                        receipt["media"][kind]
                            .as_str()
                            .ok_or("Missing emitted media")?,
                        receipt["media_sha256"][kind]
                            .as_str()
                            .ok_or("Missing emitted media digest")?,
                    )?;
                }
                let modulator = plasticity_modulator_digest_v1(
                    self.scope.objective_digest,
                    self.scope.scope_digest,
                    &[FixedQ32::from_raw(utility)],
                )?;
                let identity: Digest32 = receipt_sha256.parse()?;
                self.transition_started = true;
                self.ndu.append_projection(
                    NduProjectionKindV1::Utility,
                    identity,
                    self.scope.objective_digest,
                    self.scope.scope_digest,
                    modulator,
                )?;
                self.ndu.select_projection(
                    Digest32::of_bytes(format!("select:{identity}").as_bytes()),
                    self.scope.objective_digest,
                    self.scope.scope_digest,
                    modulator,
                )?;
                self.history.modulator = modulator;
                let digest = self.append(json!({"kind": "outcome", "request_id": request_id,
                    "decision_digest": decision_digest, "observation_sha256": receipt_sha256, "utility_q32": utility}))?;
                Ok(json!({"outcome_digest": digest.to_string(), "status": self.status()?}))
            }
            Command::Cancel {
                request_id,
                decision_digest,
            } => {
                if self
                    .history
                    .pending
                    .as_ref()
                    .is_none_or(|(r, d, _)| r != &request_id || d != &decision_digest)
                {
                    return Err("Cancellation is not bound to the pending decision".into());
                }
                self.append(json!({"kind": "cancel", "request_id": request_id, "decision_digest": decision_digest}))?;
                self.status()
            }
        }
    }
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 5 || !["new", "resume"].contains(&args[4].as_str()) {
        return Err("usage: online descriptor expected-sha state-directory new|resume".into());
    }
    let mut controller =
        Controller::open(&args[1], &args[2], Path::new(&args[3]), args[4] == "resume")?;
    println!("{}", json!({"ready": true, "status": controller.status()?}));
    std::io::stdout().flush()?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let command = serde_json::from_str::<Command>(&line);
        let shutdown = matches!(&command, Ok(Command::Shutdown));
        let before = controller.owner.runtime().current_anchor()?;
        controller.transition_started = false;
        let result = command
            .map_err(|e| e.into())
            .and_then(|c| controller.command(c));
        let success = result.is_ok();
        let fatal = !success
            && (controller.transition_started
                || controller.owner.runtime().current_anchor()? != before);
        let response = match result {
            Ok(value) => json!({"ok": true, "value": value}),
            Err(error) => json!({"ok": false, "error": error.to_string(), "fatal": fatal}),
        };
        println!("{response}");
        std::io::stdout().flush()?;
        if fatal || shutdown && success {
            break;
        }
    }
    Ok(())
}
