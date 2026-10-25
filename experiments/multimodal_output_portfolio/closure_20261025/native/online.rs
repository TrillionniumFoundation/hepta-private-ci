//! Causal research controller using the unmodified Agentd owner and native gates.
mod head;
mod future_head;
mod measure;
mod runtime_profile;
mod dynamics_profile;
mod stream_io;
mod online_port;
mod online_log;

use std::io::{BufRead, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;
use codex_hepta_ndu::{NduProjectionKindV1, NduProjectionStoreV1};
use codex_hepta_neuron::*;
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use codex_native_owner_bridge::plasticity_modulator_digest_v1;
use hepta_online_agentd_owner::AgentdNeuronOwner;
use serde::Deserialize;
use serde_json::{Value, json};
use stream_io::{Result, file, SEGMENT};

#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;
const Q: i64 = 1 << 24;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Spec {
    schema: String, pins: runtime_profile::Pins, weights_path: String,
    calibration_path: String, verification_path: String,
    observer_path: String, observer_sha256: String, max_native_ticks: u64,
    registration: Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate { action: String, features: Vec<i64> }

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Decide { request_id: String, generation: u64, weights_sha256: String,
        objective_digest: String, prefix_digest: String, candidates: Vec<Candidate> },
    Observe { request_id: String, decision_digest: String, selected_action: String,
        receipt_path: String, receipt_sha256: String },
    Cancel { request_id: String, decision_digest: String },
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
    owner: Owner, config: NeuronRuntimeConfigV1, root: PathBuf,
    scope: JournalScope, subject: StableId, history: online_log::History,
    ndu: NduProjectionStoreV1, observer: String, maximum: u64,
    started: Instant, time_base: u64, last_time: u64,
    process_ticks: usize, process_peak: usize, tick_samples: Vec<NeuronResourceSampleV1>,
    transition_started: bool,
}

impl Controller {
    fn open(spec_path: &str, expected: &str, root: &Path, resume: bool) -> Result<Self> {
        let raw = checked(spec_path, expected)?;
        let spec: Spec = serde_json::from_slice(&raw)?;
        if spec.schema != "hepta.closure.native-online.v1" || spec.max_native_ticks > 2864
            || spec.max_native_ticks < 2 || !spec.registration.is_object()
        { return Err("Invalid online registration".into()); }
        let weights = checked(&spec.weights_path, &spec.pins.weights)?;
        let calibration = checked(&spec.calibration_path, &spec.pins.calibration)?;
        let verification: Value = serde_json::from_slice(&checked(&spec.verification_path, &spec.pins.verification)?)?;
        checked(&spec.observer_path, &spec.observer_sha256)?;
        if verification["study_qualified"] != true || verification["native_config_point_qualified"] != true
            || verification["native_measured_ece_ppm"].as_u64() != Some(u64::from(spec.pins.measured_ece_ppm))
            || verification["native_measured_false_acceptance_ppm"].as_u64() != Some(u64::from(spec.pins.measured_false_acceptance_ppm))
            || verification["gates"].as_object().is_none_or(|g| g.len() != 4 || g.values().any(|v| v != true))
        { return Err("Frozen complete study qualification rejected".into()); }
        let binary = Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?);
        let identity = json!({"descriptor": expected, "binary": binary.to_string(), "owner": "original AgentdNeuronOwner"});
        if resume {
            if serde_json::from_slice::<Value>(&std::fs::read(root.join("identity.json"))?)? != identity {
                return Err("Resume descriptor or executable identity mismatch".into());
            }
        } else {
            std::fs::create_dir(root)?;
            std::fs::write(root.join("identity.json"), serde_json::to_vec_pretty(&identity)?)?;
        }
        let (mut native, mut config) = runtime_profile::configuration(&spec.pins, binary)?;
        native.width = 33;
        native.normalization_digest = Digest32::of_bytes(b"online.preaction.forecast-carrier.v1;observed-future-not-present");
        config.config_id = StableId::new("closure.online.forecast-carrier.v1")?;
        config.model_id = StableId::new("closure.frozen-causal-future-head.v1")?;
        config.model_manifest_digest = Digest32::of_bytes(&raw);
        config.normalization_digest = native.normalization_digest;
        config.input_feature_dimension = 478;
        config.state_width = 33;
        config.calibration.expires_after_sequence = spec.max_native_ticks;
        dynamics_profile::bind(&mut native, &mut config, dynamics_profile::DynamicsProfile::BoundedBalanced,
            dynamics_profile::DriveDomain::FutureEmittedState)?;
        let baseline = measure::live_bytes();
        let mut head = future_head::FutureHead { weights: serde_json::from_slice(&weights)?,
            calibration: serde_json::from_slice(&calibration)?, config: config.clone(),
            contract: future_head::OutputContract::StateResidual, measured_resident_heap_bytes: 0 };
        head.measured_resident_heap_bytes = measure::live_bytes() - baseline;
        let control = online_port::Control { head, forwards: 0, last_receipt: None };
        let subject = StableId::new("closure.online.research-subject")?;
        let scope = JournalScope { scope_digest: runtime_profile::subject_scope(&subject), objective_digest: expected.parse()? };
        let mut history = online_log::History::open(&root.join("control.jsonl"), resume)?;
        let ndu_root = root.join("ndu");
        if !resume { std::fs::create_dir(&ndu_root)?; }
        let mut ndu = NduProjectionStoreV1::open(&ndu_root)?;
        let runtime = if resume {
            stream_io::recover(root, native, scope, config.clone(), history.native_sequence as usize)?
        } else {
            let witness = FileAnchorWitnessStore::open(file(&root.join("neuron.witness"))?, scope, native.generation, 4096)?;
            NeuronRuntime::bootstrap(file(&root.join("neuron-0000.journal"))?, native, scope, SEGMENT, config.clone(), witness)?
        };
        if runtime.current_anchor()?.map_or(0, |a| a.sequence) != history.native_sequence {
            return Err("Native/controller frontier mismatch; reconciliation required".into());
        }
        if !resume {
            let prior = plasticity_modulator_digest_v1(scope.objective_digest, scope.scope_digest, &[FixedQ32::from_raw(0)])?;
            ndu.append_projection(NduProjectionKindV1::Utility, Digest32::of_bytes(b"registered-zero-prior-not-outcome"),
                scope.objective_digest, scope.scope_digest, prior)?;
            ndu.select_projection(Digest32::of_bytes(b"select-registered-zero-prior"), scope.objective_digest, scope.scope_digest, prior)?;
            history.append(json!({"kind": "bootstrap", "native_sequence": 0,
                "monotonic_micros": 0, "modulator": prior.to_string(), "prior_is_observed_outcome": false}))?;
        }
        if ndu.selected_projection_digest(scope.objective_digest, scope.scope_digest)? != Some(history.modulator) {
            return Err("NDU/controller frontier mismatch; reconciliation required".into());
        }
        let time_base = history.monotonic_micros;
        Ok(Self { owner: AgentdNeuronOwner::new(runtime, control), config, root: root.to_path_buf(),
            scope, subject, history, ndu, observer: spec.observer_sha256, maximum: spec.max_native_ticks,
            started: Instant::now(), time_base, last_time: time_base,
            process_ticks: 0, process_peak: 0, tick_samples: Vec::new(), transition_started: false })
    }

    fn status(&mut self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        let resource = if self.tick_samples.is_empty() { Value::Null } else {
            let summary = summarize_resource_samples(&self.tick_samples, &self.config.resource_envelope)?;
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
            "training_steps": 0, "ticks_in_process": self.process_ticks, "whole_owner_peak_bytes": self.process_peak,
            "native_resource_summary_passed": resource["pilot_ceiling_passed_for_supplied_samples"],
            "native_resource_summary": resource, "authority": "deny_all", "daemon_deployment": false}))
    }

    fn append(&mut self, mut event: Value) -> Result<Digest32> {
        self.transition_started = true;
        event["native_sequence"] = json!(self.owner.runtime().current_anchor()?.map_or(0, |a| a.sequence));
        event["monotonic_micros"] = json!(self.last_time);
        event["modulator"] = json!(self.history.modulator.to_string());
        self.history.append(event)
    }

    fn command(&mut self, command: Command) -> Result<Value> {
        match command {
            Command::Status => self.status(),
            Command::Shutdown => {
                if self.history.pending.is_some() { return Err("Pending outcome or cancellation required".into()); }
                self.status()
            }
            Command::Decide { request_id, generation, weights_sha256, objective_digest, prefix_digest, candidates } => {
                if self.history.pending.is_some() || self.history.requests.contains(&request_id) {
                    return Err("Pending outcome or repeated request".into());
                }
                if generation != self.config.generation.get() || weights_sha256 != self.config.weights_digest.to_string()
                    || objective_digest != self.scope.objective_digest.to_string() || prefix_digest.parse::<Digest32>()?.is_zero()
                    || candidates.len() != 2 || self.history.native_sequence + 2 > self.maximum
                { return Err("Request identity, candidate set or bounded lifetime rejected".into()); }
                StableId::new(request_id.clone())?;
                for (i, candidate) in candidates.iter().enumerate() {
                    if candidate.action != ["refine_text", "couple"][i] || candidate.features.len() != 478
                        || candidate.features.iter().any(|v| !(-8 * Q..=8 * Q).contains(v))
                        || candidate.features[476 + i] != Q || candidate.features[477 - i] != 0
                    { return Err("Invalid public prefix or action encoding".into()); }
                }
                if candidates[0].features[..476] != candidates[1].features[..476] {
                    return Err("Candidate actions do not share the same public prefix".into());
                }
                let began = Instant::now();
                let mut evaluated = Vec::new();
                for candidate in candidates {
                    self.transition_started = true;
                    let count = self.owner.runtime().current_anchor()?.map_or(0, |a| a.sequence);
                    if count > 0 && count % SEGMENT as u64 == 0 {
                        self.owner.runtime_mut().rollover(file(&self.root.join(format!("neuron-{:04}.journal", count / SEGMENT as u64)))?, SEGMENT)?;
                    }
                    let previous = self.owner.runtime().current_anchor()?.map_or(Digest32::ZERO, |a| a.checkpoint_digest);
                    self.last_time = self.time_base + self.started.elapsed().as_micros() as u64 + 1;
                    let input = NeuronTickInputV1 { tick_id: StableId::new(format!("{request_id}.{}", candidate.action))?,
                        subject_id: self.subject.clone(), logical_sequence: count + 1, monotonic_time_micros: self.last_time,
                        checkpoint_digest: previous, input_feature_digest: canonical_feature_vector_digest_v1(&candidate.features),
                        feature_vector_q24: candidate.features, objective_digest: self.scope.objective_digest,
                        ndu_snapshot_digest: self.history.modulator, body_generation: Some(1), modulator_digest: Some(self.history.modulator) };
                    let baseline = measure::start_window();
                    let outer = Instant::now();
                    let result = self.owner.tick(input)?;
                    let owner_micros = outer.elapsed().as_micros();
                    let peak = measure::peak_delta(baseline);
                    self.process_peak = self.process_peak.max(peak);
                    self.process_ticks += 1;
                    let receipt = self.owner.inference_control_mut().last_receipt.take().ok_or("Missing actual feature receipt")?;
                    let admitted = !result.tick.abstain && peak as u64 <= self.config.resource_envelope.transient_allocation_bytes;
                    self.tick_samples.push(NeuronResourceSampleV1 { host_profile_digest: self.config.device_digest,
                        exact_candidate_digest: self.config.model_manifest_digest, observed_at_micros: self.last_time,
                        receipt: result.tick.resource_receipt.clone() });
                    evaluated.push(json!({"action": candidate.action, "admitted": admitted,
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
                let selected = evaluated.iter().filter(|v| v["admitted"] == true)
                    .max_by_key(|v| (v["probability_q24"].as_i64().unwrap_or(i64::MIN), v["action"] == "refine_text"))
                    .and_then(|v| v["action"].as_str()).map(str::to_string);
                let event = json!({"kind": "decision", "request_id": request_id, "prefix_digest": prefix_digest,
                    "selected_action": selected, "candidates": evaluated, "decision_micros": began.elapsed().as_micros(),
                    "future_observation_available": false, "authority": "deny_all"});
                let digest = self.append(event.clone())?;
                Ok(json!({"decision": event, "decision_digest": digest.to_string(), "status": self.status()?}))
            }
            Command::Observe { request_id, decision_digest, selected_action, receipt_path, receipt_sha256 } => {
                if self.history.pending.as_ref() != Some(&(request_id.clone(), decision_digest.clone(), selected_action.clone())) {
                    return Err("Outcome is not bound to the pending decision".into());
                }
                let receipt: Value = serde_json::from_slice(&checked(&receipt_path, &receipt_sha256)?)?;
                if receipt["request_id"] != request_id || receipt["decision_digest"] != decision_digest
                    || receipt["action"] != selected_action || receipt["observer_sha256"] != self.observer
                    || receipt["generation_started_ns"].as_u64().is_none_or(|t| t <= receipt["decision_received_ns"].as_u64().unwrap_or(u64::MAX))
                    || receipt["observed_ns"].as_u64().is_none_or(|t| t <= receipt["generation_started_ns"].as_u64().unwrap_or(u64::MAX))
                { return Err("Observed outcome identity or causal order rejected".into()); }
                let utility = receipt["utility_q32"].as_i64().ok_or("Missing observed utility")?;
                if !(-(1_i64 << 32)..=(1_i64 << 32)).contains(&utility) {
                    return Err("Observed utility outside registered bounded score".into());
                }
                for kind in ["image", "text"] {
                    checked(receipt["media"][kind].as_str().ok_or("Missing emitted media")?,
                        receipt["media_sha256"][kind].as_str().ok_or("Missing emitted media digest")?)?;
                }
                let modulator = plasticity_modulator_digest_v1(self.scope.objective_digest, self.scope.scope_digest, &[FixedQ32::from_raw(utility)])?;
                let identity: Digest32 = receipt_sha256.parse()?;
                self.transition_started = true;
                self.ndu.append_projection(NduProjectionKindV1::Utility, identity, self.scope.objective_digest, self.scope.scope_digest, modulator)?;
                self.ndu.select_projection(Digest32::of_bytes(format!("select:{identity}").as_bytes()), self.scope.objective_digest, self.scope.scope_digest, modulator)?;
                self.history.modulator = modulator;
                let digest = self.append(json!({"kind": "outcome", "request_id": request_id,
                    "decision_digest": decision_digest, "observation_sha256": receipt_sha256, "utility_q32": utility}))?;
                Ok(json!({"outcome_digest": digest.to_string(), "status": self.status()?}))
            }
            Command::Cancel { request_id, decision_digest } => {
                if self.history.pending.as_ref().is_none_or(|(r, d, _)| r != &request_id || d != &decision_digest) {
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
    let mut controller = Controller::open(&args[1], &args[2], Path::new(&args[3]), args[4] == "resume")?;
    println!("{}", json!({"ready": true, "status": controller.status()?}));
    std::io::stdout().flush()?;
    for line in std::io::stdin().lock().lines() {
        let line = line?;
        let command = serde_json::from_str::<Command>(&line);
        let shutdown = matches!(&command, Ok(Command::Shutdown));
        let before = controller.owner.runtime().current_anchor()?;
        controller.transition_started = false;
        let result = command.map_err(|e| e.into()).and_then(|c| controller.command(c));
        let success = result.is_ok();
        let fatal = !success && (controller.transition_started || controller.owner.runtime().current_anchor()? != before);
        let response = match result { Ok(value) => json!({"ok": true, "value": value}),
            Err(error) => json!({"ok": false, "error": error.to_string(), "fatal": fatal}) };
        println!("{response}"); std::io::stdout().flush()?;
        if fatal || shutdown && success { break; }
    }
    Ok(())
}
