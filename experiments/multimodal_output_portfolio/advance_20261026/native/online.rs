//! Actual 100-code portfolio and late source evidence through original Hepta owner.
mod bootstrap;
mod control;
mod dynamics_profile;
mod head;
mod history;
mod measure;
mod media_receipt;
mod online_port;
mod outcome;
mod qualification;
mod runtime_profile;
mod semantic;
mod stream_io;
use codex_hepta_ndu::{NduProjectionKindV1, NduProjectionStoreV1};
use codex_hepta_neuron::*;
use codex_hepta_types::{Digest32, FixedQ32, StableId};
use codex_native_owner_bridge::plasticity_modulator_digest_v1;
use hepta_online_agentd_owner::AgentdNeuronOwner;
use semantic::Q;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    io::{BufRead, Write},
    path::{Path, PathBuf},
    time::Instant,
};
use stream_io::{Result, SEGMENT, file};

#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Spec {
    schema: String,
    pins: runtime_profile::Pins,
    weights_path: String,
    calibration_path: String,
    verification_path: String,
    likelihood_path: String,
    likelihood_sha256: String,
    observer_path: String,
    observer_sha256: String,
    max_native_ticks: u64,
    stream_id: String,
    source_group_id: String,
    mode: String,
    policy: String,
    emit_cost: f64,
    acquire_cost: f64,
    numeric_modulation: bool,
}
#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Decide {
        request_id: String,
        episode_id: String,
        parent_outcome_digest: Option<String>,
        generation: u64,
        weights_sha256: String,
        objective_digest: String,
        prefix_digest: String,
        features: Vec<i64>,
        route: String,
        remaining: u64,
        explicit_missing: bool,
    },
    Observe {
        request_id: String,
        decision_digest: String,
        selected_action: usize,
        receipt_path: String,
        receipt_sha256: String,
    },
    Cancel {
        request_id: String,
        decision_digest: String,
    },
    Status,
    Shutdown,
    Disconnect,
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
    history: history::History,
    ndu: NduProjectionStoreV1,
    spec: Spec,
    started: Instant,
    time_base: u64,
    last_time: u64,
    transition_started: bool,
    process_peak: usize,
    tick_samples: Vec<NeuronResourceSampleV1>,
}
impl Controller {
    fn eligibility(&self) -> Result<Vec<i64>> {
        Ok(self
            .owner
            .runtime()
            .current_eligibility_sample()?
            .map_or_else(|| vec![0; 33], |s| s.eligibility_q24().to_vec()))
    }
    fn status(&mut self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        let eligibility = self.eligibility()?;
        let resources = if self.tick_samples.is_empty() {
            Value::Null
        } else {
            let s = summarize_resource_samples(&self.tick_samples, &self.config.resource_envelope)?;
            json!({"samples":s.sample_count,"p95_us":s.p95_execution_micros,"p99_us":s.p99_execution_micros,
                "max_transient":s.maximum_transient_allocation_bytes,"max_checkpoint":s.maximum_checkpoint_bytes,
                "max_write_amplification_ppm":s.maximum_write_amplification_ppm,"passed":s.pilot_ceiling_passed_for_supplied_samples})
        };
        Ok(
            json!({"native_sequence":anchor.map_or(0,|a|a.sequence),"anchor":anchor.map(|a|a.checkpoint_digest.to_string()),
            "eligibility_q24":eligibility,"eligibility_digest":canonical_feature_vector_digest_v1(&eligibility).to_string(),
            "history_digest":self.history.last.to_string(),"objective_digest":self.scope.objective_digest.to_string(),
            "modulator":self.history.modulator.to_string(),"utility_q32":self.history.utility_q32,
            "pending":self.history.pending,"completed":self.history.completed,"late_audio_label":self.history.late_label,
            "requests":self.history.requests.len(),"outcomes":self.history.outcomes,
            "model_forwards":self.owner.inference_control_mut().forwards,"whole_owner_peak_bytes":self.process_peak,
            "native_resources":resources,"stream_id":self.spec.stream_id,"source_group_id":self.spec.source_group_id,
            "mode":self.spec.mode,"numeric_modulation":self.spec.numeric_modulation,"policy":self.spec.policy,
            "qualification_inherited":false,"authority":"deny_all","daemon_deployment":false}),
        )
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
        event["utility_q32"] = json!(self.history.utility_q32);
        self.history.append(event)
    }
    fn tick(&mut self, request: &str, action: usize, mut features: Vec<i64>) -> Result<Value> {
        features[178] = action as i64 * control::INDEX_Q;
        features[181..214].copy_from_slice(&self.eligibility()?);
        self.transition_started = true;
        let anchor = self.owner.runtime().current_anchor()?;
        let count = anchor.map_or(0, |a| a.sequence);
        if count >= self.spec.max_native_ticks {
            return Err("Original bounded stream lifetime exhausted".into());
        }
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
        self.last_time = self.time_base + self.started.elapsed().as_micros() as u64 + 1;
        let before_eligibility = self.eligibility()?;
        let feature_digest = canonical_feature_vector_digest_v1(&features);
        let input = NeuronTickInputV1 {
            tick_id: StableId::new(format!("{request}.a{action}"))?,
            subject_id: self.subject.clone(),
            logical_sequence: count + 1,
            monotonic_time_micros: self.last_time,
            checkpoint_digest: anchor.map_or(Digest32::ZERO, |a| a.checkpoint_digest),
            input_feature_digest: feature_digest,
            feature_vector_q24: features,
            objective_digest: self.scope.objective_digest,
            ndu_snapshot_digest: self.history.modulator,
            body_generation: Some(1),
            modulator_digest: Some(self.history.modulator),
        };
        let baseline = measure::start_window();
        let began = Instant::now();
        let result = self.owner.tick(input)?;
        let wall = began.elapsed().as_micros();
        let peak = measure::peak_delta(baseline);
        self.process_peak = self.process_peak.max(peak);
        let receipt = self
            .owner
            .inference_control_mut()
            .last_receipt
            .take()
            .ok_or("Missing actual model receipt")?;
        let admitted = !result.tick.abstain
            && peak as u64 <= self.config.resource_envelope.transient_allocation_bytes;
        self.tick_samples.push(NeuronResourceSampleV1 {
            host_profile_digest: self.config.device_digest,
            exact_candidate_digest: self.config.model_manifest_digest,
            observed_at_micros: self.last_time,
            receipt: result.tick.resource_receipt.clone(),
        });
        Ok(
            json!({"action":action,"admitted":admitted,"native_abstain":result.tick.abstain,
            "confidence_ppm":result.tick.confidence_ppm,"ood_ppm":result.tick.ood_ppm,
            "prediction_q24":receipt.prediction_q24,"drive_q24":receipt.drive_q24,
            "prediction_error_q24":result.tick.prediction_error_q24,
            "temporal_state_digest":result.signal.temporal_state_digest.to_string(),
            "activation_digest":result.tick.activation_digest.to_string(),"active_indices":result.tick.active_indices,
            "activation_q24":result.signal.signals_q24,"threshold_digest":result.tick.threshold_digest.to_string(),
            "sparsity_ppm":result.tick.sparsity_ppm,"projection_count":result.tick.resource_receipt.saturation_count,
            "eligibility_before_q24":before_eligibility,"eligibility_after_q24":self.eligibility()?,
            "feature_digest":feature_digest.to_string(),"model_receipt":receipt.receipt_digest.to_string(),
            "sequence":count+1,"anchor":result.tick.checkpoint_after.to_string(),"owner_us":wall,"owner_peak_bytes":peak,
            "native_execution_us":result.tick.resource_receipt.execution_micros,
            "native_transient_bytes":result.tick.resource_receipt.transient_allocation_bytes,
            "native_checkpoint_bytes":result.tick.resource_receipt.checkpoint_bytes,
            "native_write_amplification_ppm":result.tick.resource_receipt.write_amplification_ppm}),
        )
    }
    fn command(&mut self, c: Command) -> Result<Value> {
        match c {
            Command::Status | Command::Disconnect => self.status(),
            Command::Shutdown => {
                if self.history.pending.is_some() {
                    return Err("Pending outcome/cancel required".into());
                }
                self.status()
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
                    return Err("Cancellation identity mismatch".into());
                }
                self.append(json!({"kind":"cancel","request_id":request_id,"decision_digest":decision_digest}))?;
                self.status()
            }
            Command::Observe {
                request_id,
                decision_digest,
                selected_action,
                receipt_path,
                receipt_sha256,
            } => self.observe(
                request_id,
                decision_digest,
                selected_action,
                receipt_path,
                receipt_sha256,
            ),
            Command::Decide {
                request_id,
                episode_id,
                parent_outcome_digest,
                generation,
                weights_sha256,
                objective_digest,
                prefix_digest,
                features,
                route,
                remaining,
                explicit_missing,
            } => {
                if self.history.pending.is_some() || self.history.requests.contains(&request_id) {
                    return Err("Pending or repeated request".into());
                }
                if generation != self.config.generation.get()
                    || weights_sha256 != self.config.weights_digest.to_string()
                    || objective_digest != self.scope.objective_digest.to_string()
                    || features.len() != 176
                    || ![1, 2].contains(&remaining)
                    || prefix_digest != canonical_feature_vector_digest_v1(&features).to_string()
                {
                    return Err("Request identity/public feature digest rejected".into());
                }
                StableId::new(request_id.clone())?;
                StableId::new(episode_id.clone())?;
                let initial = self.history.completed;
                if initial {
                    if parent_outcome_digest.is_some() {
                        return Err(
                            "New episode cannot claim a previous external observation".into()
                        );
                    }
                } else if self.history.episode.as_ref() != Some(&episode_id)
                    || self.history.prefix.as_ref() != Some(&prefix_digest)
                    || self.history.late_label.is_none()
                    || remaining != 1
                    || parent_outcome_digest != self.history.last_outcome
                {
                    return Err("Continuation must retain initial public input and follow actual external evidence".into());
                }
                let route_index = ["image", "text", "audio", "video"]
                    .iter()
                    .position(|s| *s == route)
                    .ok_or("Unknown input route")?;
                let mut x = features;
                x.extend([
                    route_index as i64 * Q,
                    remaining as i64 * Q,
                    0,
                    self.history.utility_q32 / 256,
                    if initial {
                        0
                    } else {
                        (self.history.late_label.unwrap_or(0) + 1) as i64 * control::INDEX_Q
                    },
                ]);
                x.extend(self.eligibility()?);
                x.push(if explicit_missing { Q } else { 0 });
                let planning = Instant::now();
                let forecast = self.owner.inference_control_mut().forecast(&x)?;
                let planning_us = planning.elapsed().as_micros();
                // Clear once so the first true owner tick executes and charges actual frozen layers.
                self.owner.inference_control_mut().cached = None;
                let mut mask = vec![false; 102];
                let mut ticks = Vec::new();
                let eligible: Vec<usize> = (0..102)
                    .filter(|a| {
                        *a != 100
                            && (*a != 101
                                || remaining == 2 && initial && self.spec.policy != "fixed_initial")
                            && control::admitted(forecast.calibrated[*a])
                    })
                    .collect();
                // Missing/low-confidence requests still execute a real original gate tick.
                let checked_actions = if eligible.is_empty() {
                    vec![0]
                } else {
                    eligible.clone()
                };
                for a in checked_actions {
                    let t = self.tick(&request_id, a, x.clone())?;
                    mask[a] = t["admitted"] == true && eligible.contains(&a);
                    ticks.push(t);
                }
                let mut selected = (0..102).filter(|a| mask[*a]).min_by(|a, b| {
                    forecast.moments[*a]
                        .total_cmp(&forecast.moments[*b])
                        .then(a.cmp(b))
                });
                if self.spec.policy == "fixed_late" && mask[101] {
                    selected = Some(101);
                }
                let event = json!({"kind":"decision","request_id":request_id,"episode_id":episode_id,
                    "initial":initial,"prefix_digest":prefix_digest,"parent_outcome_digest":parent_outcome_digest,
                    "remaining":remaining,"explicit_missing":explicit_missing,"route":route,"selected_action":selected,
                    "law":forecast.law.iter().map(f64::to_string).collect::<Vec<_>>(),
                    "moments":forecast.moments.iter().map(f64::to_string).collect::<Vec<_>>(),
                    "raw_success":forecast.raw.iter().map(f64::to_string).collect::<Vec<_>>(),
                    "calibrated_success":forecast.calibrated.iter().map(f64::to_string).collect::<Vec<_>>(),
                    "actual_mask":mask,"ticks":ticks,"future_actions":forecast.future_actions,
                    "future_no_admitted_mass":forecast.future_rejected_mass.to_string(),"planning_us":planning_us,
                    "screened_content_rejections":102-eligible.len(),"state_readback_is_eligibility":true,
                    "future_stochastic_resource_law":"unmodelled; actual current gates authoritative",
                    "own_output_updates_target_belief":false,"authority":"deny_all"});
                let digest = self.append(event.clone())?;
                Ok(
                    json!({"decision":event,"decision_digest":digest.to_string(),"status":self.status()?}),
                )
            }
        }
    }
}
fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 5 || !["new", "resume"].contains(&args[4].as_str()) {
        return Err("usage: online descriptor expected-sha state-directory new|resume".into());
    }
    let mut c = Controller::open(&args[1], &args[2], Path::new(&args[3]), args[4] == "resume")?;
    println!("{}", json!({"ready":true,"status":c.status()?}));
    std::io::stdout().flush()?;
    for line in std::io::stdin().lock().lines() {
        let command = serde_json::from_str::<Command>(&line?);
        let exit = matches!(&command, Ok(Command::Shutdown | Command::Disconnect));
        let before = c.owner.runtime().current_anchor()?;
        c.transition_started = false;
        let result = command.map_err(|e| e.into()).and_then(|cmd| c.command(cmd));
        let success = result.is_ok();
        let fatal =
            !success && (c.transition_started || c.owner.runtime().current_anchor()? != before);
        let response = match result {
            Ok(v) => json!({"ok":true,"value":v}),
            Err(e) => json!({"ok":false,"error":e.to_string(),"fatal":fatal}),
        };
        println!("{response}");
        std::io::stdout().flush()?;
        if fatal || exit && success {
            break;
        }
    }
    Ok(())
}
