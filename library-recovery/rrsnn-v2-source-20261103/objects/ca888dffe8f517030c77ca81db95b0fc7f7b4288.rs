//! Strict transport for a complete sampled state and its already known inputs.
//! This is an unregistered, authority-free research format. It does not implement
//! Hepta's NeuronModelPort, authenticate inference, or sample the Brownian process.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub type Result<T> = std::result::Result<T, String>;
pub const MAX_BYTES: usize = 1_048_576;
pub const MAX_COMPONENTS: usize = 256;
const DOMAIN: &[u8] = b"rrsnn.offline.event-payload.v2\0";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PcgWords {
    pub state: String,
    pub inc: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PcgState {
    pub bit_generator: String,
    pub state: PcgWords,
    pub has_uint32: u8,
    pub uinteger: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Checkpoint {
    pub schema: String,
    pub time: f64,
    pub evidence: Vec<f64>,
    pub refractory_until: Vec<f64>,
    pub drift: Vec<f64>,
    pub sigma: Vec<f64>,
    pub threshold: Vec<f64>,
    pub reset: Vec<f64>,
    pub refractory: Vec<f64>,
    pub count: Vec<u64>,
    pub rng: Vec<PcgState>,
}

#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Parameters {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub drift: Option<Vec<f64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sigma: Option<Vec<f64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub threshold: Option<Vec<f64>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub kick: Option<Vec<f64>>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InputEvent {
    pub time: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parameters: Option<Parameters>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Emission {
    pub time: f64,
    pub component: usize,
    pub cause: String,
    pub evidence_before: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Fixture {
    pub schema: String,
    pub semantics: String,
    pub initial: Checkpoint,
    pub events_before_split: Vec<Emission>,
    pub checkpoint_at_split: Checkpoint,
    pub continuation: Vec<InputEvent>,
    pub expected_continuation_events: Vec<Emission>,
    pub expected_final: Checkpoint,
    pub numpy_version: String,
}

impl Checkpoint {
    pub fn validate(&self) -> Result<()> {
        let n = self.evidence.len();
        if self.schema != "rrsnn.exact-independent-checkpoint.v1"
            || !(1..=MAX_COMPONENTS).contains(&n)
            || !self.time.is_finite()
            || self.time < 0.0
        {
            return Err("unsupported checkpoint schema, width or clock".into());
        }
        for values in [
            &self.evidence,
            &self.refractory_until,
            &self.drift,
            &self.sigma,
            &self.threshold,
            &self.reset,
            &self.refractory,
        ] {
            if values.len() != n || values.iter().any(|v| !v.is_finite()) {
                return Err("nonfinite or mismatched physical state".into());
            }
        }
        if self.count.len() != n
            || self.rng.len() != n
            || self.count.iter().any(|v| *v > i64::MAX as u64)
        {
            return Err("invalid count or random-stream dimensions".into());
        }
        for i in 0..n {
            if self.sigma[i] < 0.0
                || self.refractory[i] <= 0.0
                || self.reset[i] >= self.threshold[i]
                || self.evidence[i] >= self.threshold[i]
                || self.refractory_until[i] < 0.0
                || self.refractory_until[i] > self.time + self.refractory[i] + 1e-12
                || (self.refractory_until[i] > self.time && self.evidence[i] != self.reset[i])
            {
                return Err("invalid physical state or refractory clock".into());
            }
            let rng = &self.rng[i];
            let state = rng
                .state
                .state
                .parse::<u128>()
                .map_err(|_| "invalid PCG state")?;
            let inc = rng
                .state
                .inc
                .parse::<u128>()
                .map_err(|_| "invalid PCG increment")?;
            if rng.bit_generator != "PCG64"
                || rng.has_uint32 > 1
                || inc % 2 != 1
                || state.to_string() != rng.state.state
                || inc.to_string() != rng.state.inc
            {
                return Err("noncanonical or unsupported complete PCG state".into());
            }
        }
        Ok(())
    }
}

pub fn validate_inputs(checkpoint: &Checkpoint, inputs: &[InputEvent]) -> Result<()> {
    if inputs.len() > 4096 {
        return Err("too many pending observations".into());
    }
    let mut last = checkpoint.time;
    for input in inputs {
        if !input.time.is_finite() || input.time < last {
            return Err("pending inputs move backwards in time".into());
        }
        last = input.time;
        if let Some(p) = &input.parameters {
            for values in [&p.drift, &p.sigma, &p.threshold, &p.kick]
                .into_iter()
                .flatten()
            {
                if values.len() != checkpoint.evidence.len()
                    || values.iter().any(|v| !v.is_finite())
                {
                    return Err("invalid pending parameter dimensions or values".into());
                }
            }
            if p.sigma.as_ref().is_some_and(|v| v.iter().any(|x| *x < 0.0))
                || p.threshold
                    .as_ref()
                    .is_some_and(|v| v.iter().zip(&checkpoint.reset).any(|(a, b)| a <= b))
            {
                return Err("invalid pending sigma or threshold".into());
            }
        }
    }
    Ok(())
}

fn validate_events(before: &Checkpoint, after: &Checkpoint, events: &[Emission]) -> Result<()> {
    if before.evidence.len() != after.evidence.len()
        || after.time < before.time
        || before.reset != after.reset
        || before.refractory != after.refractory
    {
        return Err("incompatible trajectory endpoints".into());
    }
    let mut counts = before.count.clone();
    let mut next_allowed = before.refractory_until.clone();
    let mut last = before.time;
    for event in events {
        let i = event.component;
        if i >= counts.len()
            || !event.time.is_finite()
            || !event.evidence_before.is_finite()
            || event.time < last
            || event.time > after.time
            || event.time + 1e-12 < next_allowed[i]
            || !matches!(event.cause.as_str(), "first_passage" | "input_or_parameter")
        {
            return Err("invalid event order, component or refractory separation".into());
        }
        counts[i] = counts[i].checked_add(1).ok_or("count overflow")?;
        next_allowed[i] = event.time + before.refractory[i];
        last = event.time;
    }
    if counts != after.count {
        return Err("events do not reconcile endpoint counts".into());
    }
    Ok(())
}

impl Fixture {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "rrsnn.exact-rollout-replay-fixture.v1" || self.numpy_version.is_empty() {
            return Err(
                "unsupported fixture schema or missing NumPy implementation version".into(),
            );
        }
        for state in [
            &self.initial,
            &self.checkpoint_at_split,
            &self.expected_final,
        ] {
            state.validate()?;
        }
        validate_events(
            &self.initial,
            &self.checkpoint_at_split,
            &self.events_before_split,
        )?;
        validate_events(
            &self.checkpoint_at_split,
            &self.expected_final,
            &self.expected_continuation_events,
        )?;
        validate_inputs(&self.checkpoint_at_split, &self.continuation)?;
        if self
            .continuation
            .last()
            .is_none_or(|e| e.time != self.expected_final.time)
        {
            return Err("continuation endpoint does not match final clock".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Context {
    pub upstream_source_commit: String,
    pub engine_source_sha256: String,
    pub model_artifact_sha256: Option<String>,
    pub numpy_version: String,
    pub instance_id: String,
    pub logical_sequence: u64,
    pub previous_payload_sha256: Option<String>,
}

fn is_hex(value: &str, length: usize) -> bool {
    value.len() == length
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        && value.bytes().any(|c| c != b'0')
}

impl Context {
    fn validate(&self) -> Result<()> {
        if !is_hex(&self.upstream_source_commit, 40)
            || !is_hex(&self.engine_source_sha256, 64)
            || self
                .model_artifact_sha256
                .as_ref()
                .is_some_and(|s| !is_hex(s, 64))
            || self
                .previous_payload_sha256
                .as_ref()
                .is_some_and(|s| !is_hex(s, 64))
            || self.logical_sequence == 0
            || ((self.logical_sequence == 1) != self.previous_payload_sha256.is_none())
            || self.numpy_version.is_empty()
            || self.instance_id.is_empty()
            || self.instance_id.len() > 128
            || !self
                .instance_id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._:-".contains(&c))
        {
            return Err("invalid offline context or checkpoint chain binding".into());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Payload {
    pub schema: String,
    pub context: Context,
    pub checkpoint: Checkpoint,
    pub pending_inputs: Vec<InputEvent>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Envelope {
    schema: String,
    canonical_payload_json: String,
    payload_sha256: String,
    evidence_scope: String,
    authority: String,
    official_runtime_receipt: Option<serde_json::Value>,
    production_activation_allowed: bool,
}

fn payload_digest(text: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(DOMAIN);
    digest.update(text.as_bytes());
    format!("{:x}", digest.finalize())
}

impl Payload {
    fn validate(&self) -> Result<()> {
        if self.schema != "rrsnn.offline.event-payload.v2" {
            return Err("wrong payload version".into());
        }
        self.context.validate()?;
        self.checkpoint.validate()?;
        validate_inputs(&self.checkpoint, &self.pending_inputs)
    }
}

impl Envelope {
    pub fn pack(
        checkpoint: Checkpoint,
        context: Context,
        pending_inputs: Vec<InputEvent>,
    ) -> Result<Self> {
        let payload = Payload {
            schema: "rrsnn.offline.event-payload.v2".into(),
            context,
            checkpoint,
            pending_inputs,
        };
        payload.validate()?;
        let text = serde_json::to_string(&payload).map_err(|e| e.to_string())?;
        if text.len() > MAX_BYTES {
            return Err("oversized checkpoint payload".into());
        }
        Ok(Self {
            schema: "rrsnn.offline.replay-envelope.v2".into(),
            payload_sha256: payload_digest(&text),
            canonical_payload_json: text,
            evidence_scope: "offline-engine-checkpoint; unregistered research schema".into(),
            authority: "none".into(),
            official_runtime_receipt: None,
            production_activation_allowed: false,
        })
    }

    pub fn unpack(&self) -> Result<Payload> {
        if self.schema != "rrsnn.offline.replay-envelope.v2"
            || self.authority != "none"
            || self.official_runtime_receipt.is_some()
            || self.production_activation_allowed
            || self.evidence_scope != "offline-engine-checkpoint; unregistered research schema"
            || self.canonical_payload_json.len() > MAX_BYTES
            || self.payload_sha256 != payload_digest(&self.canonical_payload_json)
        {
            return Err("invalid, altered or authority-bearing offline envelope".into());
        }
        let payload: Payload =
            serde_json::from_str(&self.canonical_payload_json).map_err(|e| e.to_string())?;
        payload.validate()?;
        Ok(payload)
    }
}
