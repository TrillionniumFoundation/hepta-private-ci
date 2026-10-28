//! Strict bounded requests and domain-separated score/decision bindings.
use crate::Result;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeSet;

pub const Q: i64 = 1 << 24;
pub const MAX_ROWS: usize = 4096;
pub const MAX_BYTES: usize = 16 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(tag = "command", deny_unknown_fields)]
pub enum Request {
    Identity {},
    DecideBatch { rows: Vec<Row> },
    Shutdown {},
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Row {
    pub row_id: String,
    pub model_sha256: String,
    pub objective_sha256: String,
    pub observation_sha256: String,
    pub state_sha256: String,
    pub scores_q24: [i64; 3],
}

impl Row {
    pub fn validate(&self) -> Result<()> {
        if self.row_id.is_empty()
            || self.row_id.len() > 256
            || !self.row_id.bytes().all(|v| v.is_ascii_graphic())
        {
            return Err("Invalid bounded row identifier".into());
        }
        for value in [
            &self.model_sha256,
            &self.objective_sha256,
            &self.observation_sha256,
            &self.state_sha256,
        ] {
            if value.parse::<Digest32>()?.is_zero() {
                return Err("Zero provenance digest".into());
            }
        }
        if self
            .scores_q24
            .iter()
            .any(|v| !(-8 * Q..=8 * Q).contains(v))
            || self.scores_q24[2] != 0
        {
            return Err("Scores require bounded Q24 values and exact zero stop payoff".into());
        }
        Ok(())
    }

    pub fn support(&self, binary: Digest32) -> Result<Digest32> {
        digest(&json!({
            "schema": "hepta.boundary-policy.score-support.v1",
            "native_binary_sha256": binary.to_string(),
            "row": self,
        }))
    }
}

pub fn validate_batch(rows: &[Row]) -> Result<()> {
    if rows.is_empty() || rows.len() > MAX_ROWS {
        return Err("Score batch size limit".into());
    }
    let mut identifiers = BTreeSet::new();
    for row in rows {
        row.validate()?;
        if !identifiers.insert(&row.row_id) {
            return Err("Duplicate row identifier in score batch".into());
        }
    }
    Ok(())
}

pub fn digest(value: &Value) -> Result<Digest32> {
    // serde_json's default map is ordered; all receipt inputs are integers or ASCII.
    Ok(Digest32::of_bytes(&serde_json::to_vec(value)?))
}
