//! Causal evidence and reconstructed spiking/credit state bound to native checkpoints.
use crate::Result;
use crate::credit::AccountState;
use crate::decision::{Action, Boundary};
use crate::port::{self, Context, Model, Policy, Readout, State};
use codex_hepta_neuron::{
    JournalAnchor, JournalScope, NeuronRuntimeConfigV1, NeuronTickInputV1, SparseCheckpoint,
    SparseConfig, SparseTick, canonical_feature_vector_digest_v1, sparse_tick,
};
use codex_hepta_types::{Digest32, StableId};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;

#[derive(Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub event_id: String,
    pub value: i32,
    pub elapsed: usize,
    pub evidence_digest: String,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub observation: Observation,
    pub output: Value,
}

pub struct Ledger {
    entries: BTreeMap<String, Event>,
    order: Vec<String>,
    file: File,
    pub state: State,
}

pub fn input(
    subject: &StableId,
    scope: JournalScope,
    previous: Option<JournalAnchor>,
    context: &Context,
    price: f64,
    observation: &Observation,
) -> Result<NeuronTickInputV1> {
    StableId::new(&observation.event_id)?;
    let evidence: Digest32 = observation.evidence_digest.parse()?;
    if evidence.is_zero() {
        return Err("Source-bound causal evidence required".into());
    }
    let sequence = previous.map_or(1, |a| a.sequence + 1);
    let features = port::features(context, observation.value, observation.elapsed, price)?;
    let mut preimage = b"hepta.adaptive-neuron.observation.v2".to_vec();
    preimage.extend(serde_json::to_vec(observation)?);
    Ok(NeuronTickInputV1 {
        tick_id: StableId::new(format!("{}.tick.{sequence}", subject.as_str()))?,
        subject_id: subject.clone(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence.checked_mul(1_000_000).ok_or("Time overflow")?,
        checkpoint_digest: previous.map_or(Digest32::ZERO, |a| a.checkpoint_digest),
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: scope.objective_digest,
        ndu_snapshot_digest: Digest32::of_bytes(&preimage),
        body_generation: Some(1),
        modulator_digest: None,
    })
}

impl Ledger {
    pub fn create(path: &Path, initial: State) -> Result<Self> {
        let file = OpenOptions::new()
            .create_new(true)
            .append(true)
            .open(path)?;
        file.sync_all()?;
        Ok(Self {
            entries: BTreeMap::new(),
            order: vec![],
            file,
            state: initial,
        })
    }
    pub fn len(&self) -> usize {
        self.order.len()
    }
    pub fn terminal(&self) -> bool {
        self.order
            .last()
            .is_some_and(|key| self.entries[key].output["terminal"] == true)
    }
    pub fn last_action(&self) -> Result<Action> {
        let key = self.order.last().ok_or("Missing terminal observation")?;
        if self.entries[key].output["native_abstain"] == true {
            return Ok(Action::Abstain);
        }
        let readout: Readout = serde_json::from_value(self.entries[key].output["readout"].clone())?;
        Ok(readout.action)
    }
    pub fn validate_next(&self, observation: &Observation) -> Result<()> {
        if self.terminal() {
            return Err("Episode already stopped; no further native tick".into());
        }
        if observation.elapsed != self.order.len() + 1 {
            return Err("Causal observation elapsed count must increase by one".into());
        }
        Ok(())
    }
    pub fn lookup(&self, observation: &Observation) -> Result<Option<Value>> {
        let Some(event) = self.entries.get(&observation.event_id) else {
            return Ok(None);
        };
        if event.observation != *observation {
            return Err("Conflicting event retry".into());
        }
        let mut out = event.output.clone();
        out["duplicate_event_ignored"] = json!(true);
        out["native_transition_executed"] = json!(false);
        for field in [
            "actual_model_calls",
            "actual_bellman_terms",
            "actual_snn_cell_updates",
            "actual_spikes",
            "actual_input_multiply_accumulates",
            "actual_readout_multiply_accumulates",
        ] {
            out[field] = json!(0);
        }
        out["actual_resource_work"] = json!(0.0);
        Ok(Some(out))
    }
    pub fn append(&mut self, event: Event) -> Result<()> {
        self.validate_next(&event.observation)?;
        if self.entries.contains_key(&event.observation.event_id) {
            return Err("Duplicate durable event".into());
        }
        let readout: Readout = serde_json::from_value(event.output["readout"].clone())?;
        let mut raw = serde_json::to_vec(&event)?;
        raw.push(b'\n');
        self.file.write_all(&raw)?;
        self.file.sync_all()?;
        self.state = readout.state_after;
        self.order.push(event.observation.event_id.clone());
        self.entries
            .insert(event.observation.event_id.clone(), event);
        Ok(())
    }
    pub fn restore(
        path: &Path,
        native: &SparseConfig,
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
        subject: &StableId,
        model: &Model,
        context: &Context,
        policy: &Policy,
        boundary: &Boundary,
        initial: &AccountState,
        price: f64,
        anchor: Option<JournalAnchor>,
    ) -> Result<Self> {
        let bytes = std::fs::read(path)?;
        if !bytes.is_empty() && bytes.last() != Some(&b'\n') {
            return Err("Truncated event ledger".into());
        }
        let mut prior: Option<SparseCheckpoint> = None;
        let mut ledger = Self {
            entries: BTreeMap::new(),
            order: vec![],
            file: OpenOptions::new().append(true).open(path)?,
            state: State::initial(initial),
        };
        for line in BufReader::new(bytes.as_slice()).lines() {
            let event: Event = serde_json::from_str(&line?)?;
            ledger.validate_next(&event.observation)?;
            if ledger.entries.contains_key(&event.observation.event_id) {
                return Err("Duplicate durable event".into());
            }
            let before = prior.as_ref().map(|p| JournalAnchor {
                sequence: p.sequence(),
                checkpoint_digest: p.digest(),
            });
            let request = input(subject, scope, before, context, price, &event.observation)?;
            let readout = port::step(
                model,
                context,
                policy,
                boundary,
                &mut ledger.state,
                event.observation.value,
                event.observation.elapsed,
                price,
            )?;
            let drive = port::drive(&readout);
            let mut body = b"hepta.neuron.body-binding.v1".to_vec();
            body.extend_from_slice(config.head_digest.as_array());
            body.extend_from_slice(&config.generation.get().to_be_bytes());
            body.extend_from_slice(&1_u64.to_be_bytes());
            let sparse = SparseTick {
                scope_digest: scope.scope_digest,
                objective_digest: scope.objective_digest,
                ndu_digest: request.ndu_snapshot_digest,
                body_digest: Digest32::of_bytes(&body),
                input_digest: request.semantic_digest()?,
                sequence: request.logical_sequence,
                monotonic_micros: request.monotonic_time_micros,
                prediction_q24: drive.clone(),
                drive_q24: drive,
            };
            let (next, signal) = sparse_tick(native, &sparse, prior.as_ref())?;
            let encoded = next.bounded_encoded_bytes() as u64;
            let written = 304 + 16 * config.state_width as u64;
            let amplification = (written * 1_000_000).div_ceil(encoded);
            let measured = |key: &str| -> Result<u64> {
                event.output[key]
                    .as_u64()
                    .ok_or_else(|| format!("Missing receipt {key}").into())
            };
            let expired = next.sequence() > config.calibration.expires_after_sequence;
            let abstain = expired
                || signal.projection_count > config.calibration.maximum_projection_count
                || measured("execution_micros")? > config.resource_envelope.p99_latency_micros
                || measured("transient_allocation_bytes")?
                    > config.resource_envelope.transient_allocation_bytes
                || encoded > config.resource_envelope.checkpoint_bytes
                || amplification > u64::from(config.resource_envelope.write_amplification_ppm);
            let terminal = abstain || readout.action != Action::Continue;
            let expected = json!({"sequence":next.sequence(),"checkpoint_before":request.checkpoint_digest.to_string(),"checkpoint_after":next.digest().to_string(),"event_digest":request.ndu_snapshot_digest.to_string(),"activation_q24":signal.activation_q24,"eligibility_q24":next.eligibility_q24(),"readout":readout,"native_abstain":abstain,"terminal":terminal,"owner_authority":"DENY_ALL","confidence_ppm":if expired{0}else{1_000_000},"ood_ppm":if expired{1_000_000}else{0},"checkpoint_bytes":encoded,"journal_bytes_written":written,"write_amplification_ppm":amplification,"duplicate_event_ignored":false,"native_transition_executed":true,"actual_model_calls":1,"actual_bellman_terms":readout.bellman_query_terms,"actual_snn_cell_updates":readout.actual_snn_cell_updates,"actual_spikes":readout.spikes,"actual_input_multiply_accumulates":readout.input_multiply_accumulates,"actual_readout_multiply_accumulates":readout.readout_multiply_accumulates,"actual_resource_work":readout.actual_work});
            for (key, value) in expected.as_object().ok_or("Expected event")? {
                if event.output.get(key) != Some(value) {
                    return Err(format!(
                        "Event binding mismatch at {}: {key}; stored={}; recomputed={value}",
                        event.observation.elapsed,
                        event.output.get(key).unwrap_or(&Value::Null)
                    )
                    .into());
                }
            }
            ledger.order.push(event.observation.event_id.clone());
            ledger
                .entries
                .insert(event.observation.event_id.clone(), event);
            prior = Some(next);
        }
        if prior.map(|p| JournalAnchor {
            sequence: p.sequence(),
            checkpoint_digest: p.digest(),
        }) != anchor
        {
            return Err("Event ledger and witness frontier disagree".into());
        }
        Ok(ledger)
    }
}
