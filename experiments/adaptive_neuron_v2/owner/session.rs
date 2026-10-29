//! Original owner, trained spiking state, durable stopping, and resource settlement.
use crate::credit::{Account, AccountState};
use crate::decision::{Action, Boundary, ReadoutKind};
use crate::events::{self, Event, Ledger, Observation};
use crate::original_owner::AgentdNeuronOwner;
use crate::port::{self, Context, Model, Policy, State};
use crate::{Result, profile};
use codex_hepta_neuron::{AnchorWitnessStore, FileAnchorWitnessStore, JournalScope, NeuronRuntime};
use codex_hepta_types::{Digest32, StableId};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OpenRequest {
    pub case: String,
    pub organ: String,
    pub expires: u64,
    pub context: Context,
    pub budget: f64,
    pub expected_account_sequence: usize,
    pub model: PathBuf,
    pub model_sha256: String,
    pub calibration: PathBuf,
    pub calibration_sha256: String,
    pub policy: Policy,
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
    initial: AccountState,
    account: Account,
    budget: f64,
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
    let b = fs::read(path)?;
    if Digest32::of_bytes(&b).to_string() != digest {
        return Err("Frozen artifact digest mismatch".into());
    }
    Ok(b)
}

impl Session {
    pub fn open(run_root: &Path, request: OpenRequest, mode: Mode) -> Result<(Self, Value)> {
        let started = Instant::now();
        let restore = matches!(mode, Mode::Restore);
        if request.case.is_empty()
            || request.case.contains("..")
            || !request
                .case
                .chars()
                .all(|x| x.is_ascii_alphanumeric() || matches!(x, '.' | '-' | '_'))
            || ![3.0, 7.0].contains(&request.budget)
        {
            return Err("Invalid case or load budget".into());
        }
        request.context.validate()?;
        let root = run_root.join(&request.case);
        let bytes = checked(&request.model, &request.model_sha256)?;
        let model: Model = serde_json::from_slice(&bytes)?;
        model.validate()?;
        let calibration_raw = checked(&request.calibration, &request.calibration_sha256)?;
        let calibration: Value = serde_json::from_slice(&calibration_raw)?;
        if calibration["schema"] != "hepta.adaptive-neuron.numeric-domain-proof.v2"
            || calibration["model_sha256"] != request.model_sha256
            || calibration["confidence_target"] != "validated_numeric_domain_contract"
            || calibration["semantic_quality_qualification"] != false
            || calibration["proof_kind"] != "algebraic_bounds_and_per_request_checks"
        {
            return Err("Numeric-domain contract mismatch".into());
        }
        if (restore || request.expected_account_sequence != 0)
            && !run_root
                .join(format!("organ.{}.jsonl", request.organ))
                .exists()
        {
            return Err("Missing historical organ account".into());
        }
        let account = Account::load(run_root, &request.organ, model.credit.clone())?;
        let initial: AccountState = if restore {
            let value: Value = serde_json::from_slice(&fs::read(root.join("IDENTITY.json"))?)?;
            serde_json::from_value(value["initial_account"].clone())?
        } else {
            account.state.clone()
        };
        account.verify_initial(&request.case, &initial)?;
        if initial.sequence != request.expected_account_sequence {
            return Err("Account sequence differs from expected organ episode".into());
        }
        if initial.balance < model.credit.quote {
            return Err("Insufficient credit for an admitted task".into());
        }
        let price = initial.used_price(request.policy.credit, &model.credit);
        let boundary = Boundary::build(
            request.context.reliability(),
            request.context.cost() + price * model.credit.quote,
            if request.policy.readout == ReadoutKind::RawBeliefMyopic {
                2
            } else {
                request.context.deadline
            },
            model.grid_points,
        )?;
        let boundary_build_terms = boundary.build_terms;
        let mut bundle_bytes = bytes;
        bundle_bytes.extend(serde_json::to_vec(&request.policy)?);
        bundle_bytes.extend(serde_json::to_vec(&request.context)?);
        bundle_bytes.extend(serde_json::to_vec(&initial)?);
        bundle_bytes.extend(request.budget.to_bits().to_be_bytes());
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
            objective_digest: Digest32::of_bytes(
                b"adaptive-neuron.bernoulli-stopping-resource-credit.v2",
            ),
        };
        let identity = json!({"schema":"hepta.adaptive-neuron.owner-identity.v2","case":request.case,"organ":request.organ,"expires":request.expires,"context":request.context,"budget":request.budget,"expected_account_sequence":request.expected_account_sequence,"policy":request.policy,"initial_account":initial,"model_sha256":request.model_sha256,"calibration_sha256":request.calibration_sha256,"binary_sha256":binary.to_string(),"bundle_sha256":bundle.to_string(),"native_config_digest":native.digest()?.to_string(),"owner_authority":"DENY_ALL"});
        if restore
            && serde_json::from_slice::<Value>(&fs::read(root.join("IDENTITY.json"))?)? != identity
        {
            return Err("Cold recovery identity mismatch".into());
        }
        account.reserve(&request.case, restore)?;
        let (runtime, ledger, replay_steps) = match mode {
            Mode::Fresh => {
                fs::create_dir(&root)?;
                let witness = FileAnchorWitnessStore::open(
                    file(&root.join("owner.witness"), true)?,
                    scope,
                    native.generation,
                    256,
                )?;
                let runtime = NeuronRuntime::bootstrap(
                    file(&root.join("owner.journal"), true)?,
                    native.clone(),
                    scope,
                    64,
                    config.clone(),
                    witness,
                )?;
                let ledger = Ledger::create(&root.join("events.jsonl"), State::initial(&initial))?;
                let mut f = OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(root.join("IDENTITY.json"))?;
                f.write_all(&serde_json::to_vec_pretty(&identity)?)?;
                f.sync_all()?;
                File::open(&root)?.sync_all()?;
                (runtime, ledger, 0)
            }
            Mode::Restore => {
                let witness = FileAnchorWitnessStore::open(
                    file(&root.join("owner.witness"), false)?,
                    scope,
                    native.generation,
                    256,
                )?;
                let anchor = witness
                    .current()?
                    .ok_or("Cold recovery requires committed prefix")?;
                let ledger = Ledger::restore(
                    &root.join("events.jsonl"),
                    &native,
                    &config,
                    scope,
                    &subject,
                    &model,
                    &request.context,
                    &request.policy,
                    &boundary,
                    &initial,
                    price,
                    Some(anchor),
                )?;
                let count = ledger.len();
                let runtime = NeuronRuntime::recover(
                    file(&root.join("owner.journal"), false)?,
                    native.clone(),
                    scope,
                    64,
                    config.clone(),
                    anchor,
                    witness,
                )?;
                (runtime, ledger, count)
            }
        };
        let state = ledger.state.clone();
        let replay_cells = state.cell_updates;
        let replay_spikes = state.spikes;
        let replay_query_terms = 2 * replay_steps.saturating_sub(usize::from(
            state.neural.elapsed == request.context.deadline,
        ));
        let port = port::Port {
            config,
            model,
            context: request.context,
            policy: request.policy,
            state,
            price,
            boundary,
            last: None,
        };
        let account_records = account.validated_records();
        let settled = account.settlement(&request.case)?.is_some();
        let session = Self {
            owner: AgentdNeuronOwner::new(runtime, port),
            scope,
            subject,
            root,
            ledger,
            initial,
            account,
            budget: request.budget,
            poisoned: false,
        };
        let receipt = json!({"status":session.status()?,"original_journal_replay_steps":replay_steps,"event_validation_kernel_steps":replay_steps,"event_validation_readout_calls":replay_steps,"event_validation_snn_cell_updates":replay_cells,"event_validation_spikes":replay_spikes,"event_validation_bellman_terms":replay_query_terms ,"boundary_build_terms":boundary_build_terms,"account_validation_native_credit_calls":account_records,"profile_weight_scalars_validated":65,"settled":settled,"open_restore_micros":started.elapsed().as_micros() as u64});
        Ok((session, receipt))
    }

    pub fn status(&self) -> Result<Value> {
        let anchor = self.owner.runtime().current_anchor()?;
        Ok(
            json!({"sequence":anchor.map_or(0,|a|a.sequence),"checkpoint":anchor.map_or(Digest32::ZERO,|a|a.checkpoint_digest).to_string(),"durable_event_count":self.ledger.len(),"terminal":self.ledger.terminal(),"host_poisoned":self.poisoned,"initial_account":self.initial,"current_neural_credit_state":self.ledger.state,"settled":self.account.settlement(self.subject.as_str())?.is_some(),"owner_authority":"DENY_ALL"}),
        )
    }

    pub fn observe(&mut self, observation: Observation) -> Result<Value> {
        if self.poisoned {
            return Err("Unacknowledged owner transition requires reconciliation".into());
        }
        if let Some(out) = self.ledger.lookup(&observation)? {
            return Ok(out);
        }
        self.ledger.validate_next(&observation)?;
        let before = self.owner.runtime().current_anchor()?;
        let port = self.owner.inference_control_mut();
        let input = events::input(
            &self.subject,
            self.scope,
            before,
            &port.context,
            port.price,
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
            .ok_or("Missing trained readout")?;
        let eligibility = self
            .owner
            .runtime()
            .current_eligibility_sample()?
            .ok_or("Missing owner eligibility")?;
        let r = &output.tick.resource_receipt;
        let terminal = output.tick.abstain || readout.action != Action::Continue;
        let result = json!({"sequence":before.map_or(1,|a|a.sequence+1),"event_digest":event_digest.to_string(),"checkpoint_before":output.tick.checkpoint_before.to_string(),"checkpoint_after":output.tick.checkpoint_after.to_string(),"activation_q24":output.signal.signals_q24,"eligibility_q24":eligibility.eligibility_q24(),"readout":readout,"native_abstain":output.tick.abstain,"terminal":terminal,"owner_authority":"DENY_ALL","confidence_ppm":output.tick.confidence_ppm,"ood_ppm":output.tick.ood_ppm,"duplicate_event_ignored":false,"native_transition_executed":true,"actual_model_calls":1,"actual_bellman_terms":readout.bellman_query_terms,"actual_snn_cell_updates":readout.actual_snn_cell_updates,"actual_spikes":readout.spikes,"actual_input_multiply_accumulates":readout.input_multiply_accumulates,"actual_readout_multiply_accumulates":readout.readout_multiply_accumulates,"actual_resource_work":readout.actual_work,"execution_micros":r.execution_micros,"transient_allocation_bytes":r.transient_allocation_bytes,"checkpoint_bytes":r.checkpoint_bytes,"journal_bytes_written":r.journal_bytes_written,"write_amplification_ppm":r.write_amplification_ppm,"queue_age_micros":r.queue_age_micros,"model_latency_micros":output.model_runtime.latency_micros,"model_resident_bytes":output.model_runtime.resident_bytes});
        self.ledger.append(Event {
            observation,
            output: result.clone(),
        })?;
        self.poisoned = false;
        Ok(result)
    }

    pub fn settle(&mut self, reward: f64, outcome_digest: String) -> Result<Value> {
        if self.poisoned || !self.ledger.terminal() {
            return Err("Only a committed terminal task can settle credit".into());
        }
        let outcome: Digest32 = outcome_digest.parse()?;
        if outcome.is_zero() {
            return Err("Outcome evidence required".into());
        }
        let action = self.ledger.last_action()?;
        if (action == Action::Abstain && reward != 0.05)
            || (action != Action::Abstain && ![-1.0, 1.0].contains(&reward))
        {
            return Err("Terminal action and observed reward mismatch".into());
        }
        let checkpoint = self
            .owner
            .runtime()
            .current_anchor()?
            .ok_or("Missing committed prefix")?
            .checkpoint_digest
            .to_string();
        let support=Digest32::of_bytes(&serde_json::to_vec(&json!({"case":self.subject.as_str(),"checkpoint":checkpoint,"reward":reward,"outcome_digest":outcome_digest}))?).to_string();
        let result = self.account.settle(
            self.subject.as_str(),
            &self.initial,
            self.ledger.state.work,
            self.budget,
            reward,
            &support,
            &checkpoint,
        )?;
        let path = self.root.join("SETTLEMENT.json");
        let record = json!({"outcome_digest":outcome_digest,"reward":reward,"support_digest":support,"account_record":result["record"]});
        if path.exists() {
            if serde_json::from_slice::<Value>(&fs::read(path)?)? != record {
                return Err("Settlement record conflict".into());
            }
        } else {
            let mut f = OpenOptions::new().write(true).create_new(true).open(path)?;
            f.write_all(&serde_json::to_vec_pretty(&record)?)?;
            f.sync_all()?;
            File::open(&self.root)?.sync_all()?;
        }
        Ok(result)
    }
}
