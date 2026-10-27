//! Durable, checkpoint-bound host event identity; no production authority.
use std::collections::BTreeMap;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::path::Path;

use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_neuron::SparseTick;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use serde_json::Value;

use crate::port;
use crate::Result;
use crate::Q;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Event {
    pub event_id: String,
    pub phase: i64,
    pub feedback_q24: i64,
    pub receipt_digest: String,
    pub output: Value,
}

pub struct Ledger {
    entries: BTreeMap<String, Event>,
    file: File,
}

pub fn input(
    subject: &StableId,
    scope: JournalScope,
    previous: Option<JournalAnchor>,
    eligibility: &[i64],
    event_id: &str,
    phase: i64,
    feedback: i64,
    receipt: Digest32,
) -> Result<NeuronTickInputV1> {
    StableId::new(event_id)?;
    if receipt.is_zero() {
        return Err("Readback/evidence digest required".into());
    }
    let sequence = previous.map_or(1, |anchor| anchor.sequence + 1);
    let mut features = vec![phase, feedback];
    features.extend(eligibility);
    let mut evidence = b"hepta.continuation.event-evidence.v1".to_vec();
    evidence.extend_from_slice(&(event_id.len() as u64).to_be_bytes());
    evidence.extend_from_slice(event_id.as_bytes());
    evidence.extend_from_slice(receipt.as_array());
    Ok(NeuronTickInputV1 {
        tick_id: StableId::new(format!("{}.tick.{sequence}", subject.as_str()))?,
        subject_id: subject.clone(),
        logical_sequence: sequence,
        monotonic_time_micros: sequence * 1000,
        checkpoint_digest: previous.map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest),
        input_feature_digest: canonical_feature_vector_digest_v1(&features),
        feature_vector_q24: features,
        objective_digest: scope.objective_digest,
        ndu_snapshot_digest: Digest32::of_bytes(&evidence),
        body_generation: Some(1),
        modulator_digest: None,
    })
}

impl Ledger {
    pub fn create(path: &Path) -> Result<Self> {
        let file = OpenOptions::new()
            .create_new(true)
            .append(true)
            .open(path)?;
        file.sync_all()?;
        Ok(Self {
            entries: BTreeMap::new(),
            file,
        })
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn lookup(
        &self,
        id: &str,
        phase: i64,
        feedback: i64,
        receipt: &str,
    ) -> Result<Option<Value>> {
        let Some(event) = self.entries.get(id) else {
            return Ok(None);
        };
        if event.phase != phase || event.feedback_q24 != feedback || event.receipt_digest != receipt
        {
            return Err("Conflicting retry: committed event payload is immutable".into());
        }
        let mut output = event.output.clone();
        output["duplicate_event_ignored"] = json!(true);
        output["native_transition_executed"] = json!(false);
        Ok(Some(output))
    }

    // Ack follows append+fsync. A failed append poisons the live host; a native
    // commit without a complete ledger record fails closed on the next restore.
    pub fn append(&mut self, event: Event) -> Result<()> {
        if self.entries.contains_key(&event.event_id) {
            return Err("Duplicate ledger identity".into());
        }
        let mut raw = serde_json::to_vec(&event)?;
        raw.push(b'\n');
        self.file.write_all(&raw)?;
        self.file.sync_all()?;
        self.entries.insert(event.event_id.clone(), event);
        Ok(())
    }

    pub fn restore(
        path: &Path,
        native: &SparseConfig,
        config: &NeuronRuntimeConfigV1,
        scope: JournalScope,
        subject: &StableId,
        model: &port::Model,
        anchor: Option<JournalAnchor>,
    ) -> Result<Self> {
        let mut previous: Option<SparseCheckpoint> = None;
        let mut entries = BTreeMap::new();
        for line in BufReader::new(File::open(path)?).split(b'\n') {
            let event: Event = serde_json::from_slice(&line?)?;
            if entries.contains_key(&event.event_id) {
                return Err("Duplicate event in durable ledger".into());
            }
            let before = previous
                .as_ref()
                .map_or_else(|| vec![0; 10], |state| state.eligibility_q24().to_vec());
            let prior = previous.as_ref().map(|state| JournalAnchor {
                sequence: state.sequence(),
                checkpoint_digest: state.digest(),
            });
            let request = input(
                subject,
                scope,
                prior,
                &before,
                &event.event_id,
                event.phase,
                event.feedback_q24,
                event.receipt_digest.parse()?,
            )?;
            let drive = port::encode(event.phase, event.feedback_q24)?;
            let mut body = b"hepta.neuron.body-binding.v1".to_vec();
            body.extend_from_slice(config.head_digest.as_array());
            body.extend_from_slice(&config.generation.get().to_be_bytes());
            body.extend_from_slice(&1_u64.to_be_bytes());
            let tick = SparseTick {
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
            let (next, signal) = sparse_tick(native, &tick, previous.as_ref())?;
            let logit = model.weights[0]
                + before
                    .iter()
                    .zip(&model.weights[1..])
                    .map(|(value, weight)| *value as f64 / Q as f64 * weight)
                    .sum::<f64>();
            let expired = next.sequence() > config.calibration.expires_after_sequence
                || next.sequence() < config.calibration.valid_from_sequence;
            let checkpoint_bytes = next.bounded_encoded_bytes() as u64;
            let journal_bytes = 304 + 16 * config.state_width as u64;
            let amplification = (journal_bytes * 1_000_000).div_ceil(checkpoint_bytes);
            let measured = |key: &str| -> Result<u64> {
                event.output[key]
                    .as_u64()
                    .ok_or_else(|| format!("Missing physical receipt: {key}").into())
            };
            let abstain = expired
                || signal.active_fraction_ppm < config.calibration.minimum_active_ppm
                || signal.active_fraction_ppm > config.calibration.maximum_active_ppm
                || signal.projection_count > config.calibration.maximum_projection_count
                || measured("execution_micros")? > config.resource_envelope.p99_latency_micros
                || measured("transient_allocation_bytes")?
                    > config.resource_envelope.transient_allocation_bytes
                || checkpoint_bytes > config.resource_envelope.checkpoint_bytes
                || amplification > config.resource_envelope.write_amplification_ppm as u64;
            let expected = json!({"event_id":event.event_id,"phase":event.phase,"feedback_q24":event.feedback_q24,
                "sequence":next.sequence(),"evidence_digest":event.receipt_digest,
                "bound_event_evidence_digest":request.ndu_snapshot_digest.to_string(),
                "checkpoint_before":request.checkpoint_digest.to_string(),"checkpoint_after":next.digest().to_string(),
                "activation_q24":signal.activation_q24,"eligibility_before_q24":before,
                "eligibility_after_q24":next.eligibility_q24(),"proposed_repair":logit>=0.0,
                "confidence_ppm":if expired {0} else {1_000_000},"ood_ppm":if expired {1_000_000} else {0},
                "native_abstain":abstain,"checkpoint_bytes":checkpoint_bytes,"journal_bytes_written":journal_bytes,
                "write_amplification_ppm":amplification,
                "owner_authority":"DENY_ALL","duplicate_event_ignored":false,"native_transition_executed":true});
            for (key, value) in expected.as_object().ok_or("Expected object")? {
                if event.output.get(key) != Some(value) {
                    return Err(format!("Ledger checkpoint binding mismatch: {key}").into());
                }
            }
            if event.output["readout_logit"]
                .as_f64()
                .is_none_or(|value| (value - logit).abs() > 1e-12)
            {
                return Err("Ledger learned readout mismatch".into());
            }
            entries.insert(event.event_id.clone(), event);
            previous = Some(next);
        }
        let reconstructed = previous.map(|state| JournalAnchor {
            sequence: state.sequence(),
            checkpoint_digest: state.digest(),
        });
        if reconstructed != anchor {
            return Err("Durable event ledger differs from native witness frontier".into());
        }
        Ok(Self {
            entries,
            file: OpenOptions::new().append(true).open(path)?,
        })
    }
}
