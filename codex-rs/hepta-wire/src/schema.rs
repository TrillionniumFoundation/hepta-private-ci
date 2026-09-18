use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;

pub const MAX_REGISTERED_WIRE_SCHEMAS: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SchemaValidationError {
    code: &'static str,
}

impl SchemaValidationError {
    pub const fn new(code: &'static str) -> Self {
        Self { code }
    }

    pub const fn code(self) -> &'static str {
        self.code
    }
}

pub type SchemaValidator = fn(&[u8]) -> Result<(), SchemaValidationError>;

#[derive(Clone)]
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
    ) -> Result<Self, SchemaAdmissionError> {
        if max_payload_bytes == 0 || max_payload_bytes > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaAdmissionError::InvalidPayloadLimit(
                max_payload_bytes,
            ));
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
}

#[derive(Clone, Default)]
pub struct SchemaRegistry {
    rules: Vec<SchemaRule>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self, rule: SchemaRule) -> Result<(), SchemaAdmissionError> {
        if self.rules.len() >= MAX_REGISTERED_WIRE_SCHEMAS {
            return Err(SchemaAdmissionError::RegistryFull);
        }
        if self
            .rules
            .iter()
            .any(|existing| existing.schema == rule.schema)
        {
            return Err(SchemaAdmissionError::DuplicateSchema(rule.schema));
        }
        self.rules.push(rule);
        Ok(())
    }

    pub fn admit_v1<'a>(
        &self,
        envelope: &'a WireEnvelope,
    ) -> Result<AdmittedPayload<'a>, SchemaAdmissionError> {
        self.admit_parts(
            envelope.schema(),
            envelope.producer(),
            envelope.generation(),
            envelope.payload(),
        )
    }

    pub fn admit_v2<'a>(
        &self,
        envelope: &'a WireEnvelopeV2,
    ) -> Result<AdmittedPayload<'a>, SchemaAdmissionError> {
        self.admit_parts(
            envelope.schema(),
            envelope.producer(),
            envelope.generation(),
            envelope.payload(),
        )
    }

    fn admit_parts<'a>(
        &self,
        schema: &'a StableId,
        producer: &'a StableId,
        generation: Generation,
        payload: &'a [u8],
    ) -> Result<AdmittedPayload<'a>, SchemaAdmissionError> {
        let rule = self
            .rules
            .iter()
            .find(|rule| &rule.schema == schema)
            .ok_or_else(|| SchemaAdmissionError::UnknownSchema(schema.clone()))?;
        if payload.len() > rule.max_payload_bytes {
            return Err(SchemaAdmissionError::PayloadTooLarge {
                schema: schema.clone(),
                observed: payload.len(),
                maximum: rule.max_payload_bytes,
            });
        }
        (rule.validator)(payload).map_err(|error| SchemaAdmissionError::Validation {
            schema: schema.clone(),
            code: error.code(),
        })?;
        Ok(AdmittedPayload {
            schema,
            producer,
            generation,
            payload,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdmittedPayload<'a> {
    schema: &'a StableId,
    producer: &'a StableId,
    generation: Generation,
    payload: &'a [u8],
}

impl<'a> AdmittedPayload<'a> {
    pub const fn schema(&self) -> &'a StableId {
        self.schema
    }

    pub const fn producer(&self) -> &'a StableId {
        self.producer
    }

    pub const fn generation(&self) -> Generation {
        self.generation
    }

    pub const fn payload(&self) -> &'a [u8] {
        self.payload
    }
}

pub trait TypedPayload: Sized {
    const SCHEMA_ID: &'static str;
    type Error;

    fn encode_payload(&self) -> Result<Vec<u8>, Self::Error>;
    fn decode_payload(payload: &[u8]) -> Result<Self, Self::Error>;
}

pub fn encode_typed_v1<T: TypedPayload>(
    producer: StableId,
    generation: Generation,
    value: &T,
) -> Result<WireEnvelope, TypedCodecError<T::Error>> {
    let schema = typed_schema::<T>()?;
    let payload = value.encode_payload().map_err(TypedCodecError::Payload)?;
    WireEnvelope::new(schema, producer, generation, payload).map_err(TypedCodecError::WireV1)
}

pub fn decode_typed_v1<T: TypedPayload>(
    envelope: &WireEnvelope,
) -> Result<T, TypedCodecError<T::Error>> {
    ensure_typed_schema::<T>(envelope.schema())?;
    T::decode_payload(envelope.payload()).map_err(TypedCodecError::Payload)
}

pub fn encode_typed_v2<T: TypedPayload>(
    producer: StableId,
    generation: Generation,
    value: &T,
) -> Result<WireEnvelopeV2, TypedCodecError<T::Error>> {
    let schema = typed_schema::<T>()?;
    let payload = value.encode_payload().map_err(TypedCodecError::Payload)?;
    WireEnvelopeV2::new(schema, producer, generation, payload).map_err(TypedCodecError::WireV2)
}

pub fn decode_typed_v2<T: TypedPayload>(
    envelope: &WireEnvelopeV2,
) -> Result<T, TypedCodecError<T::Error>> {
    ensure_typed_schema::<T>(envelope.schema())?;
    T::decode_payload(envelope.payload()).map_err(TypedCodecError::Payload)
}

fn typed_schema<T: TypedPayload>() -> Result<StableId, TypedCodecError<T::Error>> {
    StableId::new(T::SCHEMA_ID).map_err(|_| TypedCodecError::InvalidSchemaId)
}

fn ensure_typed_schema<T: TypedPayload>(
    observed: &StableId,
) -> Result<(), TypedCodecError<T::Error>> {
    let expected = typed_schema::<T>()?;
    if observed != &expected {
        return Err(TypedCodecError::SchemaMismatch {
            expected,
            observed: observed.clone(),
        });
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaAdmissionError {
    InvalidPayloadLimit(usize),
    RegistryFull,
    DuplicateSchema(StableId),
    UnknownSchema(StableId),
    PayloadTooLarge {
        schema: StableId,
        observed: usize,
        maximum: usize,
    },
    Validation {
        schema: StableId,
        code: &'static str,
    },
}

impl fmt::Display for SchemaAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for SchemaAdmissionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedCodecError<E> {
    InvalidSchemaId,
    SchemaMismatch {
        expected: StableId,
        observed: StableId,
    },
    Payload(E),
    WireV1(WireError),
    WireV2(WireV2Error),
}

impl<E: fmt::Debug> fmt::Display for TypedCodecError<E> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl<E: fmt::Debug> Error for TypedCodecError<E> {}

#[cfg(test)]
#[path = "schema_tests.rs"]
mod tests;
