//! Research host around the unchanged AgentdNeuronOwner and durable runtime.
mod events;
mod measure;
mod original_owner;
mod port;
mod profile;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use events::Event;
use events::Ledger;
use original_owner::AgentdNeuronOwner;
use port::Model;
use port::Port;
use serde::Deserialize;
use serde_json::json;
use serde_json::Value;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::BufRead;
use std::io::Write;
use std::io::{self};
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const Q: i64 = 1 << 24;
#[global_allocator]
static ALLOCATOR: measure::ObservedAllocator = measure::ObservedAllocator;

#[derive(Deserialize)]
#[serde(tag = "command", deny_unknown_fields)]
enum Request {
    Open {
        directory: PathBuf,
        case: String,
        expires: u64,
        model: PathBuf,
        model_sha256: String,
        calibration: PathBuf,
        calibration_sha256: String,
    },
    Resume {
        directory: PathBuf,
        case: String,
        expires: u64,
        model: PathBuf,
        model_sha256: String,
        calibration: PathBuf,
        calibration_sha256: String,
    },
    Tick {
        event_id: String,
        phase: i64,
        feedback_q24: i64,
        receipt_digest: String,
    },
    Forecast {
        feedback_q24: i64,
        branch: String,
    },
    Status,
    Close,
}

enum Start {
    Fresh,
    Restore,
}

struct Session {
    owner: AgentdNeuronOwner<FileAnchorWitnessStore, Port>,
    native: SparseConfig,
    config: NeuronRuntimeConfigV1,
    scope: JournalScope,
    subject: StableId,
    root: PathBuf,
    ledger: Ledger,
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

fn checked_bytes(path: &Path, digest: &str) -> Result<Vec<u8>> {
    let raw = fs::read(path)?;
    if Digest32::of_bytes(&raw).to_string() != digest {
        return Err("Artifact identity mismatch".into());
    }
    Ok(raw)
}

impl Session {
    fn open(
        mode: Start,
        root: PathBuf,
        case: String,
        expires: u64,
        model_path: PathBuf,
        model_sha: String,
        calibration_path: PathBuf,
        calibration_sha: String,
    ) -> Result<Self> {
        let model_raw = checked_bytes(&model_path, &model_sha)?;
        let model: Model = serde_json::from_slice(&model_raw)?;
        if model.schema != "hepta.continuation.owner-readout.v1"
            || model.weights.len() != 11
            || model.weights.iter().any(|x| !x.is_finite())
        {
            return Err("Invalid readout model".into());
        }
        let calibration_raw = checked_bytes(&calibration_path, &calibration_sha)?;
        let calibration: Value = serde_json::from_slice(&calibration_raw)?;
        if calibration["schema"] != "hepta.continuation.encoder-domain-proof.v1"
            || calibration["confidence_target"] != "registered_public_encoder_domain_validity"
            || calibration["semantic_quality_qualification"] != false
            || calibration["finite_domain_ece_ppm"] != 0
            || calibration["finite_domain_false_acceptance_ppm"] != 0
        {
            return Err("Calibration role or finite-domain evidence mismatch".into());
        }
        let subject = StableId::new(case)?;
        let mut scope_bytes = b"hepta.neuron.subject-scope.v1".to_vec();
        scope_bytes.extend_from_slice(&(subject.as_str().len() as u32).to_be_bytes());
        scope_bytes.extend_from_slice(subject.as_str().as_bytes());
        let scope = JournalScope {
            scope_digest: Digest32::of_bytes(&scope_bytes),
            objective_digest: Digest32::of_bytes(b"continuation.complete-delivered-return.v1"),
        };
        let binary = Digest32::of_bytes(&fs::read(std::env::current_exe()?)?);
        let (native, config) = profile::configuration(
            Digest32::of_bytes(&model_raw),
            Digest32::of_bytes(&calibration_raw),
            binary,
            expires,
        )?;
        let identity = json!({
            "schema":"hepta.continuation.checkpoint-bound-events.v2",
            "case":subject.as_str(), "model_sha256":model_sha, "calibration_sha256":calibration_sha,
            "binary_sha256":binary.to_string(), "expires":expires, "native_config":native.digest()?.to_string(),
            "owner_authority":"DENY_ALL", "host_dispatch_authorization":"separate protocol-scoped research permit"
        });
        let (owner, ledger) = match mode {
            Start::Fresh => {
                fs::create_dir(&root)?;
                let witness = FileAnchorWitnessStore::open(
                    file(&root.join("owner.witness"), true)?,
                    scope,
                    native.generation,
                    128,
                )?;
                let runtime = NeuronRuntime::bootstrap(
                    file(&root.join("owner.journal"), true)?,
                    native.clone(),
                    scope,
                    /*max_records*/ 32,
                    config.clone(),
                    witness,
                )?;
                let port = Port {
                    config: config.clone(),
                    model,
                    proposed_repair: false,
                    logit: 0.0,
                };
                let ledger = Ledger::create(&root.join("events.jsonl"))?;
                let mut id_file = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(root.join("IDENTITY.json"))?;
                id_file.write_all(&serde_json::to_vec_pretty(&identity)?)?;
                id_file.sync_all()?;
                File::open(&root)?.sync_all()?;
                (AgentdNeuronOwner::new(runtime, port), ledger)
            }
            Start::Restore => {
                if serde_json::from_slice::<Value>(&fs::read(root.join("IDENTITY.json"))?)?
                    != identity
                {
                    return Err(
                        "Restore identity differs from frozen host/model/calibration".into(),
                    );
                }
                Self::recover(&root, &native, &config, scope, &subject, model)?
            }
        };
        Ok(Self {
            owner,
            native,
            config,
            scope,
            subject,
            root,
            ledger,
            poisoned: false,
        })
    }

    fn recover(
        root: &Path,
        native: &SparseConfig,
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
        subject: &StableId,
        model: Model,
    ) -> Result<(AgentdNeuronOwner<FileAnchorWitnessStore, Port>, Ledger)> {
        let witness = FileAnchorWitnessStore::open(
            file(&root.join("owner.witness"), false)?,
            scope,
            native.generation,
            128,
        )?;
        let anchor = witness
            .current()?
            .ok_or("Restore requires a committed prefix")?;
        let ledger = Ledger::restore(
            &root.join("events.jsonl"),
            native,
            config,
            scope,
            subject,
            &model,
            Some(anchor),
        )?;
        let runtime = NeuronRuntime::recover(
            file(&root.join("owner.journal"), false)?,
            native.clone(),
            scope,
            /*max_records*/ 32,
            config.clone(),
            anchor,
            witness,
        )?;
        let port = Port {
            config: config.clone(),
            model,
            proposed_repair: false,
            logit: 0.0,
        };
        Ok((AgentdNeuronOwner::new(runtime, port), ledger))
    }

    fn sequence(&self) -> Result<u64> {
        Ok(self
            .owner
            .runtime()
            .current_anchor()?
            .map_or(0, |anchor| anchor.sequence))
    }

    fn eligibility(&self) -> Result<Vec<i64>> {
        Ok(self
            .owner
            .runtime()
            .current_eligibility_sample()?
            .map_or_else(|| vec![0; 10], |sample| sample.eligibility_q24().to_vec()))
    }

    fn status(&self) -> Result<Value> {
        Ok(
            json!({"sequence":self.sequence()?, "eligibility_q24":self.eligibility()?,
            "checkpoint":self.owner.runtime().current_anchor()?.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest).to_string(),
            "owner_authority":"DENY_ALL", "expires":self.config.calibration.expires_after_sequence,
            "durable_event_count":self.ledger.len(),"host_poisoned":self.poisoned}),
        )
    }

    fn tick(
        &mut self,
        event_id: &str,
        phase: i64,
        feedback: i64,
        receipt_digest: &str,
    ) -> Result<Value> {
        if self.poisoned {
            return Err("Unacknowledged native transition: host requires forensic recovery".into());
        }
        if let Some(output) = self
            .ledger
            .lookup(event_id, phase, feedback, receipt_digest)?
        {
            return Ok(output);
        }
        port::encode(phase, feedback)?;
        let receipt: Digest32 = receipt_digest.parse()?;
        if receipt.is_zero() {
            return Err("Readback/evidence digest required".into());
        }
        let previous = self.owner.runtime().current_anchor()?;
        let sequence = previous.map_or(1, |anchor| anchor.sequence + 1);
        let before = self.eligibility()?;
        let input = events::input(
            &self.subject,
            self.scope,
            previous,
            &before,
            event_id,
            phase,
            feedback,
            receipt,
        )?;
        let bound_evidence = input.ndu_snapshot_digest;
        self.poisoned = true;
        let output = self.owner.tick(input)?;
        if output.signal.authority.grants_any() {
            return Err("Unexpected authority grant".into());
        }
        let head = self.owner.inference_control_mut();
        let proposal = head.proposed_repair;
        let logit = head.logit;
        let after = self.eligibility()?;
        let r = &output.tick.resource_receipt;
        let result = json!({"phase":phase,"feedback_q24":feedback,"sequence":sequence,
            "event_id":event_id,"bound_event_evidence_digest":bound_evidence.to_string(),
            "duplicate_event_ignored":false,"native_transition_executed":true,
            "evidence_digest":receipt_digest,"checkpoint_before":output.tick.checkpoint_before.to_string(),
            "checkpoint_after":output.tick.checkpoint_after.to_string(),
            "activation_q24":output.signal.signals_q24,"eligibility_before_q24":before,"eligibility_after_q24":after,
            "confidence_ppm":output.tick.confidence_ppm,"ood_ppm":output.tick.ood_ppm,
            "native_abstain":output.tick.abstain,"owner_authority":"DENY_ALL",
            "proposed_repair":proposal,"readout_logit":logit,
            "readout_scalar_input":false,"readout_target_input":false,
            "execution_micros":r.execution_micros,"transient_allocation_bytes":r.transient_allocation_bytes,
            "checkpoint_bytes":r.checkpoint_bytes,"journal_bytes_written":r.journal_bytes_written,
            "write_amplification_ppm":r.write_amplification_ppm,"queue_age_micros":r.queue_age_micros,
            "model_latency_micros":output.model_runtime.latency_micros,
            "model_resident_bytes":output.model_runtime.resident_bytes});
        self.ledger.append(Event {
            event_id: event_id.to_owned(),
            phase,
            feedback_q24: feedback,
            receipt_digest: receipt_digest.to_owned(),
            output: result.clone(),
        })?;
        self.poisoned = false;
        Ok(result)
    }

    fn forecast(&mut self, feedback: i64, branch: &str) -> Result<Value> {
        if self.poisoned {
            return Err("Cannot fork unacknowledged native transition".into());
        }
        if branch.is_empty()
            || !branch
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '-')
        {
            return Err("Invalid branch name".into());
        }
        let root = self.root.join(format!("forecast-{branch}"));
        fs::create_dir(&root)?;
        for name in [
            "owner.journal",
            "owner.witness",
            "events.jsonl",
            "IDENTITY.json",
        ] {
            fs::copy(self.root.join(name), root.join(name))?;
        }
        let restore_start = Instant::now();
        let model = self.owner.inference_control_mut().model.clone();
        let (owner, ledger) = Self::recover(
            &root,
            &self.native,
            &self.config,
            self.scope,
            &self.subject,
            model,
        )?;
        let validation_steps = ledger.len();
        let restore_micros = restore_start.elapsed().as_micros() as u64;
        let mut child = Self {
            owner,
            native: self.native.clone(),
            config: self.config.clone(),
            scope: self.scope,
            subject: self.subject.clone(),
            root,
            ledger,
            poisoned: false,
        };
        let start = child.status()?;
        let evidence =
            Digest32::of_bytes(format!("hypothetical-observation:{feedback}").as_bytes())
                .to_string();
        let ticks = vec![
            child.tick(
                &format!("hypothesis.{branch}.feedback"),
                1,
                feedback,
                &evidence,
            )?,
            child.tick(&format!("hypothesis.{branch}.hold"), 2, 0, &evidence)?,
            child.tick(&format!("hypothesis.{branch}.decision"), 3, 0, &evidence)?,
        ];
        let end = child.status()?;
        Ok(
            json!({"branch":branch,"start":start,"ticks":ticks,"end":end,
            "shadow_only":true,"media_dispatched":false,"committed_parent_unchanged":self.status()?==start,
            "ledger_validation_kernel_steps":validation_steps,"original_journal_replayed_prefix_steps":validation_steps,
            "restore_micros":restore_micros}),
        )
    }
}

fn main() -> Result<()> {
    let mut session: Option<Session> = None;
    let mut stdout = io::stdout().lock();
    for line in io::stdin().lock().lines() {
        let line = line?;
        let began = Instant::now();
        let response: Result<Value> = (|| match serde_json::from_str::<Request>(&line)? {
            Request::Open {
                directory,
                case,
                expires,
                model,
                model_sha256,
                calibration,
                calibration_sha256,
            } => {
                if session.is_some() {
                    Err("A session is already open".into())
                } else {
                    session = Some(Session::open(
                        Start::Fresh,
                        directory,
                        case,
                        expires,
                        model,
                        model_sha256,
                        calibration,
                        calibration_sha256,
                    )?);
                    session.as_ref().ok_or("No session")?.status()
                }
            }
            Request::Resume {
                directory,
                case,
                expires,
                model,
                model_sha256,
                calibration,
                calibration_sha256,
            } => {
                if session.is_some() {
                    Err("A session is already open".into())
                } else {
                    session = Some(Session::open(
                        Start::Restore,
                        directory,
                        case,
                        expires,
                        model,
                        model_sha256,
                        calibration,
                        calibration_sha256,
                    )?);
                    session.as_ref().ok_or("No session")?.status()
                }
            }
            Request::Tick {
                event_id,
                phase,
                feedback_q24,
                receipt_digest,
            } => session.as_mut().ok_or("No session")?.tick(
                &event_id,
                phase,
                feedback_q24,
                &receipt_digest,
            ),
            Request::Forecast {
                feedback_q24,
                branch,
            } => session
                .as_mut()
                .ok_or("No session")?
                .forecast(feedback_q24, &branch),
            Request::Status => session.as_ref().ok_or("No session")?.status(),
            Request::Close => {
                let result = session.as_ref().ok_or("No session")?.status()?;
                session = None;
                Ok(result)
            }
        })();
        let physical_micros = began.elapsed().as_micros() as u64;
        let envelope = match response {
            Ok(value) => {
                json!({"ok":true,"result":value,"physical_receipt_processing_micros":physical_micros})
            }
            Err(error) => {
                json!({"ok":false,"error":error.to_string(),"physical_receipt_processing_micros":physical_micros})
            }
        };
        writeln!(stdout, "{envelope}")?;
        stdout.flush()?;
    }
    Ok(())
}
