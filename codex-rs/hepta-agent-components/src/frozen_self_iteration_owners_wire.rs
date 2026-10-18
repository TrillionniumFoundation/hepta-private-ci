//! Finite E/S/O requests carry original codecs and model fact identities only.
//! Neither decoding nor a caller's model text establishes owner authority.
use super::*;

pub const MAX_SELF_ITERATION_OWNER_RECORD_BYTES_V1: usize = 16 * 1024;
pub const MAX_SELF_ITERATION_OWNER_EVALUATION_BYTES_V1: usize = 1024 * 1024;
pub const MAX_SELF_ITERATION_OWNER_REQUEST_BYTES_V1: usize =
    2 * (280 * 1024 + MAX_SELF_ITERATION_OWNER_RECORD_BYTES_V1) + 4096;
pub const MAX_SELF_ITERATION_OWNER_RESPONSE_BYTES_V1: usize =
    2 * MAX_SELF_ITERATION_OWNER_EVALUATION_BYTES_V1 + 4096;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum SelfIterationOwnerPurposeV1 {
    Evaluate,
    Select,
    Observe,
}
impl SelfIterationOwnerPurposeV1 {
    pub fn schema(self) -> u32 {
        match self {
            Self::Evaluate => 5,
            Self::Select => 6,
            Self::Observe => 7,
        }
    }
    pub fn maximum_response_bytes(self) -> usize {
        match self {
            Self::Evaluate => MAX_SELF_ITERATION_OWNER_RESPONSE_BYTES_V1,
            Self::Select | Self::Observe => 2 * 32 * 1024 + 4096,
        }
    }
}

/// A model fact lookup tuple. The Root service must join it to its original
/// native record, protected provider witness and authenticated current round.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationOwnerModelFactsV1 {
    pub request_id: String,
    pub envelope_digest: String,
    pub candidate_digest: String,
    pub output_digest: String,
    pub native_run_digest: String,
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationOwnerRequestV1 {
    pub schema_version: u32,
    pub purpose: SelfIterationOwnerPurposeV1,
    pub frozen_consumer_hex: String,
    pub original_record_hex: String,
    pub model_facts: SelfIterationOwnerModelFactsV1,
}
impl SelfIterationOwnerRequestV1 {
    pub fn from_original_bytes(
        purpose: SelfIterationOwnerPurposeV1,
        consumer: &[u8],
        record: &[u8],
        model_facts: SelfIterationOwnerModelFactsV1,
    ) -> WireResult<Self> {
        let request = Self {
            schema_version: purpose.schema(),
            purpose,
            frozen_consumer_hex: encode_hex(consumer),
            original_record_hex: encode_hex(record),
            model_facts,
        };
        request.original_bytes()?;
        Ok(request)
    }
    pub fn original_bytes(&self) -> WireResult<(Vec<u8>, Vec<u8>)> {
        if self.schema_version != self.purpose.schema() {
            return Err("finite self-iteration owner schema/purpose mismatch".into());
        }
        codex_hepta_types::StableId::new(&self.model_facts.request_id)?;
        for text in [
            &self.model_facts.envelope_digest,
            &self.model_facts.candidate_digest,
            &self.model_facts.output_digest,
            &self.model_facts.native_run_digest,
        ] {
            let digest: codex_hepta_types::Digest32 = text.parse()?;
            if digest.is_zero() || digest.to_string() != *text {
                return Err("whole original model fact digest".into());
            }
        }
        Ok((
            decode_hex(&self.frozen_consumer_hex, 280 * 1024)?,
            decode_hex(
                &self.original_record_hex,
                MAX_SELF_ITERATION_OWNER_RECORD_BYTES_V1,
            )?,
        ))
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SelfIterationOwnerGrantedV1 {
    pub schema_version: u32,
    pub purpose: SelfIterationOwnerPurposeV1,
    pub frozen_digest: String,
    /// E returns its whole original transport; S/O return their whole original
    /// finite-purpose publication. No response creates another evidence codec.
    pub original_publication_hex: String,
}
impl SelfIterationOwnerGrantedV1 {
    pub fn from_publication(
        purpose: SelfIterationOwnerPurposeV1,
        frozen: codex_hepta_types::Digest32,
        publication: &[u8],
    ) -> WireResult<Self> {
        let value = Self {
            schema_version: purpose.schema(),
            purpose,
            frozen_digest: frozen.to_string(),
            original_publication_hex: encode_hex(publication),
        };
        value.publication()?;
        Ok(value)
    }
    pub fn publication(&self) -> WireResult<Vec<u8>> {
        let digest: codex_hepta_types::Digest32 = self.frozen_digest.parse()?;
        if self.schema_version != self.purpose.schema()
            || digest.is_zero()
            || digest.to_string() != self.frozen_digest
        {
            return Err("finite owner response binding".into());
        }
        decode_hex(
            &self.original_publication_hex,
            match self.purpose {
                SelfIterationOwnerPurposeV1::Evaluate => {
                    MAX_SELF_ITERATION_OWNER_EVALUATION_BYTES_V1
                }
                _ => 32 * 1024,
            },
        )
    }
}
#[derive(Deserialize, Serialize)]
#[serde(untagged)]
pub enum SelfIterationOwnerResponseV1 {
    Granted(SelfIterationOwnerGrantedV1),
    Refused(FrozenGeneratorFailureV1),
}
pub fn encode_self_iteration_owner_request_v1(
    value: &SelfIterationOwnerRequestV1,
) -> WireResult<Vec<u8>> {
    value.original_bytes()?;
    bounded_json(value, MAX_SELF_ITERATION_OWNER_REQUEST_BYTES_V1)
}
pub fn decode_self_iteration_owner_request_v1(
    bytes: &[u8],
) -> WireResult<SelfIterationOwnerRequestV1> {
    validate_frame(bytes, MAX_SELF_ITERATION_OWNER_REQUEST_BYTES_V1)?;
    let value: SelfIterationOwnerRequestV1 = serde_json::from_slice(bytes)?;
    value.original_bytes()?;
    Ok(value)
}
pub fn encode_self_iteration_owner_response_v1(
    purpose: SelfIterationOwnerPurposeV1,
    value: &SelfIterationOwnerResponseV1,
) -> WireResult<Vec<u8>> {
    if let SelfIterationOwnerResponseV1::Granted(value) = value {
        if value.purpose != purpose {
            return Err("finite owner response purpose".into());
        }
        value.publication()?;
    }
    bounded_json(value, purpose.maximum_response_bytes())
}
pub fn decode_self_iteration_owner_response_v1(
    purpose: SelfIterationOwnerPurposeV1,
    bytes: &[u8],
) -> WireResult<SelfIterationOwnerResponseV1> {
    validate_frame(bytes, purpose.maximum_response_bytes())?;
    let value: SelfIterationOwnerResponseV1 = serde_json::from_slice(bytes)?;
    if let SelfIterationOwnerResponseV1::Granted(value) = &value {
        if value.purpose != purpose {
            return Err("finite owner response purpose".into());
        }
        value.publication()?;
    }
    Ok(value)
}
fn encode_hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn decode_hex(value: &str, maximum: usize) -> WireResult<Vec<u8>> {
    if value.is_empty()
        || value.len() > 2 * maximum
        || !value.len().is_multiple_of(2)
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("finite owner whole lowercase byte bound".into());
    }
    Ok(value
        .as_bytes()
        .chunks_exact(2)
        .map(|p| {
            let digit = |b: u8| {
                if b.is_ascii_digit() {
                    b - b'0'
                } else {
                    b - b'a' + 10
                }
            };
            digit(p[0]) * 16 + digit(p[1])
        })
        .collect())
}
