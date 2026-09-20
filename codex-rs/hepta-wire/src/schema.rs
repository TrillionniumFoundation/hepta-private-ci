use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

use crate::MAX_WIRE_PAYLOAD_BYTES;
use crate::WireVersion;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchemaDescriptor {
    schema: StableId,
    min_version: WireVersion,
    max_version: WireVersion,
    max_payload_bytes: usize,
}

impl SchemaDescriptor {
    pub fn new(
        schema: StableId,
        min_version: WireVersion,
        max_version: WireVersion,
        max_payload_bytes: usize,
    ) -> Result<Self, SchemaAdmissionError> {
        if min_version > max_version {
            return Err(SchemaAdmissionError::InvalidVersionRange);
        }
        if max_payload_bytes == 0 || max_payload_bytes > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaAdmissionError::InvalidPayloadLimit(max_payload_bytes));
        }
        Ok(Self {
            schema,
            min_version,
            max_version,
            max_payload_bytes,
        })
    }

    pub fn schema(&self) -> &StableId {
        &self.schema
    }

    pub const fn min_version(&self) -> WireVersion {
        self.min_version
    }

    pub const fn max_version(&self) -> WireVersion {
        self.max_version
    }

    pub const fn max_payload_bytes(&self) -> usize {
        self.max_payload_bytes
    }

    pub const fn supports_version(&self, version: WireVersion) -> bool {
        self.min_version as u16 <= version as u16 && version as u16 <= self.max_version as u16
    }
}

/// Explicit schema admission registry.
///
/// This registry owns no domain state. It only binds a stable schema identity
/// to supported wire versions and payload bounds. Semantic field validation is
/// delegated to a typed PayloadCodec after admission.
#[derive(Clone, Debug, Default)]
pub struct SchemaRegistry {
    schemas: BTreeMap<StableId, SchemaDescriptor>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self, descriptor: SchemaDescriptor) -> Result<(), SchemaAdmissionError> {
        if let Some(existing) = self.schemas.get(descriptor.schema()) {
            if existing == &descriptor {
                return Ok(());
            }
            return Err(SchemaAdmissionError::ConflictingRegistration(
                descriptor.schema().clone(),
            ));
        }
        self.schemas.insert(descriptor.schema().clone(), descriptor);
        Ok(())
    }

    pub fn descriptor(&self, schema: &StableId) -> Option<&SchemaDescriptor> {
        self.schemas.get(schema)
    }

    pub fn admit(
        &self,
        version: WireVersion,
        schema: &StableId,
        payload: &[u8],
    ) -> Result<&SchemaDescriptor, SchemaAdmissionError> {
        let descriptor = self
            .schemas
            .get(schema)
            .ok_or_else(|| SchemaAdmissionError::UnknownSchema(schema.clone()))?;
        if !descriptor.supports_version(version) {
            return Err(SchemaAdmissionError::UnsupportedSchemaVersion {
                schema: schema.clone(),
                version,
            });
        }
        if payload.is_empty() || payload.len() > descriptor.max_payload_bytes {
            return Err(SchemaAdmissionError::PayloadLength {
                schema: schema.clone(),
                length: payload.len(),
                maximum: descriptor.max_payload_bytes,
            });
        }
        Ok(descriptor)
    }
}

/// Typed payload codec layered above transport-neutral frame parsing.
///
/// Implementations are responsible for canonical field encoding and for
/// rejecting missing required fields and unknown critical fields. The registry
/// is checked before decode so an unregistered schema never reaches domain
/// deserialization.
pub trait PayloadCodec {
    type Value;

    fn descriptor(&self) -> &SchemaDescriptor;

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError>;

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError>;
}

pub fn encode_typed<C: PayloadCodec>(
    registry: &SchemaRegistry,
    version: WireVersion,
    codec: &C,
    value: &C::Value,
) -> Result<Vec<u8>, SchemaCodecError> {
    require_registered_descriptor(registry, codec.descriptor())?;
    let payload = codec.encode_value(value)?;
    registry
        .admit(version, codec.descriptor().schema(), &payload)
        .map_err(SchemaCodecError::Admission)?;
    Ok(payload)
}

pub fn decode_typed<C: PayloadCodec>(
    registry: &SchemaRegistry,
    version: WireVersion,
    schema: &StableId,
    codec: &C,
    payload: &[u8],
) -> Result<C::Value, SchemaCodecError> {
    let admitted = registry
        .admit(version, schema, payload)
        .map_err(SchemaCodecError::Admission)?;
    if admitted != codec.descriptor() {
        return Err(SchemaCodecError::DescriptorMismatch);
    }
    codec.decode_value(payload)
}

fn require_registered_descriptor(
    registry: &SchemaRegistry,
    descriptor: &SchemaDescriptor,
) -> Result<(), SchemaCodecError> {
    let Some(registered) = registry.descriptor(descriptor.schema()) else {
        return Err(SchemaCodecError::Admission(
            SchemaAdmissionError::UnknownSchema(descriptor.schema().clone()),
        ));
    };
    if registered != descriptor {
        return Err(SchemaCodecError::DescriptorMismatch);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaAdmissionError {
    InvalidVersionRange,
    InvalidPayloadLimit(usize),
    UnknownSchema(StableId),
    ConflictingRegistration(StableId),
    UnsupportedSchemaVersion {
        schema: StableId,
        version: WireVersion,
    },
    PayloadLength {
        schema: StableId,
        length: usize,
        maximum: usize,
    },
}

impl fmt::Display for SchemaAdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidVersionRange => formatter.write_str("schema wire version range is invalid"),
            Self::InvalidPayloadLimit(limit) => {
                write!(formatter, "schema payload limit is invalid: {limit}")
            }
            Self::UnknownSchema(schema) => write!(formatter, "unknown wire schema {schema}"),
            Self::ConflictingRegistration(schema) => {
                write!(formatter, "conflicting wire schema registration for {schema}")
            }
            Self::UnsupportedSchemaVersion { schema, version } => write!(
                formatter,
                "schema {schema} does not admit wire version {}",
                version.as_u16()
            ),
            Self::PayloadLength {
                schema,
                length,
                maximum,
            } => write!(
                formatter,
                "schema {schema} payload length {length} is outside 1..={maximum}"
            ),
        }
    }
}

impl Error for SchemaAdmissionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaCodecError {
    Admission(SchemaAdmissionError),
    DescriptorMismatch,
    Rejected(&'static str),
}

impl fmt::Display for SchemaCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Admission(error) => error.fmt(formatter),
            Self::DescriptorMismatch => {
                formatter.write_str("payload codec descriptor does not match registered schema")
            }
            Self::Rejected(reason) => write!(formatter, "typed payload rejected: {reason}"),
        }
    }
}

impl Error for SchemaCodecError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "schema_tests.rs"]
mod tests;
