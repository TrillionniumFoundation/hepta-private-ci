//! Research-only JSONL ingress. Cell state hashes bind external physics; they do not execute it.
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const Q: i64 = 1 << 24;
pub const LIMIT: usize = 1024;
pub const ACTIONS: [&str; 4] = ["STOP", "SKIP", "READ", "FIRE"];
pub const NUMERIC_CONTRACT: &str = "hepta.task.native-q24-residual.v1";

pub fn deployment_digest(model: Digest32) -> Digest32 {
    let mut bytes = b"hepta.task.deployment-model.v1".to_vec();
    bytes.extend_from_slice(model.as_array());
    bytes.extend_from_slice(NUMERIC_CONTRACT.as_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn digest(text: &str) -> Result<Digest32, String> {
    text.parse::<Digest32>().map_err(|error| error.to_string())
}
pub fn id(text: &str) -> Result<StableId, String> {
    StableId::new(text).map_err(|error| error.to_string())
}
pub fn marker(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}
pub fn quantize(value: f64) -> Result<i64, String> {
    if !value.is_finite() || value.abs() > 8.0 {
        return Err("nonfinite or outside native Q24 input envelope".into());
    }
    Ok((value * Q as f64).round() as i64)
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub numeric_contract: String,
    pub sequence: u64,
    pub monotonic_time_micros: u64,
    pub checkpoint_before: String,
    pub model_sha256: String,
    pub cell_snapshot_sha256: String,
    pub public_state_sha256: String,
    pub features: Vec<f64>,
    pub prior: [f64; 4],
    pub feasible: [bool; 4],
}

impl Request {
    pub fn packed(&self, width: usize) -> Result<Vec<i64>, String> {
        if self.numeric_contract != NUMERIC_CONTRACT
            || self.sequence == 0
            || self.sequence > LIMIT as u64
            || self.features.len() != width
            || !self.feasible[0]
        {
            return Err("invalid sequence, input width, or STOP mask".into());
        }
        for value in [
            &self.model_sha256,
            &self.cell_snapshot_sha256,
            &self.public_state_sha256,
        ] {
            if digest(value)?.is_zero() {
                return Err("empty identity".into());
            }
        }
        digest(&self.checkpoint_before)?;
        let mut values = self
            .features
            .iter()
            .map(|&value| quantize(value))
            .collect::<Result<Vec<_>, _>>()?;
        for (index, &value) in self.prior.iter().enumerate() {
            values.push(if self.feasible[index] {
                quantize(value)?
            } else {
                0
            });
        }
        values.extend(self.feasible.iter().map(|&value| if value { Q } else { 0 }));
        Ok(values)
    }

    pub fn evidence_digest(&self) -> Result<Digest32, String> {
        let bytes = serde_json::to_vec(self).map_err(|error| error.to_string())?;
        Ok(Digest32::of_bytes(&bytes))
    }
}
