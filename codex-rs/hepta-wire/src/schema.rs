use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::EnvelopeView;
use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireVersion;

pub type SchemaValidator = fn(&[u8]) -> Result<(), SchemaValidationError>;

#[derive(Clone)]
pub struct SchemaDefinition {
    schema: StableId,
    min_version: WireVersion,
    max_version: WireVersion,
    max_payload_bytes: usize,
    validator: SchemaValidator,
}

impl SchemaDefinition {
    pub fn new(
        schema: StableId,
        min_version: WireVersion,
        max_version: WireVersion,
        max_payload_bytes: usize,
        validator: SchemaValidator,
    ) -> Result<Self, SchemaRegistrationError> {
        if min_version > max_version {
            return Err(SchemaRegistrationError::InvalidVersionRange);
        }
        if max_payload_bytes == 0 || max_payload_bytes > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaRegistrationError::InvalidPayloadLimit);
        }
        Ok(Self {
            schema,
            min_version,
            max_version,
            max_payload_bytes,
            validator,
        })
    }

    pub fn schema(&self) -> &StableId {
        &self.schema
    }
}

#[derive(Default)]
pub struct SchemaRegistry {
    schemas: BTreeMap<StableId, SchemaDefinition>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(
        &mut self,
        definition: SchemaDefinition,
    ) -> Result<(), SchemaRegistrationError> {
        if self.schemas.contains_key(definition.schema()) {
            return Err(SchemaRegistrationError::DuplicateSchema);
        }
        self.schemas
            .insert(definition.schema().clone(), definition);
        Ok(())
    }

    pub fn admit<'a, E: EnvelopeView>(
        &self,
        envelope: &'a E,
    ) -> Result<AdmittedPayload<'a>, SchemaAdmissionError> {
        let Some(definition) = self.schemas.get(envelope.schema()) else {
            return Err(SchemaAdmissionError::UnknownSchema(
                envelope.schema().clone(),
            ));
        };
        let wire_version = WireVersion::try_from(envelope.wire_version())
            .map_err(|_| SchemaAdmissionError::UnsupportedWireVersion(envelope.wire_version()))?;
        if wire_version < definition.min_version || wire_version > definition.max_version {
            return Err(SchemaAdmissionError::VersionNotAllowed {
                schema: envelope.schema().clone(),
                version: wire_version,
            });
        }
        if envelope.payload().is_empty() || envelope.payload().len() > definition.max_payload_bytes {
            return Err(SchemaAdmissionError::PayloadOutsideSchemaLimit);
        }
        (definition.validator)(envelope.payload()).map_err(SchemaAdmissionError::Validation)?;
        Ok(AdmittedPayload {
            wire_version,
            schema: envelope.schema(),
            producer: envelope.producer(),
            generation: envelope.generation(),
            payload: envelope.payload(),
        })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct AdmittedPayload<'a> {
    wire_version: WireVersion,
    schema: &'a StableId,
    producer: &'a StableId,
    generation: Generation,
    payload: &'a [u8],
}

impl<'a> AdmittedPayload<'a> {
    pub const fn wire_version(&self) -> WireVersion {
        self.wire_version
    }

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

    pub fn decode_with<C: PayloadCodec>(
        &self,
        codec: &C,
    ) -> Result<C::Value, TypedPayloadError> {
        if codec.schema() != self.schema {
            return Err(TypedPayloadError::SchemaMismatch {
                expected: codec.schema().clone(),
                observed: self.schema.clone(),
            });
        }
        codec
            .decode(self.payload)
            .map_err(TypedPayloadError::Codec)
    }
}

pub trait PayloadCodec {
    type Value;

    fn schema(&self) -> &StableId;

    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError>;

    fn decode(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError>;
}

/// Encode a typed payload directly into a V2 frame. Producers still need to
/// register and validate their schema before publication.
pub fn encode_typed_v2<C: PayloadCodec>(
    codec: &C,
    producer: StableId,
    generation: Generation,
    value: &C::Value,
) -> Result<WireEnvelopeV2, TypedEncodeError> {
    let payload = codec.encode(value).map_err(TypedEncodeError::Codec)?;
    WireEnvelopeV2::new(codec.schema().clone(), producer, generation, payload)
        .map_err(TypedEncodeError::Wire)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchemaValidationError {
    message: String,
}

impl SchemaValidationError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for SchemaValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for SchemaValidationError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SchemaRegistrationError {
    InvalidVersionRange,
    InvalidPayloadLimit,
    DuplicateSchema,
}

impl fmt::Display for SchemaRegistrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidVersionRange => formatter.write_str("schema version range is invalid"),
            Self::InvalidPayloadLimit => formatter.write_str("schema payload limit is invalid"),
            Self::DuplicateSchema => formatter.write_str("schema is already registered"),
        }
    }
}

impl Error for SchemaRegistrationError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaAdmissionError {
    UnknownSchema(StableId),
    UnsupportedWireVersion(u16),
    VersionNotAllowed {
        schema: StableId,
        version: WireVersion,
    },
    PayloadOutsideSchemaLimit,
    Validation(SchemaValidationError),
}

impl fmt::Display for SchemaAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownSchema(schema) => write!(formatter, "unknown schema {schema}"),
            Self::UnsupportedWireVersion(version) => {
                write!(formatter, "unsupported wire version {version}")
            }
            Self::VersionNotAllowed { schema, version } => {
                write!(
                    formatter,
                    "wire version {} is not allowed for schema {schema}",
                    version.as_u16()
                )
            }
            Self::PayloadOutsideSchemaLimit => {
                formatter.write_str("payload is outside the registered schema limit")
            }
            Self::Validation(error) => write!(formatter, "schema validation failed: {error}"),
        }
    }
}

impl Error for SchemaAdmissionError {}

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
pub enum TypedPayloadError {
    SchemaMismatch {
        expected: StableId,
        observed: StableId,
    },
    Codec(PayloadCodecError),
}

impl fmt::Display for TypedPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::SchemaMismatch { expected, observed } => {
                write!(
                    formatter,
                    "codec schema {expected} does not match admitted schema {observed}"
                )
            }
            Self::Codec(error) => error.fmt(formatter),
        }
    }
}

impl Error for TypedPayloadError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedEncodeError {
    Codec(PayloadCodecError),
    Wire(WireError),
}

impl fmt::Display for TypedEncodeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Codec(error) => error.fmt(formatter),
            Self::Wire(error) => error.fmt(formatter),
        }
    }
}

impl Error for TypedEncodeError {}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Generation;

    use super::*;

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    struct TinyMessage {
        step: u8,
    }

    struct TinyCodec {
        schema: StableId,
    }

    impl TinyCodec {
        fn new() -> Self {
            Self {
                schema: StableId::new("wire.tiny.v2").expect("schema"),
            }
        }
    }

    impl PayloadCodec for TinyCodec {
        type Value = TinyMessage;

        fn schema(&self) -> &StableId {
            &self.schema
        }

        fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, PayloadCodecError> {
            Ok(vec![1, value.step])
        }

        fn decode(&self, payload: &[u8]) -> Result<Self::Value, PayloadCodecError> {
            if payload.len() != 2 || payload[0] != 1 {
                return Err(PayloadCodecError::new("unknown or malformed required field"));
            }
            Ok(TinyMessage { step: payload[1] })
        }
    }

    fn validate_tiny(payload: &[u8]) -> Result<(), SchemaValidationError> {
        if payload.len() == 2 && payload[0] == 1 {
            Ok(())
        } else {
            Err(SchemaValidationError::new(
                "unknown or malformed required field",
            ))
        }
    }

    fn registry() -> SchemaRegistry {
        let mut registry = SchemaRegistry::new();
        registry
            .register(
                SchemaDefinition::new(
                    StableId::new("wire.tiny.v2").expect("schema"),
                    WireVersion::V2,
                    WireVersion::V2,
                    2,
                    validate_tiny,
                )
                .expect("definition"),
            )
            .expect("register");
        registry
    }

    #[test]
    fn registered_schema_admits_and_decodes_typed_payload() {
        let codec = TinyCodec::new();
        let envelope = encode_typed_v2(
            &codec,
            StableId::new("producer").expect("producer"),
            Generation::new(1).expect("generation"),
            &TinyMessage { step: 7 },
        )
        .expect("encode");
        let registry = registry();
        let admitted = registry.admit(&envelope).expect("admit");
        assert_eq!(
            admitted.decode_with(&codec).expect("decode"),
            TinyMessage { step: 7 }
        );
    }

    #[test]
    fn unknown_schema_and_unknown_required_field_reject() {
        let registry = registry();
        let unknown = WireEnvelopeV2::new(
            StableId::new("wire.unknown.v2").expect("schema"),
            StableId::new("producer").expect("producer"),
            Generation::new(1).expect("generation"),
            vec![1, 7],
        )
        .expect("envelope");
        assert!(matches!(
            registry.admit(&unknown),
            Err(SchemaAdmissionError::UnknownSchema(_))
        ));

        let malformed = WireEnvelopeV2::new(
            StableId::new("wire.tiny.v2").expect("schema"),
            StableId::new("producer").expect("producer"),
            Generation::new(1).expect("generation"),
            vec![2, 7],
        )
        .expect("envelope");
        assert!(matches!(
            registry.admit(&malformed),
            Err(SchemaAdmissionError::Validation(_))
        ));
    }
}
