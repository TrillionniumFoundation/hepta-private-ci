use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireVersion;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PayloadCodecError {
    message: &'static str,
}

impl PayloadCodecError {
    pub const fn new(message: &'static str) -> Self {
        Self { message }
    }

    pub const fn message(self) -> &'static str {
        self.message
    }
}

impl fmt::Display for PayloadCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.message)
    }
}

impl Error for PayloadCodecError {}

/// Typed payload contract owned by the domain that defines the schema.
///
/// Implementations are responsible for canonical serialization and must reject
/// missing required fields, unknown critical fields and non-canonical values.
/// `platform.wire` owns only registration/admission and envelope framing.
pub trait WirePayload: Sized {
    const SCHEMA_ID: &'static str;

    fn encode_payload(&self) -> Result<Vec<u8>, PayloadCodecError>;

    fn decode_payload(payload: &[u8]) -> Result<Self, PayloadCodecError>;
}

pub type SchemaValidator = fn(&[u8]) -> Result<(), PayloadCodecError>;

#[derive(Clone)]
struct SchemaRule {
    versions: Vec<WireVersion>,
    max_payload_bytes: usize,
    validator: SchemaValidator,
}

#[derive(Clone, Default)]
pub struct SchemaRegistry {
    rules: BTreeMap<StableId, SchemaRule>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register<T: WirePayload>(
        &mut self,
        versions: &[WireVersion],
        max_payload_bytes: usize,
    ) -> Result<(), SchemaError> {
        let schema = StableId::new(T::SCHEMA_ID).map_err(|_| SchemaError::InvalidSchemaId)?;
        self.register_validator(
            schema,
            versions,
            max_payload_bytes,
            validate_typed::<T>,
        )
    }

    pub fn register_validator(
        &mut self,
        schema: StableId,
        versions: &[WireVersion],
        max_payload_bytes: usize,
        validator: SchemaValidator,
    ) -> Result<(), SchemaError> {
        if self.rules.contains_key(&schema) {
            return Err(SchemaError::DuplicateSchema(schema.to_string()));
        }
        if versions.is_empty() {
            return Err(SchemaError::NoWireVersions);
        }
        if max_payload_bytes == 0 || max_payload_bytes > crate::MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaError::InvalidPayloadLimit);
        }
        let mut versions = versions.to_vec();
        versions.sort();
        versions.dedup();
        self.rules.insert(
            schema,
            SchemaRule {
                versions,
                max_payload_bytes,
                validator,
            },
        );
        Ok(())
    }

    pub fn contains(&self, schema: &StableId) -> bool {
        self.rules.contains_key(schema)
    }

    pub fn admit_v1(&self, envelope: &WireEnvelope) -> Result<(), SchemaError> {
        self.admit(
            WireVersion::V1,
            envelope.schema(),
            envelope.payload(),
        )
    }

    pub fn admit_v2(&self, envelope: &WireEnvelopeV2) -> Result<(), SchemaError> {
        self.admit(
            WireVersion::V2,
            envelope.schema(),
            envelope.payload(),
        )
    }

    pub fn encode_v2<T: WirePayload>(
        &self,
        producer: StableId,
        generation: Generation,
        value: &T,
    ) -> Result<WireEnvelopeV2, SchemaError> {
        let schema = StableId::new(T::SCHEMA_ID).map_err(|_| SchemaError::InvalidSchemaId)?;
        let payload = value.encode_payload().map_err(SchemaError::PayloadRejected)?;
        self.admit(WireVersion::V2, &schema, &payload)?;
        WireEnvelopeV2::new(schema, producer, generation, payload)
            .map_err(|_| SchemaError::EnvelopeRejected)
    }

    pub fn decode_v1<T: WirePayload>(&self, envelope: &WireEnvelope) -> Result<T, SchemaError> {
        self.decode_typed(WireVersion::V1, envelope.schema(), envelope.payload())
    }

    pub fn decode_v2<T: WirePayload>(&self, envelope: &WireEnvelopeV2) -> Result<T, SchemaError> {
        self.decode_typed(WireVersion::V2, envelope.schema(), envelope.payload())
    }

    fn decode_typed<T: WirePayload>(
        &self,
        version: WireVersion,
        observed_schema: &StableId,
        payload: &[u8],
    ) -> Result<T, SchemaError> {
        let expected = StableId::new(T::SCHEMA_ID).map_err(|_| SchemaError::InvalidSchemaId)?;
        if observed_schema != &expected {
            return Err(SchemaError::TypeSchemaMismatch {
                expected: expected.to_string(),
                observed: observed_schema.to_string(),
            });
        }
        self.admit(version, observed_schema, payload)?;
        T::decode_payload(payload).map_err(SchemaError::PayloadRejected)
    }

    fn admit(
        &self,
        version: WireVersion,
        schema: &StableId,
        payload: &[u8],
    ) -> Result<(), SchemaError> {
        let Some(rule) = self.rules.get(schema) else {
            return Err(SchemaError::UnknownSchema(schema.to_string()));
        };
        if !rule.versions.contains(&version) {
            return Err(SchemaError::VersionNotAllowed {
                schema: schema.to_string(),
                version,
            });
        }
        if payload.is_empty() || payload.len() > rule.max_payload_bytes {
            return Err(SchemaError::PayloadOutsideSchemaBounds {
                schema: schema.to_string(),
                length: payload.len(),
                maximum: rule.max_payload_bytes,
            });
        }
        (rule.validator)(payload).map_err(SchemaError::PayloadRejected)
    }
}

fn validate_typed<T: WirePayload>(payload: &[u8]) -> Result<(), PayloadCodecError> {
    T::decode_payload(payload).map(|_| ())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaError {
    InvalidSchemaId,
    DuplicateSchema(String),
    NoWireVersions,
    InvalidPayloadLimit,
    UnknownSchema(String),
    VersionNotAllowed {
        schema: String,
        version: WireVersion,
    },
    PayloadOutsideSchemaBounds {
        schema: String,
        length: usize,
        maximum: usize,
    },
    TypeSchemaMismatch {
        expected: String,
        observed: String,
    },
    PayloadRejected(PayloadCodecError),
    EnvelopeRejected,
}

impl fmt::Display for SchemaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidSchemaId => formatter.write_str("wire schema id is not canonical"),
            Self::DuplicateSchema(schema) => write!(formatter, "wire schema {schema} is already registered"),
            Self::NoWireVersions => formatter.write_str("wire schema must allow at least one wire version"),
            Self::InvalidPayloadLimit => formatter.write_str("wire schema payload limit is outside global bounds"),
            Self::UnknownSchema(schema) => write!(formatter, "wire schema {schema} is not registered"),
            Self::VersionNotAllowed { schema, version } => write!(
                formatter,
                "wire schema {schema} does not allow HPTA version {}",
                version.as_u16()
            ),
            Self::PayloadOutsideSchemaBounds {
                schema,
                length,
                maximum,
            } => write!(
                formatter,
                "wire schema {schema} payload length {length} exceeds schema bound {maximum}"
            ),
            Self::TypeSchemaMismatch { expected, observed } => write!(
                formatter,
                "typed wire schema mismatch: expected {expected}, observed {observed}"
            ),
            Self::PayloadRejected(error) => write!(formatter, "wire payload rejected by schema: {error}"),
            Self::EnvelopeRejected => formatter.write_str("typed wire payload could not be framed"),
        }
    }
}

impl Error for SchemaError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct ExamplePayload {
        step: u32,
        accepted: bool,
    }

    impl WirePayload for ExamplePayload {
        const SCHEMA_ID: &'static str = "hepta.wire.example.v1";

        fn encode_payload(&self) -> Result<Vec<u8>, PayloadCodecError> {
            let mut bytes = Vec::with_capacity(5);
            bytes.extend_from_slice(&self.step.to_be_bytes());
            bytes.push(u8::from(self.accepted));
            Ok(bytes)
        }

        fn decode_payload(payload: &[u8]) -> Result<Self, PayloadCodecError> {
            if payload.len() != 5 {
                return Err(PayloadCodecError::new("example payload length"));
            }
            if payload[4] > 1 {
                return Err(PayloadCodecError::new("example boolean is not canonical"));
            }
            let step = u32::from_be_bytes(
                payload[..4]
                    .try_into()
                    .map_err(|_| PayloadCodecError::new("example step"))?,
            );
            Ok(Self {
                step,
                accepted: payload[4] == 1,
            })
        }
    }

    #[test]
    fn registered_typed_payload_round_trips_through_v2() {
        let mut registry = SchemaRegistry::new();
        registry
            .register::<ExamplePayload>(&[WireVersion::V2], 5)
            .expect("register schema");
        let value = ExamplePayload {
            step: 7,
            accepted: true,
        };
        let envelope = registry
            .encode_v2(
                StableId::new("platform.wire").expect("producer"),
                Generation::new(1).expect("generation"),
                &value,
            )
            .expect("encode typed payload");
        assert_eq!(
            registry.decode_v2::<ExamplePayload>(&envelope),
            Ok(value)
        );
    }

    #[test]
    fn unknown_schema_and_noncanonical_payload_fail_closed() {
        let registry = SchemaRegistry::new();
        let envelope = WireEnvelopeV2::new(
            StableId::new("unknown.schema").expect("schema"),
            StableId::new("producer").expect("producer"),
            Generation::new(1).expect("generation"),
            vec![1],
        )
        .expect("frame");
        assert!(matches!(
            registry.admit_v2(&envelope),
            Err(SchemaError::UnknownSchema(_))
        ));

        let mut registry = SchemaRegistry::new();
        registry
            .register::<ExamplePayload>(&[WireVersion::V2], 5)
            .expect("register schema");
        let invalid = WireEnvelopeV2::new(
            StableId::new(ExamplePayload::SCHEMA_ID).expect("schema"),
            StableId::new("producer").expect("producer"),
            Generation::new(1).expect("generation"),
            vec![0, 0, 0, 1, 2],
        )
        .expect("frame");
        assert!(matches!(
            registry.admit_v2(&invalid),
            Err(SchemaError::PayloadRejected(_))
        ));
    }
}
