//! Bounded research generation wire contract. No dispatch or authority is issued.
//! Float32 bit patterns preserve actual latent bytes across the Python boundary.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

pub const GENERATION_MAX_BYTES: usize = 256 * 1024;
pub const GENERATION_SCHEMA: &str = "hepta.inference.generation.v1";
const TOKENS: [&str; 24] = [
    "<pad>",
    "<bos>",
    "<eos>",
    "left",
    "right",
    "relation",
    "less",
    "equal",
    "greater",
    "keep",
    "swap",
    "unknown",
    "hint_left",
    "hint_right",
    "0",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationModelPinsV1 {
    pub checkpoint_sha256: String,
    pub snapshot_sha256: String,
    pub parameters_sha256: String,
    pub config_sha256: String,
    pub source_sha256: String,
    pub python_sha256: String,
    pub device_sha256: String,
    pub runtime_versions: [String; 4],
    pub hidden: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum GenerationActionV1 {
    RefineSemantic,
    RefineImage,
    RefineText,
    Couple,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationRequestV1 {
    pub schema: String,
    pub request_id: String,
    pub objective_sha256: String,
    pub input_source_sha256: String,
    pub model: GenerationModelPinsV1,
    pub required_modalities: u8,
    pub pixels_f32: Vec<u32>,
    pub mask_f32: Vec<u32>,
    pub text_tokens: Vec<u32>,
    pub noise_seed: u64,
    pub content_control: bool,
    pub actions: Vec<GenerationActionV1>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationStateV1 {
    /// h, image, text, context, each with exactly `hidden` values, batch size one.
    /// State zero follows encoder/initial plan; later states follow named actions.
    pub values_f32: Vec<u32>,
    pub backend_state_sha256: String,
    pub plan_index: Option<i32>,
    pub state_sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationExecutionV1 {
    pub schema: String,
    pub request_sha256: String,
    pub model: GenerationModelPinsV1,
    pub states: Vec<GenerationStateV1>,
    pub token_ids: Vec<u32>,
    pub caption: String,
    pub png: Vec<u8>,
    pub png_sha256: String,
    pub text_sha256: String,
    pub wall_ns: u64,
    pub cpu_ns: u64,
    pub peak_rss_bytes: u64,
    /// A wire constant, checked explicitly; never a dispatch or mutation grant.
    pub authority: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GenerationContractError(pub &'static str);

impl std::fmt::Display for GenerationContractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid generation contract: {}", self.0)
    }
}
impl std::error::Error for GenerationContractError {}

fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        && value.bytes().any(|c| c != b'0')
}

pub fn generation_json_digest<T: Serialize>(value: &T) -> Result<String, GenerationContractError> {
    let bytes = serde_json::to_vec(value).map_err(|_| GenerationContractError("JSON"))?;
    if bytes.len() > GENERATION_MAX_BYTES {
        return Err(GenerationContractError("byte bound"));
    }
    Ok(Digest32::of_bytes(&bytes).to_string())
}

impl GenerationModelPinsV1 {
    pub fn validate(&self) -> Result<(), GenerationContractError> {
        if !(16..=128).contains(&self.hidden)
            || self
                .runtime_versions
                .iter()
                .any(|s| s.is_empty() || s.len() > 64)
            || [
                &self.checkpoint_sha256,
                &self.snapshot_sha256,
                &self.parameters_sha256,
                &self.config_sha256,
                &self.source_sha256,
                &self.python_sha256,
                &self.device_sha256,
            ]
            .iter()
            .any(|s| !digest(s))
        {
            return Err(GenerationContractError("model pins"));
        }
        Ok(())
    }
}

impl GenerationRequestV1 {
    pub fn validate(
        &self,
        registered: &GenerationModelPinsV1,
    ) -> Result<(), GenerationContractError> {
        self.model.validate()?;
        if self.model != *registered
            || self.schema != GENERATION_SCHEMA
            || StableId::new(&self.request_id).is_err()
            || !digest(&self.objective_sha256)
            || !digest(&self.input_source_sha256)
            || self.required_modalities != 3
            || self.actions.len() > 8
            || (!self.content_control
                && self.actions.iter().any(|action| {
                    matches!(
                        action,
                        GenerationActionV1::RefineSemantic | GenerationActionV1::Couple
                    )
                }))
            || self.noise_seed > i64::MAX as u64
            || self.pixels_f32.len() != 28 * 56
            || self.mask_f32.len() != 28 * 56
            || self.text_tokens.len() != 8
            || self.text_tokens.iter().any(|v| *v >= 24)
            || self
                .pixels_f32
                .iter()
                .any(|v| !(0.0..=1.0).contains(&f32::from_bits(*v)))
            || self
                .mask_f32
                .iter()
                .any(|v| !matches!(f32::from_bits(*v), 0.0 | 1.0))
        {
            return Err(GenerationContractError("request scope, shape or bounds"));
        }
        generation_json_digest(self)?;
        Ok(())
    }
}

impl GenerationExecutionV1 {
    pub fn verify(&self, request: &GenerationRequestV1) -> Result<(), GenerationContractError> {
        request.validate(&self.model)?;
        if self.schema != GENERATION_SCHEMA
            || self.request_sha256 != generation_json_digest(request)?
            || self.states.len() != request.actions.len() + 1
            || self.token_ids.len() != 8
            || self.token_ids.iter().any(|v| *v >= 24)
            || self.caption.len() > 512
            || self.png.len() < 45
            || self.png.len() > 65_536
            || !self
                .png
                .starts_with(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\08\0\0\0\x1c\x08\0")
            || !self.png.ends_with(b"\0\0\0\0IEND\xaeB`\x82")
            || self.png_sha256 != Digest32::of_bytes(&self.png).to_string()
            || self.text_sha256 != Digest32::of_bytes(self.caption.as_bytes()).to_string()
            || self.wall_ns == 0
            || self.cpu_ns == 0
            || self.peak_rss_bytes == 0
            || self.authority != "deny_all"
        {
            return Err(GenerationContractError("execution binding or bounds"));
        }
        for state in &self.states {
            if state.values_f32.len() != self.model.hidden * 4
                || state
                    .values_f32
                    .iter()
                    .any(|v| !(-8.0..=8.0).contains(&f32::from_bits(*v)))
                || !digest(&state.backend_state_sha256)
                || state.plan_index.is_some_and(|v| !(-1..=3).contains(&v))
            {
                return Err(GenerationContractError("latent state bounds"));
            }
            let mut bytes = b"hepta.inference.generation-state.v1\0".to_vec();
            bytes.extend_from_slice(self.model.snapshot_sha256.as_bytes());
            bytes.extend_from_slice(state.backend_state_sha256.as_bytes());
            bytes.extend_from_slice(&state.plan_index.unwrap_or(-2).to_le_bytes());
            for value in &state.values_f32 {
                bytes.extend_from_slice(&value.to_le_bytes());
            }
            if state.state_sha256 != Digest32::of_bytes(&bytes).to_string() {
                return Err(GenerationContractError("latent state identity"));
            }
        }
        let caption = self
            .token_ids
            .iter()
            .take_while(|id| **id != 2)
            .filter(|id| **id >= 3)
            .map(|id| TOKENS[*id as usize])
            .collect::<Vec<_>>()
            .join(" ");
        if caption != self.caption {
            return Err(GenerationContractError("caption changed after decoding"));
        }
        let width = self.model.hidden;
        for (action, states) in request.actions.iter().zip(self.states.windows(2)) {
            let before = &states[0].values_f32;
            let after = &states[1].values_f32;
            let preserved = match action {
                GenerationActionV1::RefineSemantic => {
                    before[width..3 * width] == after[width..3 * width]
                }
                GenerationActionV1::RefineImage => {
                    before[..width] == after[..width]
                        && before[2 * width..3 * width] == after[2 * width..3 * width]
                }
                GenerationActionV1::RefineText => before[..2 * width] == after[..2 * width],
                GenerationActionV1::Couple => true,
            };
            if !preserved
                || before[3 * width..] != after[3 * width..]
                || states[0].plan_index != states[1].plan_index
            {
                return Err(GenerationContractError(
                    "action changed a preserved state component",
                ));
            }
        }
        generation_json_digest(self)?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "generation_step_tests.rs"]
mod tests;
