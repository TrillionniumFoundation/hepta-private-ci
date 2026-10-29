//! Bounded embedding-only frames: no keys, values or owner authority cross here.

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_types::Digest32;
use serde::{Deserialize, Serialize};

pub(super) const MAX_REQUEST: usize = 16384;
pub(super) const MAX_RESPONSE: usize = 32768;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Ready {
    pub schema: String,
    pub encoder_digest: ContractDigestV1,
    pub worker_digest: ContractDigestV1,
    pub source_digest: ContractDigestV1,
    pub dimension: usize,
    pub native_batch: usize,
    pub max_request: usize,
    pub max_response: usize,
    pub base_bytes: usize,
}

#[derive(Serialize)]
#[serde(deny_unknown_fields)]
struct Request<'a> {
    schema: &'static str,
    request_id: u64,
    text: &'a str,
    text_digest: ContractDigestV1,
    encoder_digest: ContractDigestV1,
}

pub(super) struct Bound {
    pub bytes: Vec<u8>,
    request_id: u64,
    text_digest: ContractDigestV1,
    encoder_digest: ContractDigestV1,
}
impl Bound {
    pub fn new(request_id: u64, text: &str, encoder_digest: ContractDigestV1) -> Result<Self, String> {
        if text.trim().is_empty() || text.len() > 8192 || request_id == 0 { return Err("encoder input bound".to_string()); }
        let text_digest = ContractDigestV1::from_digest(Digest32::of_bytes(text.as_bytes())).map_err(|error| error.to_string())?;
        let mut bytes = serde_json::to_vec(&Request { schema: "hepta.memory.inventory-encoder-request.v1", request_id, text, text_digest, encoder_digest })
            .map_err(|error| error.to_string())?;
        bytes.push(b'\n');
        if bytes.len() > MAX_REQUEST { return Err("encoder request frame bound".to_string()); }
        Ok(Self { bytes, request_id, text_digest, encoder_digest })
    }

    pub fn response(&self, bytes: &[u8]) -> Result<Response, String> {
        let response: Response = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        if response.schema != "hepta.memory.inventory-encoder-response.v1" || response.request_id != self.request_id
            || response.text_digest != self.text_digest || response.encoder_digest != self.encoder_digest
            || !(1..=128).contains(&response.tokens) || response.cpu_ns > 60_000_000_000 || response.wall_ns > 60_000_000_000
            || (response.truncated && !response.features.is_empty())
            || (!response.truncated && response.features.len() != 384)
            || response.features.iter().any(|value| !value.is_finite())
        { return Err("encoder response binding, cost, shape or truncation bound".to_string()); }
        if !response.truncated {
            let squared: f32 = response.features.iter().map(|value| value * value).sum();
            if (squared - 1.0).abs() > 0.002 { return Err("encoder feature normalization differs".to_string()); }
        }
        Ok(response)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Response {
    schema: String,
    request_id: u64,
    text_digest: ContractDigestV1,
    encoder_digest: ContractDigestV1,
    pub features: Vec<f32>,
    pub truncated: bool,
    tokens: usize,
    pub cpu_ns: u64,
    pub wall_ns: u64,
}
