//! Original-owner composition with immutable model identity and durable stopping.
use crate::events;
use crate::events::Event;
use crate::events::Ledger;
use crate::events::Observation;
use crate::original_owner::AgentdNeuronOwner;
use crate::port;
use crate::profile;
use crate::Result;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use serde_json::Value;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OpenRequest {
    pub case: String,
    pub expires: u64,
    pub model: PathBuf,
    pub model_sha256: String,
    pub calibration: PathBuf,
    pub calibration_sha256: String,
    pub policy: port::Policy,
}

pub enum Mode {
    Fresh,
    Restore,
}

pub struct Session {
    owner: AgentdNeuronOwner<FileAnchorWitnessStore, port::Port>,
    scope: JournalScope,
    subject: StableId,
    root: PathBuf,
    ledger: Ledger,
    external_terminal: Option<Value>,
    poisoned: bool,
}

fn file(path: &Path, create: bool) -> Result<File> {
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .create(create)
        .truncate(false)
        .open(path)?)
}

fn checked(path: &Path, digest: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(path)?;
    if Digest32::of_bytes(&bytes).to_string() != digest {
        return Err("Frozen artifact digest mismatch".into());
    }
    Ok(bytes)
}

impl Session {
    pub fn open(run_root: &Path, request: OpenRequest, mode: Mode) -> Result<(Self, Value)> {
        let started = Instant::now();
        if request.case.is_empty()
            || request.case.contains("..")
            || !request
                .case
                .chars()
                .all(|x| x.is_ascii_alphanumeric() || matches!(x, '.' | '-' | '_'))
        {
            return Err("Case must be a bounded local identifier".into());
        }
        let root = run_root.join(&request.case);
        let bytes = checked(&request.model, &request.model_sha256)?;
        let model: port::Model = serde_json::from_slice(&bytes)?;
        model.validate()?;
        let calibration_raw = checked(&request.calibration, &request.calibration_sha256)?;
        let calibration: Value = serde_json::from_slice(&calibration_raw)?;
        if calibration["schema"] != "hepta.free-boundary.encoder-domain-proof.v1"
            || calibration["model_sha256"] != request.model_sha256
            || calibration["confidence_target"] != "registered_public_encoder_domain_validity"
            || calibration["semantic_quality_qualification"] != false
            || calibration["finite_domain_ece_ppm"] != 0
            || calibration["finite_domain_false_acceptance_ppm"] != 0
            || calibration["domain_points"] != model.states.len() * model.value.len()
        {
            return Err("Calibration identity or finite-domain scope mismatch".into());
        }
        // Execute the registered encoder on every admitted input, not a claimed
        // semantic-success calibration fixture.
        for remaining in 0..model.value.len() {
            for state in 0..model.states.len() {
                let encoded = port::drive(&model.features(state, remaining)?)?;
                if encoded.len() != 10 || encoded.iter().any(|x| x.abs() > 8 * crate::Q) {
                    return Err("Finite encoder-domain validation failed".into());
                }
            }
        }
        let mut bundle_bytes = bytes;
        bundle_bytes.extend(serde_json::to_vec(&request.policy)?);
        let bundle = Digest32::of_bytes(&bundle_bytes);
        let binary = Digest32::of_bytes(&fs::read(std::env::current_exe()?)?);
        let (native, config) = profile::configuration(
            bundle,
            Digest32::of_bytes(&calibration_raw),
            binary,
            request.expires,
        )?;
        let subject = StableId::new(&request.case)?;
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: Digest32::of_bytes(b"free-boundary.finite-gaussian-stopping.v1"),
        };
        let identity = json!({"schema":"hepta.free-boundary.owner-identity.v1",
            "case":request.case,"expires":request.expires,"policy":request.policy,
            "model_sha256":request.model_sha256,"calibration_sha256":request.calibration_sha256,
            "binary_sha256":binary.to_string(),"bundle_sha256":bundle.to_string(),
            "native_config_digest":native.digest()?.to_string(),"owner_authority":"DENY_ALL"});
        let witness;
        let runtime;
        let ledger;
        let replay_steps;
        match mode {
            Mode::Fresh => {
                fs::create_dir(&root)?;
                witness = FileAnchorWitnessStore::open(
                    file(&root.join("owner.witness"), true)?,
                    scope,
                    native.generation,
                    256,
                )?;
                runtime = NeuronRuntime::bootstrap(
                    file(&root.join("owner.journal"), true)?,
                    native.clone(),
                    scope,
                    64,
                    config.clone(),
                    witness,
                )?;
                ledger = Ledger::create(&root.join("events.jsonl"))?;
                let mut output = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(root.join("IDENTITY.json"))?;
                output.write_all(&serde_json::to_vec_pretty(&identity)?)?;
                output.sync_all()?;
                File::open(&root)?.sync_all()?;
                replay_steps = 0;
            }
            Mode::Restore => {
                if serde_json::from_slice::<Value>(&fs::read(root.join("IDENTITY.json"))?)?
                    != identity
                {
                    return Err("Cold recovery identity mismatch".into());
                }
                witness = FileAnchorWitnessStore::open(
                    file(&root.join("owner.witness"), false)?,
                    scope,
                    native.generation,
                    256,
                )?;
                let anchor = witness
                    .current()?
                    .ok_or("Cold recovery requires a committed prefix")?;
                ledger = Ledger::restore(
                    &root.join("events.jsonl"),
                    &native,
                    &config,
                    scope,
                    &subject,
                    &model,
                    &request.policy,
                    Some(anchor),
                )?;
                replay_steps = ledger.len();
                runtime = NeuronRuntime::recover(
                    file(&root.join("owner.journal"), false)?,
                    native.clone(),
                    scope,
                    64,
                    config.clone(),
                    anchor,
                    witness,
                )?;
            }
        }
        let external_terminal = if root.join("FINISH.json").exists() {
            let value: Value = serde_json::from_slice(&fs::read(root.join("FINISH.json"))?)?;
            let mut payload = value.clone();
            payload
                .as_object_mut()
                .ok_or("Malformed terminal record")?
                .remove("record_digest");
            if value["checkpoint"]
                != runtime
                    .current_anchor()?
                    .map_or(Digest32::ZERO, |a| a.checkpoint_digest)
                    .to_string()
                || value["reason"] != "killed"
                || value["owner_authority"] != "DENY_ALL"
                || value["record_digest"]
                    != Digest32::of_bytes(&serde_json::to_vec(&payload)?).to_string()
            {
                return Err("External terminal observation binding mismatch".into());
            }
            Some(value)
        } else {
            None
        };
        let dimensions = (model.states.len(), model.value.len());
        let port = port::Port {
            config,
            model,
            policy: request.policy,
            last: None,
        };
        let session = Self {
            owner: AgentdNeuronOwner::new(runtime, port),
            scope,
            subject,
            root,
            ledger,
            external_terminal,
            poisoned: false,
        };
        let receipt = json!({"status":session.status()?,"original_journal_replay_steps":replay_steps,
            "event_validation_kernel_steps":replay_steps,"event_validation_readout_calls":replay_steps,
            "event_validation_bellman_terms":if replay_steps==0 {0} else {session.ledger.validation_terms()},
            "profile_validation_readouts":dimensions.0*dimensions.1,
            "profile_validation_bellman_terms":dimensions.0*dimensions.0*(dimensions.1-1),
            "finite_encoder_domain_checks":dimensions.0*dimensions.1,
            "open_restore_micros":started.elapsed().as_micros() as u64});
        Ok((session, receipt))
    }

    pub fn status(&self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        Ok(json!({"sequence":anchor.map_or(0,|a|a.sequence),
            "checkpoint":anchor.map_or(Digest32::ZERO,|a|a.checkpoint_digest).to_string(),
            "durable_event_count":self.ledger.len(),"terminal":self.ledger.terminal()||self.external_terminal.is_some(),
            "external_terminal":self.external_terminal,"host_poisoned":self.poisoned,"owner_authority":"DENY_ALL"}))
    }

    pub fn observe(&mut self, observation: Observation) -> Result<Value> {
        if self.poisoned {
            return Err("Unacknowledged owner transition requires reconciliation".into());
        }
        if let Some(value) = self.ledger.lookup(&observation)? {
            return Ok(value);
        }
        if self.external_terminal.is_some() {
            return Err("Episode externally terminated".into());
        }
        self.ledger.validate_next(&observation)?;
        let before = self.owner.runtime().current_anchor()?;
        let input = events::input(
            &self.subject,
            self.scope,
            before,
            &self.owner.inference_control_mut().model,
            &observation,
        )?;
        let event_digest = input.ndu_snapshot_digest;
        self.poisoned = true;
        let output = self.owner.tick(input)?;
        if output.signal.authority.grants_any() {
            return Err("Unexpected native authority".into());
        }
        let readout = self
            .owner
            .inference_control_mut()
            .last
            .clone()
            .ok_or("Missing model readout")?;
        let eligibility = self
            .owner
            .runtime()
            .current_eligibility_sample()?
            .ok_or("Missing owner eligibility")?;
        let r = &output.tick.resource_receipt;
        let terminal = output.tick.abstain || readout.action != port::Action::Continue;
        let result = json!({"sequence":before.map_or(1,|a|a.sequence+1),"event_digest":event_digest.to_string(),
            "checkpoint_before":output.tick.checkpoint_before.to_string(),"checkpoint_after":output.tick.checkpoint_after.to_string(),
            "activation_q24":output.signal.signals_q24,"eligibility_q24":eligibility.eligibility_q24(),
            "readout":readout,"native_abstain":output.tick.abstain,"terminal":terminal,"owner_authority":"DENY_ALL",
            "confidence_ppm":output.tick.confidence_ppm,"ood_ppm":output.tick.ood_ppm,
            "duplicate_event_ignored":false,"native_transition_executed":true,
            "actual_model_calls":1,"actual_bellman_terms":readout.bellman_terms,
            "execution_micros":r.execution_micros,"transient_allocation_bytes":r.transient_allocation_bytes,
            "checkpoint_bytes":r.checkpoint_bytes,"journal_bytes_written":r.journal_bytes_written,
            "write_amplification_ppm":r.write_amplification_ppm,"queue_age_micros":r.queue_age_micros,
            "model_latency_micros":output.model_runtime.latency_micros,"model_resident_bytes":output.model_runtime.resident_bytes});
        self.ledger.append(Event {
            observation,
            output: result.clone(),
        })?;
        self.poisoned = false;
        Ok(result)
    }

    pub fn finish_killed(&mut self, evidence: String) -> Result<Value> {
        let digest: Digest32 = evidence.parse()?;
        if digest.is_zero() || self.poisoned || self.ledger.terminal() {
            return Err("Invalid killed observation".into());
        }
        let mut value = json!({"reason":"killed","evidence_digest":evidence,
            "checkpoint":self.owner.runtime().current_anchor()?.ok_or("Missing prefix")?.checkpoint_digest.to_string(),
            "owner_authority":"DENY_ALL"});
        value["record_digest"] =
            json!(Digest32::of_bytes(&serde_json::to_vec(&value)?).to_string());
        if let Some(previous) = &self.external_terminal {
            if *previous != value {
                return Err("Conflicting terminal observation".into());
            }
            return Ok(previous.clone());
        }
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(self.root.join("FINISH.json"))?;
        file.write_all(&serde_json::to_vec(&value)?)?;
        file.sync_all()?;
        File::open(&self.root)?.sync_all()?;
        self.external_terminal = Some(value.clone());
        Ok(value)
    }
}
