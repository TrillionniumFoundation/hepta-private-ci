use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DecodedEnvelope;
use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;

pub const MAX_REGISTERED_SCHEMAS: usize = 128;
pub const MAX_ADMITTED_PRODUCERS: usize = 128;

pub type SchemaValidator = fn(&[u8]) -> Result<(), PayloadValidationError>;

#[derive(Clone, Debug)]
pub struct SchemaRule {
    schema: StableId,
    max_payload_bytes: usize,
    validator: SchemaValidator,
}

impl SchemaRule {
    pub fn new(
        schema: StableId,
        max_payload_bytes: usize,
        validator: SchemaValidator,
    ) -> Result<Self, SchemaRegistryError> {
        if max_payload_bytes == 0 || max_payload_bytes > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaRegistryError::PayloadLimit);
        }
        Ok(Self {
            schema,
            max_payload_bytes,
            validator,
        })
    }

    pub fn schema(&self) -> &StableId {
        &self.schema
    }

    pub const fn max_payload_bytes(&self) -> usize {
        self.max_payload_bytes
    }
}

#[derive(Clone, Debug, Default)]
pub struct SchemaRegistry {
    rules: BTreeMap<StableId, SchemaRule>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self, rule: SchemaRule) -> Result<(), SchemaRegistryError> {
        if self.rules.len() >= MAX_REGISTERED_SCHEMAS {
            return Err(SchemaRegistryError::SchemaLimitExceeded);
        }
        if self.rules.contains_key(rule.schema()) {
            return Err(SchemaRegistryError::DuplicateSchema(
                rule.schema().to_string(),
            ));
        }
        self.rules.insert(rule.schema.clone(), rule);
        Ok(())
    }

    pub fn get(&self, schema: &StableId) -> Option<&SchemaRule> {
        self.rules.get(schema)
    }

    pub fn len(&self) -> usize {
        self.rules.len()
    }

    pub fn is_empty(&self) -> bool {
        self.rules.is_empty()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProducerAdmission {
    AnyCanonical,
    AllowList(BTreeSet<StableId>),
}

impl ProducerAdmission {
    pub fn allow_list(
        producers: impl IntoIterator<Item = StableId>,
    ) -> Result<Self, AdmissionPolicyError> {
        let producers = producers.into_iter().collect::<BTreeSet<_>>();
        if producers.is_empty() {
            return Err(AdmissionPolicyError::EmptyProducerSet);
        }
        if producers.len() > MAX_ADMITTED_PRODUCERS {
            return Err(AdmissionPolicyError::ProducerLimitExceeded);
        }
        Ok(Self::AllowList(producers))
    }

    fn admits(&self, producer: &StableId) -> bool {
        match self {
            Self::AnyCanonical => true,
            Self::AllowList(producers) => producers.contains(producer),
        }
    }
}

/// Schema and producer admission applied after framing and before domain use.
///
/// Admission proves only that this policy recognizes the producer/schema and
/// that the registered payload validator accepted the bytes. It carries no
/// effect authority.
#[derive(Debug)]
pub struct AdmissionPolicy<'a> {
    registry: &'a SchemaRegistry,
    producers: &'a ProducerAdmission,
}

impl<'a> AdmissionPolicy<'a> {
    pub const fn new(
        registry: &'a SchemaRegistry,
        producers: &'a ProducerAdmission,
    ) -> Self {
        Self {
            registry,
            producers,
        }
    }

    pub fn admit<'e>(
        &self,
        envelope: &'e DecodedEnvelope,
    ) -> Result<AdmittedEnvelope<'e>, AdmissionError> {
        if !self.producers.admits(envelope.producer()) {
            return Err(AdmissionError::ProducerDenied(
                envelope.producer().to_string(),
            ));
        }
        let rule = self
            .registry
            .get(envelope.schema())
            .ok_or_else(|| AdmissionError::UnknownSchema(envelope.schema().to_string()))?;
        if envelope.payload().len() > rule.max_payload_bytes {
            return Err(AdmissionError::PayloadLimitExceeded {
                schema: envelope.schema().to_string(),
                observed: envelope.payload().len(),
                maximum: rule.max_payload_bytes,
            });
        }
        (rule.validator)(envelope.payload()).map_err(AdmissionError::PayloadRejected)?;
        Ok(AdmittedEnvelope {
            version: envelope.version(),
            schema: envelope.schema(),
            producer: envelope.producer(),
            generation: envelope.generation(),
            payload: envelope.payload(),
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdmittedEnvelope<'a> {
    version: WireVersion,
    schema: &'a StableId,
    producer: &'a StableId,
    generation: Generation,
    payload: &'a [u8],
}

impl<'a> AdmittedEnvelope<'a> {
    pub const fn version(self) -> WireVersion {
        self.version
    }

    pub const fn schema(self) -> &'a StableId {
        self.schema
    }

    pub const fn producer(self) -> &'a StableId {
        self.producer
    }

    pub const fn generation(self) -> Generation {
        self.generation
    }

    pub const fn payload(self) -> &'a [u8] {
        self.payload
    }
}

/// Typed payload serialization bound to exactly one stable schema identifier.
pub trait PayloadCodec {
    type Value;

    fn schema(&self) -> &StableId;

    fn encode_payload(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError>;

    fn decode_payload(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedEnvelope<T> {
    pub version: WireVersion,
    pub schema: StableId,
    pub producer: StableId,
    pub generation: Generation,
    pub value: T,
}

pub fn encode_typed<C: PayloadCodec>(
    codec: &C,
    producer: StableId,
    generation: Generation,
    value: &C::Value,
    version: WireVersion,
) -> Result<Vec<u8>, TypedEncodeError> {
    let payload = codec
        .encode_payload(value)
        .map_err(TypedEncodeError::Codec)?;
    match version {
        WireVersion::V1 => WireEnvelope::new(codec.schema().clone(), producer, generation, payload)
            .map(|envelope| envelope.encode())
            .map_err(TypedEncodeError::V1),
        WireVersion::V2 => {
            WireEnvelopeV2::new(codec.schema().clone(), producer, generation, payload)
                .map(|envelope| envelope.encode())
                .map_err(TypedEncodeError::V2)
        }
    }
}

pub fn decode_typed<C: PayloadCodec>(
    codec: &C,
    envelope: AdmittedEnvelope<'_>,
) -> Result<TypedEnvelope<C::Value>, TypedDecodeError> {
    if envelope.schema() != codec.schema() {
        return Err(TypedDecodeError::SchemaMismatch {
            expected: codec.schema().to_string(),
            observed: envelope.schema().to_string(),
        });
    }
    let value = codec
        .decode_payload(envelope.payload())
        .map_err(TypedDecodeError::Codec)?;
    Ok(TypedEnvelope {
        version: envelope.version(),
        schema: envelope.schema().clone(),
        producer: envelope.producer().clone(),
        generation: envelope.generation(),
        value,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PayloadValidationError {
    reason: &'static str,
}

impl PayloadValidationError {
    pub const fn new(reason: &'static str) -> Self {
        Self { reason }
    }
}

impl fmt::Display for PayloadValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.reason)
    }
}

impl Error for PayloadValidationError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaRegistryError {
    PayloadLimit,
    SchemaLimitExceeded,
    DuplicateSchema(String),
}

impl fmt::Display for SchemaRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for SchemaRegistryError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdmissionPolicyError {
    EmptyProducerSet,
    ProducerLimitExceeded,
}

impl fmt::Display for AdmissionPolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for AdmissionPolicyError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdmissionError {
    ProducerDenied(String),
    UnknownSchema(String),
    PayloadLimitExceeded {
        schema: String,
        observed: usize,
        maximum: usize,
    },
    PayloadRejected(PayloadValidationError),
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for AdmissionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PayloadCodecError {
    message: String,
}

impl PayloadCodecError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for PayloadCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for PayloadCodecError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedEncodeError {
    Codec(PayloadCodecError),
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for TypedEncodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for TypedEncodeError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedDecodeError {
    SchemaMismatch {
        expected: String,
        observed: String,
    },
    Codec(PayloadCodecError),
}

impl fmt::Display for TypedDecodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for TypedDecodeError {}

#[cfg(test)]
#[path = "schema_tests.rs"]
mod tests;
