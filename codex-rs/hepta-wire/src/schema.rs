use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use codex_hepta_types::StableId;

use crate::MAX_WIRE_PAYLOAD_BYTES;

pub trait SchemaAdmission: Send + Sync {
    fn schema_id(&self) -> &StableId;
    fn max_payload_bytes(&self) -> usize;
    fn validate(&self, payload: &[u8]) -> Result<(), SchemaError>;
}

pub struct StaticSchemaAdmission {
    schema_id: StableId,
    max_payload_bytes: usize,
    validator: fn(&[u8]) -> Result<(), &'static str>,
}

impl StaticSchemaAdmission {
    pub fn new(
        schema_id: StableId,
        max_payload_bytes: usize,
        validator: fn(&[u8]) -> Result<(), &'static str>,
    ) -> Result<Self, SchemaError> {
        if max_payload_bytes == 0 || max_payload_bytes > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaError::InvalidSchemaLimit(max_payload_bytes));
        }
        Ok(Self {
            schema_id,
            max_payload_bytes,
            validator,
        })
    }
}

impl SchemaAdmission for StaticSchemaAdmission {
    fn schema_id(&self) -> &StableId {
        &self.schema_id
    }

    fn max_payload_bytes(&self) -> usize {
        self.max_payload_bytes
    }

    fn validate(&self, payload: &[u8]) -> Result<(), SchemaError> {
        (self.validator)(payload).map_err(|reason| SchemaError::AdmissionRejected {
            schema: self.schema_id.clone(),
            reason: reason.to_owned(),
        })
    }
}

pub trait PayloadCodec {
    type Value;

    fn schema_id(&self) -> &StableId;
    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaError>;
    fn decode(&self, payload: &[u8]) -> Result<Self::Value, SchemaError>;
}

#[derive(Default)]
pub struct SchemaRegistry {
    entries: BTreeMap<StableId, Box<dyn SchemaAdmission>>,
}

impl fmt::Debug for SchemaRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SchemaRegistry")
            .field("schema_count", &self.entries.len())
            .finish()
    }
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(
        &mut self,
        admission: Box<dyn SchemaAdmission>,
    ) -> Result<(), SchemaError> {
        let schema = admission.schema_id().clone();
        let maximum = admission.max_payload_bytes();
        if maximum == 0 || maximum > MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaError::InvalidSchemaLimit(maximum));
        }
        if self.entries.contains_key(&schema) {
            return Err(SchemaError::DuplicateSchema(schema));
        }
        self.entries.insert(schema, admission);
        Ok(())
    }

    pub fn contains(&self, schema: &StableId) -> bool {
        self.entries.contains_key(schema)
    }

    pub fn admit(&self, schema: &StableId, payload: &[u8]) -> Result<(), SchemaError> {
        let admission = self
            .entries
            .get(schema)
            .ok_or_else(|| SchemaError::UnknownSchema(schema.clone()))?;
        if payload.is_empty() || payload.len() > admission.max_payload_bytes() {
            return Err(SchemaError::PayloadLength {
                schema: schema.clone(),
                length: payload.len(),
                maximum: admission.max_payload_bytes(),
            });
        }
        admission.validate(payload)
    }

    pub fn encode_typed<C: PayloadCodec>(
        &self,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, SchemaError> {
        self.require_codec_schema(codec.schema_id())?;
        let payload = codec.encode(value)?;
        self.admit(codec.schema_id(), &payload)?;
        Ok(payload)
    }

    pub fn decode_typed<C: PayloadCodec>(
        &self,
        codec: &C,
        envelope_schema: &StableId,
        payload: &[u8],
    ) -> Result<C::Value, SchemaError> {
        if codec.schema_id() != envelope_schema {
            return Err(SchemaError::CodecSchemaMismatch {
                codec: codec.schema_id().clone(),
                envelope: envelope_schema.clone(),
            });
        }
        self.admit(envelope_schema, payload)?;
        codec.decode(payload)
    }

    fn require_codec_schema(&self, schema: &StableId) -> Result<(), SchemaError> {
        if self.entries.contains_key(schema) {
            Ok(())
        } else {
            Err(SchemaError::UnknownSchema(schema.clone()))
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaError {
    UnknownSchema(StableId),
    DuplicateSchema(StableId),
    InvalidSchemaLimit(usize),
    PayloadLength {
        schema: StableId,
        length: usize,
        maximum: usize,
    },
    AdmissionRejected {
        schema: StableId,
        reason: String,
    },
    CodecSchemaMismatch {
        codec: StableId,
        envelope: StableId,
    },
    CodecRejected {
        schema: StableId,
        reason: String,
    },
}

impl fmt::Display for SchemaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownSchema(schema) => write!(formatter, "unknown wire schema {schema}"),
            Self::DuplicateSchema(schema) => write!(formatter, "duplicate wire schema {schema}"),
            Self::InvalidSchemaLimit(limit) => {
                write!(formatter, "invalid schema payload limit {limit}")
            }
            Self::PayloadLength {
                schema,
                length,
                maximum,
            } => write!(
                formatter,
                "wire schema {schema} payload length {length} exceeds admitted range 1..={maximum}"
            ),
            Self::AdmissionRejected { schema, reason } => {
                write!(formatter, "wire schema {schema} rejected payload: {reason}")
            }
            Self::CodecSchemaMismatch { codec, envelope } => write!(
                formatter,
                "typed codec schema {codec} does not match envelope schema {envelope}"
            ),
            Self::CodecRejected { schema, reason } => {
                write!(formatter, "typed codec {schema} rejected payload: {reason}")
            }
        }
    }
}

impl Error for SchemaError {}
