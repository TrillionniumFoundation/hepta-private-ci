//! Original-kernel replay checks every persisted action and state binding.
use crate::Result;
use crate::decision;
use crate::model::Features;
use crate::model::Profile;
use crate::model::Stage;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseTick;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub event_id: String,
    pub step: u64,
    pub checkpoint: String,
    pub features: Features,
    pub evidence_digest: String,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub observation: Observation,
    pub output: Value,
}
pub struct Ledger {
    pub events: Vec<Event>,
    pub index: BTreeMap<String, usize>,
    file: File,
}

pub fn input(
    profile: &Profile,
    subject: &StableId,
    scope: JournalScope,
    prior: Option<JournalAnchor>,
    o: &Observation,
) -> Result<NeuronTickInputV1> {
    let step = prior.map_or(1, |p| p.sequence + 1);
    if o.step != step
        || o.step > profile.maximum_ticks
        || o.checkpoint
            != prior
                .map_or(Digest32::ZERO, |p| p.checkpoint_digest)
                .to_string()
        || o.evidence_digest.parse::<Digest32>()?.is_zero()
    {
        return Err("Sequence, checkpoint or evidence mismatch".into());
    }
    StableId::new(&o.event_id)?;
    let x = profile.feature_vector(&o.features)?;
    Ok(NeuronTickInputV1 {
        tick_id: StableId::new(format!("{}.tick.{step}", subject.as_str()))?,
        subject_id: subject.clone(),
        logical_sequence: step,
        monotonic_time_micros: step
            .checked_mul(profile.tick_micros)
            .ok_or("Clock overflow")?,
        checkpoint_digest: prior.map_or(Digest32::ZERO, |p| p.checkpoint_digest),
        input_feature_digest: canonical_feature_vector_digest_v1(&x),
        feature_vector_q24: x,
        objective_digest: scope.objective_digest,
        ndu_snapshot_digest: Digest32::of_bytes(&serde_json::to_vec(o)?),
        body_generation: Some(1),
        modulator_digest: None,
    })
}
pub fn kernel_input(
    config: &NeuronRuntimeConfigV1,
    scope: JournalScope,
    request: &NeuronTickInputV1,
    drive: Vec<i64>,
) -> Result<SparseTick> {
    let mut body = b"hepta.neuron.body-binding.v1".to_vec();
    body.extend_from_slice(config.head_digest.as_array());
    body.extend_from_slice(&config.generation.get().to_be_bytes());
    body.extend_from_slice(&1_u64.to_be_bytes());
    Ok(SparseTick {
        scope_digest: scope.scope_digest,
        objective_digest: scope.objective_digest,
        ndu_digest: request.ndu_snapshot_digest,
        body_digest: Digest32::of_bytes(&body),
        input_digest: request.semantic_digest()?,
        sequence: request.logical_sequence,
        monotonic_micros: request.monotonic_time_micros,
        prediction_q24: drive.clone(),
        drive_q24: drive,
    })
}
impl Ledger {
    pub fn fresh(path: &Path) -> Result<Self> {
        let file = OpenOptions::new()
            .create_new(true)
            .append(true)
            .open(path)?;
        file.sync_all()?;
        Ok(Self {
            events: vec![],
            index: BTreeMap::new(),
            file,
        })
    }
    pub fn terminal(&self) -> bool {
        self.events
            .last()
            .is_some_and(|e| e.output["terminal"] == true)
    }
    pub fn lookup(&self, o: &Observation) -> Result<Option<Value>> {
        let Some(index) = self.index.get(&o.event_id) else {
            return Ok(None);
        };
        if self.events[*index].observation != *o {
            return Err("Conflicting exact-event retry".into());
        }
        let mut value = self.events[*index].output.clone();
        value["duplicate_event_ignored"] = json!(true);
        value["native_transition_executed"] = json!(false);
        value["actual_model_calls"] = json!(0);
        value["actual_ndu_calls"] = json!(0);
        Ok(Some(value))
    }
    pub fn append(&mut self, event: Event) -> Result<()> {
        if self.terminal() || self.index.contains_key(&event.observation.event_id) {
            return Err("Terminal or duplicate append".into());
        }
        let mut bytes = serde_json::to_vec(&event)?;
        bytes.push(b'\n');
        self.file.write_all(&bytes)?;
        self.file.sync_all()?;
        self.index
            .insert(event.observation.event_id.clone(), self.events.len());
        self.events.push(event);
        Ok(())
    }
    pub fn restore(
        path: &Path,
        profile: &Profile,
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
        subject: &StableId,
        seed: u64,
        anchor: Option<JournalAnchor>,
    ) -> Result<Self> {
        let bytes = std::fs::read(path)?;
        if !bytes.is_empty() && bytes.last() != Some(&b'\n') {
            return Err("Truncated continuous event ledger".into());
        }
        let mut ledger = Self {
            events: vec![],
            index: BTreeMap::new(),
            file: OpenOptions::new().append(true).open(path)?,
        };
        let mut prior: Option<SparseCheckpoint> = None;
        let native = profile.native(config.model_manifest_digest)?;
        for line in bytes.split(|b| *b == b'\n').filter(|x| !x.is_empty()) {
            let event: Event = serde_json::from_slice(line)?;
            let mut payload = event.output.clone();
            let saved = payload
                .as_object_mut()
                .ok_or("Malformed event output")?
                .remove("receipt_digest")
                .ok_or("Missing receipt digest")?;
            if saved != json!(Digest32::of_bytes(&serde_json::to_vec(&payload)?).to_string()) {
                return Err("Receipt hash mismatch".into());
            }
            if ledger.terminal() || ledger.index.contains_key(&event.observation.event_id) {
                return Err("Event after terminal or duplicate".into());
            }
            let before = prior.as_ref().map(|p| JournalAnchor {
                sequence: p.sequence(),
                checkpoint_digest: p.digest(),
            });
            let request = input(profile, subject, scope, before, &event.observation)?;
            let drive = profile.encode(&request.feature_vector_q24)?;
            let sparse = kernel_input(config, scope, &request, drive)?;
            let (next, signal) = sparse_tick(&native, &sparse, prior.as_ref())?;
            let readout = decision::decide(
                profile,
                &signal.activation_q24,
                event.observation.features.continuous.risk_q24,
                next.digest(),
            )?;
            let number = |key: &str| -> Result<u64> {
                event.output[key]
                    .as_u64()
                    .ok_or_else(|| format!("Missing receipt {key}").into())
            };
            let encoded = next.bounded_encoded_bytes() as u64;
            let written = 304 + 16 * config.state_width as u64;
            let amplification = (written * 1_000_000).div_ceil(encoded);
            let expired = next.sequence() > config.calibration.expires_after_sequence;
            let abstain = expired
                || signal.projection_count > config.calibration.maximum_projection_count
                || number("execution_micros")? > config.resource_envelope.p99_latency_micros
                || number("transient_allocation_bytes")?
                    > config.resource_envelope.transient_allocation_bytes
                || encoded > config.resource_envelope.checkpoint_bytes
                || amplification > u64::from(config.resource_envelope.write_amplification_ppm);
            let expected = json!({"case":subject.as_str(),"seed":seed,"arm":profile.arm_id,
                "profile_sha256":config.model_manifest_digest.to_string(),"profile_masks":[profile.use_margin,profile.use_risk,profile.use_flow],
                "step":next.sequence(),"event_kind":"continuous_readout",
                "checkpoint_before":request.checkpoint_digest.to_string(),"checkpoint_after":next.digest().to_string(),
                "input_feature_digest":request.input_feature_digest.to_string(),"event_digest":request.ndu_snapshot_digest.to_string(),
                "activation_q24":signal.activation_q24,"eligibility_q24":next.eligibility_q24(),
                "readout":readout,"native_abstain":abstain,
                "effective_action":if abstain {"stop"}else if profile.stage==Stage::Transform {"observe"}else{&readout.action},
                "terminal":abstain||(profile.stage==Stage::Act&&readout.action=="stop"),
                "owner_authority":"DENY_ALL","checkpoint_bytes":encoded,
                "journal_bytes_written":written,"write_amplification_ppm":amplification,
                "duplicate_event_ignored":false,"native_transition_executed":true,"actual_model_calls":1,"actual_ndu_calls":1});
            for (key, value) in expected.as_object().ok_or("Expected replay object")? {
                if event.output.get(key) != Some(value) {
                    return Err(format!("Persisted action/state mismatch: {key}").into());
                }
            }
            ledger
                .index
                .insert(event.observation.event_id.clone(), ledger.events.len());
            ledger.events.push(event);
            prior = Some(next);
        }
        let reconstructed = prior.map(|p| JournalAnchor {
            sequence: p.sequence(),
            checkpoint_digest: p.digest(),
        });
        if reconstructed != anchor {
            return Err("Event/witness frontier mismatch".into());
        }
        Ok(ledger)
    }
}
