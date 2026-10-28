//! Durable owner execution of continuous signals with native post-activation actions.
use crate::Result;
use crate::decision;
use crate::model::Profile;
use crate::model::Stage;
use crate::original_owner::AgentdNeuronOwner;
use crate::port::Port;
use crate::replay::Event;
use crate::replay::Ledger;
use crate::replay::Observation;
use crate::replay::{self};
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::time::Instant;
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OpenRequest {
    pub case: String,
    pub seed: u64,
    pub profile_sha256: String,
}
pub struct Session {
    owner: AgentdNeuronOwner<FileAnchorWitnessStore, Port>,
    profile: Profile,
    scope: JournalScope,
    subject: StableId,
    seed: u64,
    bundle: Digest32,
    ledger: Ledger,
    poisoned: bool,
}
pub enum Mode {
    Fresh,
    Restore,
}
fn file(path: &Path, mode: &Mode) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(matches!(mode, Mode::Fresh))
        .truncate(false)
        .open(path)?)
}
impl Session {
    pub fn open(
        root: &Path,
        request: OpenRequest,
        profile: Profile,
        bundle: Digest32,
        binary: Digest32,
        mode: Mode,
    ) -> Result<(Self, Value)> {
        let start = Instant::now();
        if request.case.is_empty()
            || request.case.len() > 100
            || request.case.contains("..")
            || !request
                .case
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
            || request.profile_sha256 != bundle.to_string()
        {
            return Err("Invalid case/profile identity".into());
        }
        let directory = root.join(&request.case);
        let native = profile.native(bundle)?;
        let config = profile.runtime(bundle, binary)?;
        let subject = StableId::new(&request.case)?;
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: profile.objective_digest.parse()?,
        };
        let identity = json!({"schema":"hepta.continuous-boundary.owner-identity.v1","case":request.case,"seed":request.seed,
            "arm":profile.arm_id,"source_model_digest":profile.source_model_digest,"profile_sha256":request.profile_sha256,
            "binary_sha256":binary.to_string(),"native_config_digest":native.digest()?.to_string(),
            "calibration_scope":"bounded-encoder-domain-only-not-task-success","native_authority":"DENY_ALL"});
        let runtime;
        let ledger;
        let replay_steps;
        match mode {
            Mode::Fresh => {
                std::fs::create_dir(&directory)?;
                let witness = FileAnchorWitnessStore::open(
                    file(&directory.join("owner.witness"), &mode)?,
                    scope,
                    native.generation,
                    2048,
                )?;
                runtime = NeuronRuntime::bootstrap(
                    file(&directory.join("owner.journal"), &mode)?,
                    native.clone(),
                    scope,
                    512,
                    config.clone(),
                    witness,
                )?;
                ledger = Ledger::fresh(&directory.join("events.jsonl"))?;
                let mut out = OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(directory.join("IDENTITY.json"))?;
                out.write_all(&serde_json::to_vec_pretty(&identity)?)?;
                out.sync_all()?;
                File::open(&directory)?.sync_all()?;
                replay_steps = 0;
            }
            Mode::Restore => {
                let actual: Value =
                    serde_json::from_slice(&std::fs::read(directory.join("IDENTITY.json"))?)?;
                if actual != identity {
                    return Err("Cold identity/profile/seed mismatch".into());
                }
                let witness = FileAnchorWitnessStore::open(
                    file(&directory.join("owner.witness"), &mode)?,
                    scope,
                    native.generation,
                    2048,
                )?;
                let anchor = witness
                    .current()?
                    .ok_or("Cold replay needs a committed prefix")?;
                ledger = Ledger::restore(
                    &directory.join("events.jsonl"),
                    &profile,
                    &config,
                    scope,
                    &subject,
                    request.seed,
                    Some(anchor),
                )?;
                replay_steps = ledger.events.len();
                runtime = NeuronRuntime::recover(
                    file(&directory.join("owner.journal"), &mode)?,
                    native.clone(),
                    scope,
                    512,
                    config.clone(),
                    anchor,
                    witness,
                )?;
            }
        }
        let session = Self {
            owner: AgentdNeuronOwner::new(
                runtime,
                Port {
                    profile: profile.clone(),
                    config,
                },
            ),
            profile,
            scope,
            subject,
            seed: request.seed,
            bundle,
            ledger,
            poisoned: false,
        };
        let receipt = json!({"status":session.status()?,"original_journal_replay_steps":replay_steps,
            "event_validation_kernel_steps":replay_steps,"event_validation_ndu_calls":replay_steps,
            "open_restore_micros":start.elapsed().as_micros() as u64});
        Ok((session, receipt))
    }
    pub fn status(&self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        Ok(
            json!({"case":self.subject.as_str(),"seed":self.seed,"arm":self.profile.arm_id,
            "step":anchor.map_or(0,|a|a.sequence),"checkpoint":anchor.map_or(Digest32::ZERO,|a|a.checkpoint_digest).to_string(),
            "durable_event_count":self.ledger.events.len(),"terminal":self.ledger.terminal(),
            "host_poisoned":self.poisoned,"owner_authority":"DENY_ALL"}),
        )
    }
    pub fn tick(&mut self, observation: Observation) -> Result<Value> {
        if self.poisoned {
            return Err("Unacknowledged native transition requires reconciliation".into());
        }
        if let Some(value) = self.ledger.lookup(&observation)? {
            return Ok(value);
        }
        if self.ledger.terminal() {
            return Err("Terminal episode; no native tick executed".into());
        }
        let before = self.owner.runtime().current_anchor()?;
        let request = replay::input(
            &self.profile,
            &self.subject,
            self.scope,
            before,
            &observation,
        )?;
        let feature_digest = request.input_feature_digest;
        let event_digest = request.ndu_snapshot_digest;
        self.poisoned = true;
        let output = self.owner.tick(request)?;
        if output.signal.authority.grants_any() {
            return Err("Unexpected native owner authority".into());
        }
        let readout = decision::decide(
            &self.profile,
            &output.signal.signals_q24,
            observation.features.continuous.risk_q24,
            output.tick.checkpoint_after,
        )?;
        let eligibility = self
            .owner
            .runtime()
            .current_eligibility_sample()?
            .ok_or("Missing native eligibility")?;
        let r = &output.tick.resource_receipt;
        let terminal =
            output.tick.abstain || (self.profile.stage == Stage::Act && readout.action == "stop");
        let effective_action = if output.tick.abstain {
            "stop"
        } else if self.profile.stage == Stage::Transform {
            "observe"
        } else {
            &readout.action
        };
        let mut value = json!({"profile_sha256":self.bundle.to_string(),"profile_masks":[self.profile.use_margin,self.profile.use_risk,self.profile.use_flow],"case":self.subject.as_str(),"seed":self.seed,"arm":self.profile.arm_id,"step":observation.step,
            "event_kind":"continuous_readout","event_digest":event_digest.to_string(),"input_feature_digest":feature_digest.to_string(),
            "checkpoint_before":output.tick.checkpoint_before.to_string(),"checkpoint_after":output.tick.checkpoint_after.to_string(),
            "activation_q24":output.signal.signals_q24,"eligibility_q24":eligibility.eligibility_q24(),
            "readout":readout,"effective_action":effective_action,"native_abstain":output.tick.abstain,"terminal":terminal,
            "owner_authority":"DENY_ALL","calibration_scope":"encoder-domain-not-task-success",
            "confidence_ppm":output.tick.confidence_ppm,"ood_ppm":output.tick.ood_ppm,
            "duplicate_event_ignored":false,"native_transition_executed":true,"actual_model_calls":1,"actual_ndu_calls":1,
            "execution_micros":r.execution_micros,"transient_allocation_bytes":r.transient_allocation_bytes,
            "checkpoint_bytes":r.checkpoint_bytes,"journal_bytes_written":r.journal_bytes_written,
            "write_amplification_ppm":r.write_amplification_ppm,"queue_age_micros":r.queue_age_micros,
            "model_latency_micros":output.model_runtime.latency_micros,"model_resident_bytes":output.model_runtime.resident_bytes});
        value["receipt_digest"] =
            json!(Digest32::of_bytes(&serde_json::to_vec(&value)?).to_string());
        self.ledger.append(Event {
            observation,
            output: value.clone(),
        })?;
        self.poisoned = false;
        Ok(value)
    }
}
