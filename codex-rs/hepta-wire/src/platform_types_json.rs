//! Strict product-owned JSON codecs for shared `platform.types` protocols.
//!
//! JSON is transport only. Raw size and nesting are bounded before Serde sees
//! the input. Derived structs reject duplicate and unknown fields, decimal
//! generation strings are canonical, and native contracts revalidate all
//! semantic invariants before a value leaves this module.

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
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryErrorV2;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryObservationV2;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryRejectReasonV2;
use codex_hepta_types::protocol_catalog_v2::identity_profile_for_protocol_field_v2;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;

pub const MAX_PLATFORM_TYPES_JSON_BYTES_V1: usize = 65_536;
pub const MAX_PLATFORM_TYPES_JSON_DEPTH_V1: usize = 16;
pub const MAX_CANONICAL_U64_DECIMAL_BYTES_V1: usize = 20;

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

fn deserialize_required_nullable<'de, D, T>(deserializer: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(deserializer)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CanonicalU64String(u64);

impl Serialize for CanonicalU64String {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for CanonicalU64String {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        if raw.is_empty()
            || raw.len() > MAX_CANONICAL_U64_DECIMAL_BYTES_V1
            || (raw.len() > 1 && raw.starts_with('0'))
            || !raw.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(serde::de::Error::custom("non-canonical u64 string"));
        }
        raw.parse::<u64>()
            .map(Self)
            .map_err(|_| serde::de::Error::custom("u64 string out of range"))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PromptDeliveryObservationV2Json {
    kind: String,
    compilation_id: String,
    provider_request_digest: String,
    delivered: bool,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    rejected_reason: Option<String>,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    observed_token_positions: Option<Vec<u32>>,
    truncation_observed: bool,
    #[serde(deserialize_with = "deserialize_required_nullable")]
    legacy_v1_digest: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTopologyCandidateV1Json {
    kind: String,
    proposal_digest: String,
    candidate_id: String,
    candidate_digest: String,
    baseline_generation: CanonicalU64String,
    candidate_generation: CanonicalU64String,
    selected_topology_digest: String,
    evaluation_digest: String,
    rollback_predecessor_digest: String,
    changed: bool,
    deltas: Vec<RuntimeTopologyDeltaV1Json>,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RuntimeTopologyDeltaV1Json {
    module_id: String,
    operation: String,
    related_module_ids: Vec<String>,
    predecessor_digest: String,
    candidate_digest: String,
    evidence_digest: String,
}

pub fn decode_prompt_delivery_v2_json(
    bytes: &[u8],
) -> Result<PromptDeliveryObservationV2, PlatformTypesWireError> {
    let wire: PromptDeliveryObservationV2Json = decode_json(bytes)?;
    if wire.kind != "prompt_delivery_observation_v2" {
        return Err(PlatformTypesWireError::InvalidKind);
    }
    let rejected_reason = wire
        .rejected_reason
        .map(|value| {
            PromptDeliveryRejectReasonV2::new(stable_id(
                "PromptDeliveryObservationV2",
                "rejected_reason",
                &value,
                "rejected_reason",
            )?)
            .map_err(PlatformTypesWireError::Prompt)
        })
        .transpose()?;
    let legacy_v1_digest = wire
        .legacy_v1_digest
        .map(|value| digest(&value, "legacy_v1_digest"))
        .transpose()?;
    PromptDeliveryObservationV2::new(
        stable_id(
            "PromptDeliveryObservationV2",
            "compilation_id",
            &wire.compilation_id,
            "compilation_id",
        )?,
        nonzero_digest(&wire.provider_request_digest, "provider_request_digest")?,
        wire.delivered,
        rejected_reason,
        wire.observed_token_positions,
        wire.truncation_observed,
        legacy_v1_digest,
    )
    .map_err(PlatformTypesWireError::Prompt)
}

pub fn encode_prompt_delivery_v2_json(
    value: &PromptDeliveryObservationV2,
) -> Result<Vec<u8>, PlatformTypesWireError> {
    value.validate().map_err(PlatformTypesWireError::Prompt)?;
    encode_json(&PromptDeliveryObservationV2Json {
        kind: "prompt_delivery_observation_v2".to_owned(),
        compilation_id: value.compilation_id().to_string(),
        provider_request_digest: value.provider_request_digest().to_string(),
        delivered: value.delivered(),
        rejected_reason: value
            .rejected_reason()
            .map(|reason| reason.as_id().to_string()),
        observed_token_positions: value.observed_token_positions().map(<[u32]>::to_vec),
        truncation_observed: value.truncation_observed(),
        legacy_v1_digest: value.legacy_v1_digest().map(|item| item.to_string()),
    })
}

pub fn decode_runtime_topology_candidate_v1_json(
    bytes: &[u8],
) -> Result<ValidatedRuntimeTopologyCandidateV1, PlatformTypesWireError> {
    let wire: RuntimeTopologyCandidateV1Json = decode_json(bytes)?;
    if wire.kind != "runtime_topology_candidate_v1" {
        return Err(PlatformTypesWireError::InvalidKind);
    }
    let value = RuntimeTopologyCandidateV1 {
        proposal_digest: nonzero_digest(&wire.proposal_digest, "proposal_digest")?,
        candidate_id: stable_id(
            "RuntimeTopologyCandidateV1",
            "candidate_id",
            &wire.candidate_id,
            "candidate_id",
        )?,
        candidate_digest: nonzero_digest(&wire.candidate_digest, "candidate_digest")?,
        baseline_generation: generation(wire.baseline_generation, "baseline_generation")?,
        candidate_generation: generation(wire.candidate_generation, "candidate_generation")?,
        selected_topology_digest: nonzero_digest(
            &wire.selected_topology_digest,
            "selected_topology_digest",
        )?,
        evaluation_digest: nonzero_digest(&wire.evaluation_digest, "evaluation_digest")?,
        rollback_predecessor_digest: nonzero_digest(
            &wire.rollback_predecessor_digest,
            "rollback_predecessor_digest",
        )?,
        changed: wire.changed,
        deltas: wire
            .deltas
            .into_iter()
            .map(decode_delta)
            .collect::<Result<Vec<_>, _>>()?,
    };
    ValidatedRuntimeTopologyCandidateV1::new(value)
}

pub fn encode_runtime_topology_candidate_v1_json(
    value: &ValidatedRuntimeTopologyCandidateV1,
) -> Result<Vec<u8>, PlatformTypesWireError> {
    let value = value.as_inner();
    value.validate().map_err(PlatformTypesWireError::Topology)?;
    encode_json(&RuntimeTopologyCandidateV1Json {
        kind: "runtime_topology_candidate_v1".to_owned(),
        proposal_digest: value.proposal_digest.to_string(),
        candidate_id: value.candidate_id.to_string(),
        candidate_digest: value.candidate_digest.to_string(),
        baseline_generation: CanonicalU64String(value.baseline_generation.get()),
        candidate_generation: CanonicalU64String(value.candidate_generation.get()),
        selected_topology_digest: value.selected_topology_digest.to_string(),
        evaluation_digest: value.evaluation_digest.to_string(),
        rollback_predecessor_digest: value.rollback_predecessor_digest.to_string(),
        changed: value.changed,
        deltas: value.deltas.iter().map(encode_delta).collect(),
    })
}

fn decode_delta(
    wire: RuntimeTopologyDeltaV1Json,
) -> Result<RuntimeTopologyDeltaV1, PlatformTypesWireError> {
    let operation = match wire.operation.as_str() {
        "add" => RuntimeTopologyOperationV1::Add,
        "replace" => RuntimeTopologyOperationV1::Replace,
        "retire" => RuntimeTopologyOperationV1::Retire,
        "rewire" => RuntimeTopologyOperationV1::Rewire,
        "split" => RuntimeTopologyOperationV1::Split,
        "merge" => RuntimeTopologyOperationV1::Merge,
        _ => return Err(PlatformTypesWireError::InvalidOperation),
    };
    Ok(RuntimeTopologyDeltaV1 {
        module_id: stable_id(
            "RuntimeTopologyCandidateV1",
            "deltas[].module_id",
            &wire.module_id,
            "module_id",
        )?,
        operation,
        related_module_ids: wire
            .related_module_ids
            .iter()
            .map(|value| {
                stable_id(
                    "RuntimeTopologyCandidateV1",
                    "deltas[].related_module_ids[]",
                    value,
                    "related_module_ids",
                )
            })
            .collect::<Result<Vec<_>, _>>()?,
        predecessor_digest: digest(&wire.predecessor_digest, "predecessor_digest")?,
        candidate_digest: digest(&wire.candidate_digest, "candidate_digest")?,
        evidence_digest: nonzero_digest(&wire.evidence_digest, "evidence_digest")?,
    })
}

fn encode_delta(value: &RuntimeTopologyDeltaV1) -> RuntimeTopologyDeltaV1Json {
    RuntimeTopologyDeltaV1Json {
        module_id: value.module_id.to_string(),
        operation: match value.operation {
            RuntimeTopologyOperationV1::Add => "add",
            RuntimeTopologyOperationV1::Replace => "replace",
            RuntimeTopologyOperationV1::Retire => "retire",
            RuntimeTopologyOperationV1::Rewire => "rewire",
            RuntimeTopologyOperationV1::Split => "split",
            RuntimeTopologyOperationV1::Merge => "merge",
        }
        .to_owned(),
        related_module_ids: value
            .related_module_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        predecessor_digest: value.predecessor_digest.to_string(),
        candidate_digest: value.candidate_digest.to_string(),
        evidence_digest: value.evidence_digest.to_string(),
    }
}

fn decode_json<T>(bytes: &[u8]) -> Result<T, PlatformTypesWireError>
where
    T: for<'de> Deserialize<'de>,
{
    enforce_raw_limits(bytes)?;
    match super::strict_json::validate_json_structure(bytes) {
        Ok(()) => {}
        Err(super::strict_json::JsonStructureError::DuplicateKey) => {
            return Err(PlatformTypesWireError::DuplicateKey);
        }
        Err(super::strict_json::JsonStructureError::InvalidJson) => {
            return Err(PlatformTypesWireError::InvalidJson);
        }
    }
    serde_json::from_slice(bytes).map_err(|_| PlatformTypesWireError::InvalidJson)
}

fn encode_json<T>(value: &T) -> Result<Vec<u8>, PlatformTypesWireError>
where
    T: Serialize,
{
    let bytes = serde_json::to_vec(value).map_err(|_| PlatformTypesWireError::InvalidJson)?;
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformTypesWireError::TooLarge);
    }
    Ok(bytes)
}

fn enforce_raw_limits(bytes: &[u8]) -> Result<(), PlatformTypesWireError> {
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformTypesWireError::TooLarge);
    }
    std::str::from_utf8(bytes).map_err(|_| PlatformTypesWireError::InvalidUtf8)?;
    let mut depth = 0_usize;
    let mut in_string = false;
    let mut escaped = false;
    for byte in bytes {
        if in_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                in_string = false;
            }
            continue;
        }
        match byte {
            b'"' => in_string = true,
            b'{' | b'[' => {
                depth = depth
                    .checked_add(1)
                    .ok_or(PlatformTypesWireError::DepthExceeded)?;
                if depth > MAX_PLATFORM_TYPES_JSON_DEPTH_V1 {
                    return Err(PlatformTypesWireError::DepthExceeded);
                }
            }
            b'}' | b']' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }
    Ok(())
}

fn stable_id(
    protocol_id: &'static str,
    field_path: &'static str,
    value: &str,
    field: &'static str,
) -> Result<StableId, PlatformTypesWireError> {
    let profile = identity_profile_for_protocol_field_v2(protocol_id, field_path)
        .ok_or(PlatformTypesWireError::StableId(field))?;
    StableId::with_profile(value, profile).map_err(|_| PlatformTypesWireError::StableId(field))
}

fn digest(value: &str, field: &'static str) -> Result<Digest32, PlatformTypesWireError> {
    Digest32::from_str(value).map_err(|_| PlatformTypesWireError::Digest(field))
}

fn nonzero_digest(value: &str, field: &'static str) -> Result<Digest32, PlatformTypesWireError> {
    let value = digest(value, field)?;
    if value.is_zero() {
        return Err(PlatformTypesWireError::Digest(field));
    }
    Ok(value)
}

fn generation(
    value: CanonicalU64String,
    field: &'static str,
) -> Result<Generation, PlatformTypesWireError> {
    Generation::new(value.0).map_err(|_| PlatformTypesWireError::CanonicalInteger(field))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformTypesWireError {
    TooLarge,
    DepthExceeded,
    InvalidUtf8,
    InvalidJson,
    DuplicateKey,
    InvalidKind,
    InvalidOperation,
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
        assert_eq!(
            decode_prompt_delivery_v2_json(&encoded).expect("roundtrip"),
            value
        );
    }

    #[test]
    fn topology_json_is_strict_and_recomputes_candidate_digest() {
        let value = decode_runtime_topology_candidate_v1_json(TOPOLOGY.as_bytes()).expect("decode");
        assert_eq!(
            value
                .as_inner()
                .content_digest()
                .expect("digest")
                .to_string(),
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
        assert_eq!(
            decode_prompt_delivery_v2_json(duplicate.as_bytes()),
            Err(PlatformTypesWireError::DuplicateKey)
        );
        let deep = format!("{}0{}", "[".repeat(18), "]".repeat(18));
        assert_eq!(
            enforce_raw_limits(deep.as_bytes()),
            Err(PlatformTypesWireError::DepthExceeded)
        );
        assert_eq!(
            enforce_raw_limits(&vec![b' '; MAX_PLATFORM_TYPES_JSON_BYTES_V1 + 1]),
            Err(PlatformTypesWireError::TooLarge)
        );
        let long = TOPOLOGY.replace(
            "\"baseline_generation\":\"7\"",
            "\"baseline_generation\":\"184467440737095516150\"",
        );
        assert_eq!(
            decode_runtime_topology_candidate_v1_json(long.as_bytes()),
            Err(PlatformTypesWireError::InvalidJson)
        );
    }

    #[test]
    fn strict_json_compares_decoded_keys_within_each_object() {
        for raw in [
            r#"{"x":1,"\u0078":2}"#,
            r#"{"outer":{"x":1,"x":2}}"#,
            r#"[{"x":1,"x":2}]"#,
        ] {
            assert_eq!(
                decode_json::<serde_json::Value>(raw.as_bytes()),
                Err(PlatformTypesWireError::DuplicateKey)
            );
        }
        for raw in [
            r#"[{"x":1},{"x":2}]"#,
            r#"{"x":{"x":1}}"#,
            r#"{"x":"\"x\":1"}"#,
        ] {
            assert_eq!(
                decode_json::<serde_json::Value>(raw.as_bytes()).expect("distinct object keys"),
                serde_json::from_str::<serde_json::Value>(raw).expect("valid JSON")
            );
        }
    }

    #[test]
    fn prompt_unsigned_positions_reject_non_integer_number_lexemes() {
        for number in ["1.0", "1e0", "-0"] {
            let raw = PROMPT.replace("[1,4,9]", &format!("[{number},4,9]"));
            assert_eq!(
                decode_prompt_delivery_v2_json(raw.as_bytes()),
                Err(PlatformTypesWireError::InvalidJson)
            );
        }
    }

    #[test]
    fn missing_nullable_fields_are_not_silently_defaulted() {
        let missing = PROMPT.replace(
            ",\"legacy_v1_digest\":\"24ea7fc3f71b6412a07d72ac08e83bcfe4aa18021b1e273467c8edfe508238af\"",
            "",
        );
        assert_eq!(
            decode_prompt_delivery_v2_json(missing.as_bytes()),
            Err(PlatformTypesWireError::InvalidJson)
        );
    }
}
