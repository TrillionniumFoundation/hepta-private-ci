//! Strict product-owned JSON codecs for shared platform.types protocols.
//!
//! JSON is transport only. Decoders enforce raw-size, depth, duplicate-key,
//! exact-field and canonical-integer rules before constructing validated native
//! values. Semantic identity remains the native HPTC commitment.

use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyContractErrorV1;
use codex_hepta_types::RuntimeTopologyDeltaV1;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::StableId;
use codex_hepta_types::numeric_registry_v2::RegistrySnapshotIdentityV1;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryErrorV2;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryObservationV2;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryRejectReasonV2;

pub const MAX_PLATFORM_TYPES_JSON_BYTES_V1: usize = 65_536;
pub const MAX_PLATFORM_TYPES_JSON_DEPTH_V1: usize = 16;
pub const MAX_CANONICAL_U64_DECIMAL_BYTES_V1: usize = 20;
pub const MAX_CANONICAL_U32_DECIMAL_BYTES_V1: usize = 10;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedRuntimeTopologyCandidateV1(RuntimeTopologyCandidateV1);

impl ValidatedRuntimeTopologyCandidateV1 {
    pub fn new(value: RuntimeTopologyCandidateV1) -> Result<Self, PlatformTypesWireError> {
        value.validate().map_err(PlatformTypesWireError::Topology)?;
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_inner(&self) -> &RuntimeTopologyCandidateV1 {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> RuntimeTopologyCandidateV1 {
        self.0
    }
}

pub fn decode_prompt_delivery_v2_json(
    bytes: &[u8],
) -> Result<PromptDeliveryObservationV2, PlatformTypesWireError> {
    let mut object = parse_json(bytes)?.into_object("prompt delivery")?;
    require_kind(&mut object, "prompt_delivery_observation_v2")?;
    let compilation_id = take_stable_id(&mut object, "compilation_id")?;
    let provider_request_digest = take_digest(&mut object, "provider_request_digest")?;
    let delivered = take_bool(&mut object, "delivered")?;
    let rejected_reason = match take(&mut object, "rejected_reason")? {
        JsonValue::Null => None,
        JsonValue::String(value) => Some(
            PromptDeliveryRejectReasonV2::new(stable_id(&value, "rejected_reason")?)
                .map_err(PlatformTypesWireError::Prompt)?,
        ),
        _ => return Err(PlatformTypesWireError::Type("rejected_reason")),
    };
    let observed_token_positions = match take(&mut object, "observed_token_positions")? {
        JsonValue::Null => None,
        JsonValue::Array(values) => Some(
            values
                .into_iter()
                .map(|value| match value {
                    JsonValue::Number(raw) => canonical_u32(&raw, "observed_token_positions"),
                    _ => Err(PlatformTypesWireError::Type("observed_token_positions")),
                })
                .collect::<Result<Vec<_>, _>>()?,
        ),
        _ => return Err(PlatformTypesWireError::Type("observed_token_positions")),
    };
    let truncation_observed = take_bool(&mut object, "truncation_observed")?;
    let legacy_v1_digest = match take(&mut object, "legacy_v1_digest")? {
        JsonValue::Null => None,
        JsonValue::String(value) => Some(digest(&value, "legacy_v1_digest")?),
        _ => return Err(PlatformTypesWireError::Type("legacy_v1_digest")),
    };
    reject_unknown(object)?;
    PromptDeliveryObservationV2::new(
        compilation_id,
        provider_request_digest,
        delivered,
        rejected_reason,
        observed_token_positions,
        truncation_observed,
        legacy_v1_digest,
    )
    .map_err(PlatformTypesWireError::Prompt)
}

pub fn encode_prompt_delivery_v2_json(
    value: &PromptDeliveryObservationV2,
) -> Result<Vec<u8>, PlatformTypesWireError> {
    value.validate().map_err(PlatformTypesWireError::Prompt)?;
    let reason = value
        .rejected_reason()
        .map_or_else(|| "null".to_owned(), |item| json_string(item.as_id().as_str()));
    let positions = value.observed_token_positions().map_or_else(
        || "null".to_owned(),
        |items| {
            format!(
                "[{}]",
                items
                    .iter()
                    .map(u32::to_string)
                    .collect::<Vec<_>>()
                    .join(",")
            )
        },
    );
    let legacy = value.legacy_v1_digest().map_or_else(
        || "null".to_owned(),
        |item| json_string(&item.to_string()),
    );
    let encoded = format!(
        "{{\"kind\":\"prompt_delivery_observation_v2\",\"compilation_id\":{},\"provider_request_digest\":{},\"delivered\":{},\"rejected_reason\":{},\"observed_token_positions\":{},\"truncation_observed\":{},\"legacy_v1_digest\":{}}}",
        json_string(value.compilation_id().as_str()),
        json_string(&value.provider_request_digest().to_string()),
        value.delivered(),
        reason,
        positions,
        value.truncation_observed(),
        legacy,
    );
    enforce_encoded_bound(encoded.into_bytes())
}

pub fn decode_runtime_topology_candidate_v1_json(
    bytes: &[u8],
) -> Result<ValidatedRuntimeTopologyCandidateV1, PlatformTypesWireError> {
    let mut object = parse_json(bytes)?.into_object("runtime topology")?;
    require_kind(&mut object, "runtime_topology_candidate_v1")?;
    let proposal_digest = take_digest(&mut object, "proposal_digest")?;
    let candidate_id = take_stable_id(&mut object, "candidate_id")?;
    let candidate_digest = take_digest(&mut object, "candidate_digest")?;
    let baseline_generation = take_generation(&mut object, "baseline_generation")?;
    let candidate_generation = take_generation(&mut object, "candidate_generation")?;
    let selected_topology_digest = take_digest(&mut object, "selected_topology_digest")?;
    let evaluation_digest = take_digest(&mut object, "evaluation_digest")?;
    let rollback_predecessor_digest =
        take_digest(&mut object, "rollback_predecessor_digest")?;
    let changed = take_bool(&mut object, "changed")?;
    let deltas = match take(&mut object, "deltas")? {
        JsonValue::Array(values) => values
            .into_iter()
            .map(decode_topology_delta)
            .collect::<Result<Vec<_>, _>>()?,
        _ => return Err(PlatformTypesWireError::Type("deltas")),
    };
    reject_unknown(object)?;
    ValidatedRuntimeTopologyCandidateV1::new(RuntimeTopologyCandidateV1 {
        proposal_digest,
        candidate_id,
        candidate_digest,
        baseline_generation,
        candidate_generation,
        selected_topology_digest,
        evaluation_digest,
        rollback_predecessor_digest,
        changed,
        deltas,
    })
}

pub fn encode_runtime_topology_candidate_v1_json(
    value: &ValidatedRuntimeTopologyCandidateV1,
) -> Result<Vec<u8>, PlatformTypesWireError> {
    let value = value.as_inner();
    value.validate().map_err(PlatformTypesWireError::Topology)?;
    let deltas = value
        .deltas
        .iter()
        .map(|delta| {
            let related = format!(
                "[{}]",
                delta
                    .related_module_ids
                    .iter()
                    .map(|id| json_string(id.as_str()))
                    .collect::<Vec<_>>()
                    .join(",")
            );
            format!(
                "{{\"module_id\":{},\"operation\":{},\"related_module_ids\":{},\"predecessor_digest\":{},\"candidate_digest\":{},\"evidence_digest\":{}}}",
                json_string(delta.module_id.as_str()),
                json_string(operation_id(delta.operation)),
                related,
                json_string(&delta.predecessor_digest.to_string()),
                json_string(&delta.candidate_digest.to_string()),
                json_string(&delta.evidence_digest.to_string()),
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let encoded = format!(
        "{{\"kind\":\"runtime_topology_candidate_v1\",\"proposal_digest\":{},\"candidate_id\":{},\"candidate_digest\":{},\"baseline_generation\":{},\"candidate_generation\":{},\"selected_topology_digest\":{},\"evaluation_digest\":{},\"rollback_predecessor_digest\":{},\"changed\":{},\"deltas\":[{}]}}",
        json_string(&value.proposal_digest.to_string()),
        json_string(value.candidate_id.as_str()),
        json_string(&value.candidate_digest.to_string()),
        json_string(&value.baseline_generation.get().to_string()),
        json_string(&value.candidate_generation.get().to_string()),
        json_string(&value.selected_topology_digest.to_string()),
        json_string(&value.evaluation_digest.to_string()),
        json_string(&value.rollback_predecessor_digest.to_string()),
        value.changed,
        deltas,
    );
    enforce_encoded_bound(encoded.into_bytes())
}

fn decode_topology_delta(value: JsonValue) -> Result<RuntimeTopologyDeltaV1, PlatformTypesWireError> {
    let mut object = value.into_object("topology delta")?;
    let module_id = take_stable_id(&mut object, "module_id")?;
    let operation = match take_string(&mut object, "operation")?.as_str() {
        "add" => RuntimeTopologyOperationV1::Add,
        "replace" => RuntimeTopologyOperationV1::Replace,
        "retire" => RuntimeTopologyOperationV1::Retire,
        "rewire" => RuntimeTopologyOperationV1::Rewire,
        "split" => RuntimeTopologyOperationV1::Split,
        "merge" => RuntimeTopologyOperationV1::Merge,
        _ => return Err(PlatformTypesWireError::Enum("operation")),
    };
    let related_module_ids = match take(&mut object, "related_module_ids")? {
        JsonValue::Array(values) => values
            .into_iter()
            .map(|value| match value {
                JsonValue::String(value) => stable_id(&value, "related_module_ids"),
                _ => Err(PlatformTypesWireError::Type("related_module_ids")),
            })
            .collect::<Result<Vec<_>, _>>()?,
        _ => return Err(PlatformTypesWireError::Type("related_module_ids")),
    };
    let predecessor_digest = take_digest(&mut object, "predecessor_digest")?;
    let candidate_digest = take_digest_allow_zero(&mut object, "candidate_digest")?;
    let evidence_digest = take_digest(&mut object, "evidence_digest")?;
    reject_unknown(object)?;
    Ok(RuntimeTopologyDeltaV1 {
        module_id,
        operation,
        related_module_ids,
        predecessor_digest,
        candidate_digest,
        evidence_digest,
    })
}

fn operation_id(value: RuntimeTopologyOperationV1) -> &'static str {
    match value {
        RuntimeTopologyOperationV1::Add => "add",
        RuntimeTopologyOperationV1::Replace => "replace",
        RuntimeTopologyOperationV1::Retire => "retire",
        RuntimeTopologyOperationV1::Rewire => "rewire",
        RuntimeTopologyOperationV1::Split => "split",
        RuntimeTopologyOperationV1::Merge => "merge",
    }
}

fn require_kind(
    object: &mut BTreeMap<String, JsonValue>,
    expected: &'static str,
) -> Result<(), PlatformTypesWireError> {
    if take_string(object, "kind")? != expected {
        return Err(PlatformTypesWireError::Enum("kind"));
    }
    Ok(())
}

fn take(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<JsonValue, PlatformTypesWireError> {
    object
        .remove(name)
        .ok_or(PlatformTypesWireError::MissingField(name))
}

fn take_string(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<String, PlatformTypesWireError> {
    match take(object, name)? {
        JsonValue::String(value) => Ok(value),
        _ => Err(PlatformTypesWireError::Type(name)),
    }
}

fn take_bool(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<bool, PlatformTypesWireError> {
    match take(object, name)? {
        JsonValue::Bool(value) => Ok(value),
        _ => Err(PlatformTypesWireError::Type(name)),
    }
}

fn take_stable_id(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<StableId, PlatformTypesWireError> {
    stable_id(&take_string(object, name)?, name)
}

fn stable_id(value: &str, name: &'static str) -> Result<StableId, PlatformTypesWireError> {
    StableId::new(value.to_owned()).map_err(|_| PlatformTypesWireError::StableId(name))
}

fn take_digest(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<Digest32, PlatformTypesWireError> {
    let value = digest(&take_string(object, name)?, name)?;
    if value.is_zero() {
        return Err(PlatformTypesWireError::Digest(name));
    }
    Ok(value)
}

fn take_digest_allow_zero(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<Digest32, PlatformTypesWireError> {
    digest(&take_string(object, name)?, name)
}

fn digest(value: &str, name: &'static str) -> Result<Digest32, PlatformTypesWireError> {
    Digest32::from_str(value).map_err(|_| PlatformTypesWireError::Digest(name))
}

fn take_generation(
    object: &mut BTreeMap<String, JsonValue>,
    name: &'static str,
) -> Result<Generation, PlatformTypesWireError> {
    let raw = take_string(object, name)?;
    if raw.len() > MAX_CANONICAL_U64_DECIMAL_BYTES_V1
        || raw.is_empty()
        || (raw.len() > 1 && raw.starts_with('0'))
        || !raw.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(PlatformTypesWireError::CanonicalInteger(name));
    }
    let value = raw
        .parse::<u64>()
        .map_err(|_| PlatformTypesWireError::CanonicalInteger(name))?;
    Generation::new(value).map_err(|_| PlatformTypesWireError::CanonicalInteger(name))
}

fn canonical_u32(raw: &str, name: &'static str) -> Result<u32, PlatformTypesWireError> {
    if raw.len() > MAX_CANONICAL_U32_DECIMAL_BYTES_V1
        || raw.is_empty()
        || (raw.len() > 1 && raw.starts_with('0'))
        || !raw.bytes().all(|byte| byte.is_ascii_digit())
    {
        return Err(PlatformTypesWireError::CanonicalInteger(name));
    }
    raw.parse::<u32>()
        .map_err(|_| PlatformTypesWireError::CanonicalInteger(name))
}

fn reject_unknown(object: BTreeMap<String, JsonValue>) -> Result<(), PlatformTypesWireError> {
    if let Some((name, _)) = object.into_iter().next() {
        return Err(PlatformTypesWireError::UnknownField(name));
    }
    Ok(())
}

fn enforce_encoded_bound(bytes: Vec<u8>) -> Result<Vec<u8>, PlatformTypesWireError> {
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformTypesWireError::TooLarge);
    }
    Ok(bytes)
}

fn json_string(value: &str) -> String {
    let mut output = String::with_capacity(value.len() + 2);
    output.push('"');
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\u{08}' => output.push_str("\\b"),
            '\u{0c}' => output.push_str("\\f"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            value if value <= '\u{1f}' => {
                output.push_str(&format!("\\u{:04x}", u32::from(value)));
            }
            value => output.push(value),
        }
    }
    output.push('"');
    output
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum JsonValue {
    Object(BTreeMap<String, JsonValue>),
    Array(Vec<JsonValue>),
    String(String),
    Bool(bool),
    Null,
    Number(String),
}

impl JsonValue {
    fn into_object(
        self,
        name: &'static str,
    ) -> Result<BTreeMap<String, JsonValue>, PlatformTypesWireError> {
        match self {
            Self::Object(value) => Ok(value),
            _ => Err(PlatformTypesWireError::Type(name)),
        }
    }
}

fn parse_json(bytes: &[u8]) -> Result<JsonValue, PlatformTypesWireError> {
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformTypesWireError::TooLarge);
    }
    std::str::from_utf8(bytes).map_err(|_| PlatformTypesWireError::InvalidUtf8)?;
    let mut parser = JsonParser { bytes, offset: 0 };
    let value = parser.parse_value(0)?;
    parser.skip_whitespace();
    if parser.offset != bytes.len() {
        return Err(PlatformTypesWireError::Syntax);
    }
    Ok(value)
}

struct JsonParser<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl JsonParser<'_> {
    fn skip_whitespace(&mut self) {
        while matches!(self.bytes.get(self.offset), Some(b' ' | b'\n' | b'\r' | b'\t')) {
            self.offset += 1;
        }
    }

    fn parse_value(&mut self, depth: usize) -> Result<JsonValue, PlatformTypesWireError> {
        if depth > MAX_PLATFORM_TYPES_JSON_DEPTH_V1 {
            return Err(PlatformTypesWireError::DepthExceeded);
        }
        self.skip_whitespace();
        match self.bytes.get(self.offset).copied() {
            Some(b'{') => self.parse_object(depth + 1),
            Some(b'[') => self.parse_array(depth + 1),
            Some(b'"') => self.parse_string().map(JsonValue::String),
            Some(b't') => self.parse_literal(b"true", JsonValue::Bool(true)),
            Some(b'f') => self.parse_literal(b"false", JsonValue::Bool(false)),
            Some(b'n') => self.parse_literal(b"null", JsonValue::Null),
            Some(b'-' | b'0'..=b'9') => self.parse_number().map(JsonValue::Number),
            _ => Err(PlatformTypesWireError::Syntax),
        }
    }

    fn parse_object(&mut self, depth: usize) -> Result<JsonValue, PlatformTypesWireError> {
        self.offset += 1;
        let mut result = BTreeMap::new();
        self.skip_whitespace();
        if self.bytes.get(self.offset) == Some(&b'}') {
            self.offset += 1;
            return Ok(JsonValue::Object(result));
        }
        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            self.skip_whitespace();
            if self.bytes.get(self.offset) != Some(&b':') {
                return Err(PlatformTypesWireError::Syntax);
            }
            self.offset += 1;
            let value = self.parse_value(depth)?;
            if result.insert(key.clone(), value).is_some() {
                return Err(PlatformTypesWireError::DuplicateKey(key));
            }
            self.skip_whitespace();
            match self.bytes.get(self.offset) {
                Some(b',') => self.offset += 1,
                Some(b'}') => {
                    self.offset += 1;
                    break;
                }
                _ => return Err(PlatformTypesWireError::Syntax),
            }
        }
        Ok(JsonValue::Object(result))
    }

    fn parse_array(&mut self, depth: usize) -> Result<JsonValue, PlatformTypesWireError> {
        self.offset += 1;
        let mut result = Vec::new();
        self.skip_whitespace();
        if self.bytes.get(self.offset) == Some(&b']') {
            self.offset += 1;
            return Ok(JsonValue::Array(result));
        }
        loop {
            result.push(self.parse_value(depth)?);
            self.skip_whitespace();
            match self.bytes.get(self.offset) {
                Some(b',') => self.offset += 1,
                Some(b']') => {
                    self.offset += 1;
                    break;
                }
                _ => return Err(PlatformTypesWireError::Syntax),
            }
        }
        Ok(JsonValue::Array(result))
    }

    fn parse_string(&mut self) -> Result<String, PlatformTypesWireError> {
        if self.bytes.get(self.offset) != Some(&b'"') {
            return Err(PlatformTypesWireError::Syntax);
        }
        self.offset += 1;
        let mut output = Vec::new();
        loop {
            let byte = *self
                .bytes
                .get(self.offset)
                .ok_or(PlatformTypesWireError::Syntax)?;
            self.offset += 1;
            match byte {
                b'"' => break,
                0x00..=0x1f => return Err(PlatformTypesWireError::Syntax),
                b'\\' => {
                    let escape = *self
                        .bytes
                        .get(self.offset)
                        .ok_or(PlatformTypesWireError::Syntax)?;
                    self.offset += 1;
                    match escape {
                        b'"' | b'\\' | b'/' => output.push(escape),
                        b'b' => output.push(0x08),
                        b'f' => output.push(0x0c),
                        b'n' => output.push(b'\n'),
                        b'r' => output.push(b'\r'),
                        b't' => output.push(b'\t'),
                        b'u' => {
                            let first = self.parse_hex_quad()?;
                            let scalar = if (0xd800..=0xdbff).contains(&first) {
                                if self.bytes.get(self.offset..self.offset + 2) != Some(b"\\u") {
                                    return Err(PlatformTypesWireError::Syntax);
                                }
                                self.offset += 2;
                                let second = self.parse_hex_quad()?;
                                if !(0xdc00..=0xdfff).contains(&second) {
                                    return Err(PlatformTypesWireError::Syntax);
                                }
                                0x1_0000
                                    + ((u32::from(first) - 0xd800) << 10)
                                    + (u32::from(second) - 0xdc00)
                            } else if (0xdc00..=0xdfff).contains(&first) {
                                return Err(PlatformTypesWireError::Syntax);
                            } else {
                                u32::from(first)
                            };
                            let character = char::from_u32(scalar)
                                .ok_or(PlatformTypesWireError::Syntax)?;
                            let mut buffer = [0_u8; 4];
                            output.extend_from_slice(character.encode_utf8(&mut buffer).as_bytes());
                        }
                        _ => return Err(PlatformTypesWireError::Syntax),
                    }
                }
                value => output.push(value),
            }
        }
        String::from_utf8(output).map_err(|_| PlatformTypesWireError::InvalidUtf8)
    }

    fn parse_hex_quad(&mut self) -> Result<u16, PlatformTypesWireError> {
        let mut value = 0_u16;
        for _ in 0..4 {
            let byte = *self
                .bytes
                .get(self.offset)
                .ok_or(PlatformTypesWireError::Syntax)?;
            self.offset += 1;
            let digit = match byte {
                b'0'..=b'9' => u16::from(byte - b'0'),
                b'a'..=b'f' => u16::from(byte - b'a' + 10),
                b'A'..=b'F' => u16::from(byte - b'A' + 10),
                _ => return Err(PlatformTypesWireError::Syntax),
            };
            value = value * 16 + digit;
        }
        Ok(value)
    }

    fn parse_literal(
        &mut self,
        literal: &[u8],
        value: JsonValue,
    ) -> Result<JsonValue, PlatformTypesWireError> {
        if self.bytes.get(self.offset..self.offset + literal.len()) != Some(literal) {
            return Err(PlatformTypesWireError::Syntax);
        }
        self.offset += literal.len();
        Ok(value)
    }

    fn parse_number(&mut self) -> Result<String, PlatformTypesWireError> {
        let start = self.offset;
        if self.bytes.get(self.offset) == Some(&b'-') {
            self.offset += 1;
        }
        match self.bytes.get(self.offset) {
            Some(b'0') => self.offset += 1,
            Some(b'1'..=b'9') => {
                self.offset += 1;
                while matches!(self.bytes.get(self.offset), Some(b'0'..=b'9')) {
                    self.offset += 1;
                }
            }
            _ => return Err(PlatformTypesWireError::Syntax),
        }
        if self.bytes.get(self.offset) == Some(&b'.') {
            self.offset += 1;
            let fraction_start = self.offset;
            while matches!(self.bytes.get(self.offset), Some(b'0'..=b'9')) {
                self.offset += 1;
            }
            if self.offset == fraction_start {
                return Err(PlatformTypesWireError::Syntax);
            }
        }
        if matches!(self.bytes.get(self.offset), Some(b'e' | b'E')) {
            self.offset += 1;
            if matches!(self.bytes.get(self.offset), Some(b'+' | b'-')) {
                self.offset += 1;
            }
            let exponent_start = self.offset;
            while matches!(self.bytes.get(self.offset), Some(b'0'..=b'9')) {
                self.offset += 1;
            }
            if self.offset == exponent_start {
                return Err(PlatformTypesWireError::Syntax);
            }
        }
        std::str::from_utf8(&self.bytes[start..self.offset])
            .map(str::to_owned)
            .map_err(|_| PlatformTypesWireError::InvalidUtf8)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformTypesWireError {
    TooLarge,
    DepthExceeded,
    InvalidUtf8,
    Syntax,
    DuplicateKey(String),
    MissingField(&'static str),
    UnknownField(String),
    Type(&'static str),
    Enum(&'static str),
    CanonicalInteger(&'static str),
    StableId(&'static str),
    Digest(&'static str),
    Prompt(PromptDeliveryErrorV2),
    Topology(RuntimeTopologyContractErrorV1),
}

impl fmt::Display for PlatformTypesWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlatformTypesWireError {}

#[cfg(test)]
mod tests {
    use super::*;

    const PROMPT: &str = concat!(
        "{\"kind\":\"prompt_delivery_observation_v2\",",
        "\"compilation_id\":\"compilation-42\",",
        "\"provider_request_digest\":\"2393429a406f72713f04dceab858ac03a88a051576680a500e91e5eb468c3f56\",",
        "\"delivered\":false,",
        "\"rejected_reason\":\"provider.rate_limited\",",
        "\"observed_token_positions\":[1,4,9],",
        "\"truncation_observed\":true,",
        "\"legacy_v1_digest\":\"24ea7fc3f71b6412a07d72ac08e83bcfe4aa18021b1e273467c8edfe508238af\"}"
    );

    const TOPOLOGY: &str = concat!(
        "{\"kind\":\"runtime_topology_candidate_v1\",",
        "\"proposal_digest\":\"ecd1378bc9dc130008f00d58db5d26f60db55934a49b949af7e6f6a8da2a2beb\",",
        "\"candidate_id\":\"candidate-8\",",
        "\"candidate_digest\":\"8a2396058d95d3c0efde025d3e34ec1524d0ffa3a10f2fb8f6457cdb35a195d8\",",
        "\"baseline_generation\":\"7\",\"candidate_generation\":\"8\",",
        "\"selected_topology_digest\":\"fa232b9dc6dac7e96f45b416ccb6a69c9943b1834979ebf3bdd6fadc2dac649f\",",
        "\"evaluation_digest\":\"efe77b201dc216c0edf435a227df2b2898d3f6ea1ff16e5d4d0d4ec0cf593271\",",
        "\"rollback_predecessor_digest\":\"fa232b9dc6dac7e96f45b416ccb6a69c9943b1834979ebf3bdd6fadc2dac649f\",",
        "\"changed\":true,\"deltas\":[{",
        "\"module_id\":\"module.alpha\",\"operation\":\"add\",\"related_module_ids\":[],",
        "\"predecessor_digest\":\"0000000000000000000000000000000000000000000000000000000000000000\",",
        "\"candidate_digest\":\"27e3ad1bd5794e7c5639704ab86fe63a6f01387f14c3380b6a009dd6b5616d5a\",",
        "\"evidence_digest\":\"ff2f2ce7f9577786db39d3dcb0e2b93bf0f583bb0daffbe04fa65b97c4e1b6d7\"}]}"
    );

    #[test]
    fn prompt_v2_json_is_strict_and_hptc_bound() {
        let value = decode_prompt_delivery_v2_json(PROMPT.as_bytes()).expect("decode");
        assert_eq!(
            value.semantic_digest().expect("digest").to_string(),
            "829b995e0ebf8df74a18723dcc477ec924fefe1be88b8f60d9bb388e6073fa34"
        );
        let encoded = encode_prompt_delivery_v2_json(&value).expect("encode");
        assert_eq!(decode_prompt_delivery_v2_json(&encoded).expect("roundtrip"), value);
    }

    #[test]
    fn topology_json_is_strict_and_recomputes_candidate_digest() {
        let value = decode_runtime_topology_candidate_v1_json(TOPOLOGY.as_bytes())
            .expect("decode");
        assert_eq!(
            value.as_inner().content_digest().expect("digest").to_string(),
            "8a2396058d95d3c0efde025d3e34ec1524d0ffa3a10f2fb8f6457cdb35a195d8"
        );
        let encoded = encode_runtime_topology_candidate_v1_json(&value).expect("encode");
        assert_eq!(
            decode_runtime_topology_candidate_v1_json(&encoded).expect("roundtrip"),
            value
        );
    }

    #[test]
    fn duplicate_keys_depth_size_and_long_integers_fail_before_admission() {
        let duplicate = PROMPT.replacen(
            "\"kind\":\"prompt_delivery_observation_v2\"",
            "\"kind\":\"prompt_delivery_observation_v2\",\"kind\":\"prompt_delivery_observation_v2\"",
            1,
        );
        assert!(matches!(
            decode_prompt_delivery_v2_json(duplicate.as_bytes()),
            Err(PlatformTypesWireError::DuplicateKey(_))
        ));
        let deep = format!("{}0{}", "[".repeat(18), "]".repeat(18));
        assert_eq!(parse_json(deep.as_bytes()), Err(PlatformTypesWireError::DepthExceeded));
        assert_eq!(
            parse_json(&vec![b' '; MAX_PLATFORM_TYPES_JSON_BYTES_V1 + 1]),
            Err(PlatformTypesWireError::TooLarge)
        );
        let long = TOPOLOGY.replace(
            "\"baseline_generation\":\"7\"",
            "\"baseline_generation\":\"184467440737095516150\"",
        );
        assert_eq!(
            decode_runtime_topology_candidate_v1_json(long.as_bytes()),
            Err(PlatformTypesWireError::CanonicalInteger("baseline_generation"))
        );
    }

    #[test]
    fn registry_snapshot_type_remains_product_wire_independent() {
        let identity = RegistrySnapshotIdentityV1::new(
            Generation::new(1).expect("generation"),
            Digest32::of_bytes(b"registry"),
        )
        .expect("identity");
        assert_eq!(identity.generation().get(), 1);
    }
}
