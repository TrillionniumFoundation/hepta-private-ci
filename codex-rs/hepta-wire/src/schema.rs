use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde::de::MapAccess;
use serde::de::SeqAccess;
use serde::de::Visitor;
use serde_json::Map;
use serde_json::Number;
use serde_json::Value;

use crate::WireEnvelopeV2;
use crate::WireV2Error;

pub const MAX_SCHEMA_FIELDS: usize = 1_024;
pub const MAX_JSON_NESTING: usize = 32;
pub const MAX_REGISTERED_SCHEMAS: usize = 256;
const MAX_FIELD_NAME_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UnknownFieldPolicy {
    Reject,
    Allow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchemaDefinition {
    schema: StableId,
    required_fields: BTreeSet<String>,
    optional_fields: BTreeSet<String>,
    unknown_field_policy: UnknownFieldPolicy,
    max_payload_bytes: usize,
}

impl SchemaDefinition {
    pub fn new(
        schema: StableId,
        required_fields: &[&str],
        optional_fields: &[&str],
        unknown_field_policy: UnknownFieldPolicy,
        max_payload_bytes: usize,
    ) -> Result<Self, SchemaError> {
        if max_payload_bytes == 0 || max_payload_bytes > crate::MAX_WIRE_PAYLOAD_BYTES {
            return Err(SchemaError::PayloadLimit);
        }
        if required_fields.len().saturating_add(optional_fields.len()) > MAX_SCHEMA_FIELDS {
            return Err(SchemaError::TooManyFields);
        }

        let required_fields = collect_fields(required_fields)?;
        let optional_fields = collect_fields(optional_fields)?;
        if let Some(overlap) = required_fields.intersection(&optional_fields).next() {
            return Err(SchemaError::RequiredOptionalOverlap(overlap.clone()));
        }

        Ok(Self {
            schema,
            required_fields,
            optional_fields,
            unknown_field_policy,
            max_payload_bytes,
        })
    }

    pub fn schema(&self) -> &StableId {
        &self.schema
    }

    pub fn required_fields(&self) -> &BTreeSet<String> {
        &self.required_fields
    }

    pub fn optional_fields(&self) -> &BTreeSet<String> {
        &self.optional_fields
    }

    pub const fn unknown_field_policy(&self) -> UnknownFieldPolicy {
        self.unknown_field_policy
    }

    pub const fn max_payload_bytes(&self) -> usize {
        self.max_payload_bytes
    }
}

fn collect_fields(fields: &[&str]) -> Result<BTreeSet<String>, SchemaError> {
    let mut output = BTreeSet::new();
    for field in fields {
        validate_field_name(field)?;
        if !output.insert((*field).to_owned()) {
            return Err(SchemaError::DuplicateField((*field).to_owned()));
        }
    }
    Ok(output)
}

fn validate_field_name(field: &str) -> Result<(), SchemaError> {
    if field.is_empty()
        || field.len() > MAX_FIELD_NAME_BYTES
        || !field
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err(SchemaError::InvalidFieldName(field.to_owned()));
    }
    Ok(())
}

#[derive(Clone, Debug, Default)]
pub struct SchemaRegistry {
    schemas: BTreeMap<StableId, SchemaDefinition>,
}

impl SchemaRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn register(&mut self, definition: SchemaDefinition) -> Result<(), SchemaError> {
        let key = definition.schema.clone();
        if self.schemas.contains_key(&key) {
            return Err(SchemaError::DuplicateSchema(key.to_string()));
        }
        if self.schemas.len() >= MAX_REGISTERED_SCHEMAS {
            return Err(SchemaError::RegistryFull);
        }
        self.schemas.insert(key, definition);
        Ok(())
    }

    pub fn definition(&self, schema: &StableId) -> Option<&SchemaDefinition> {
        self.schemas.get(schema)
    }

    pub fn admit(&self, envelope: &WireEnvelopeV2) -> Result<AdmittedPayload, AdmissionError> {
        let definition = self
            .schemas
            .get(envelope.schema())
            .ok_or_else(|| AdmissionError::UnknownSchema(envelope.schema().to_string()))?;
        if envelope.payload().len() > definition.max_payload_bytes {
            return Err(AdmissionError::PayloadTooLarge);
        }

        let mut deserializer = serde_json::Deserializer::from_slice(envelope.payload());
        let value = StrictValue::deserialize(&mut deserializer)
            .map_err(|error| AdmissionError::Json(error.to_string()))?
            .0;
        deserializer
            .end()
            .map_err(|error| AdmissionError::Json(error.to_string()))?;
        let mut field_count = 0_usize;
        validate_json_shape(&value, 1, &mut field_count)?;

        let object = value.as_object().ok_or(AdmissionError::ExpectedObject)?;
        for required in &definition.required_fields {
            if !object.contains_key(required) {
                return Err(AdmissionError::MissingRequiredField(required.clone()));
            }
        }
        if definition.unknown_field_policy == UnknownFieldPolicy::Reject {
            for field in object.keys() {
                if !definition.required_fields.contains(field)
                    && !definition.optional_fields.contains(field)
                {
                    return Err(AdmissionError::UnknownField(field.clone()));
                }
            }
        }

        Ok(AdmittedPayload {
            schema: envelope.schema().clone(),
            value,
        })
    }

    pub fn encode_typed<T: TypedWirePayload>(
        &self,
        producer: StableId,
        generation: Generation,
        value: &T,
    ) -> Result<WireEnvelopeV2, TypedPayloadError> {
        let envelope = encode_typed(producer, generation, value)?;
        self.admit(&envelope)
            .map_err(TypedPayloadError::Admission)?;
        Ok(envelope)
    }

    pub fn decode_typed<T: TypedWirePayload>(
        &self,
        envelope: &WireEnvelopeV2,
    ) -> Result<T, TypedPayloadError> {
        if envelope.schema().as_str() != T::schema_id() {
            return Err(TypedPayloadError::SchemaMismatch {
                expected: T::schema_id().to_owned(),
                observed: envelope.schema().to_string(),
            });
        }
        let admitted = self.admit(envelope).map_err(TypedPayloadError::Admission)?;
        serde_json::from_value(admitted.value)
            .map_err(|error| TypedPayloadError::Decode(error.to_string()))
    }
}

struct StrictValue(Value);

impl<'de> Deserialize<'de> for StrictValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(StrictValueVisitor)
    }
}

struct StrictValueVisitor;

impl<'de> Visitor<'de> for StrictValueVisitor {
    type Value = StrictValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a strict JSON value without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Number::from_f64(value)
            .map(Value::Number)
            .map(StrictValue)
            .ok_or_else(|| E::custom("non-finite JSON number"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Ok(StrictValue(Value::String(value.to_owned())))
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(StrictValue(Value::Null))
    }

    fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: Deserializer<'de>,
    {
        StrictValue::deserialize(deserializer)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<StrictValue>()? {
            values.push(value.0);
        }
        Ok(StrictValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut values = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(serde::de::Error::custom(format!(
                    "duplicate JSON object key {key}"
                )));
            }
            let value = object.next_value::<StrictValue>()?;
            values.insert(key, value.0);
        }
        Ok(StrictValue(Value::Object(values)))
    }
}


fn validate_json_shape(
    value: &Value,
    depth: usize,
    field_count: &mut usize,
) -> Result<(), AdmissionError> {
    if depth > MAX_JSON_NESTING {
        return Err(AdmissionError::NestingTooDeep);
    }
    match value {
        Value::Object(object) => {
            *field_count = field_count
                .checked_add(object.len())
                .ok_or(AdmissionError::FieldCountExceeded)?;
            if *field_count > MAX_SCHEMA_FIELDS {
                return Err(AdmissionError::FieldCountExceeded);
            }
            for nested in object.values() {
                validate_json_shape(nested, depth + 1, field_count)?;
            }
        }
        Value::Array(array) => {
            for nested in array {
                validate_json_shape(nested, depth + 1, field_count)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq)]
pub struct AdmittedPayload {
    pub schema: StableId,
    pub value: Value,
}

pub trait TypedWirePayload: Serialize + DeserializeOwned {
    fn schema_id() -> &'static str;
}

pub fn encode_typed<T: TypedWirePayload>(
    producer: StableId,
    generation: Generation,
    value: &T,
) -> Result<WireEnvelopeV2, TypedPayloadError> {
    let schema =
        StableId::new(T::schema_id()).map_err(|_| TypedPayloadError::InvalidSchemaIdentity)?;
    let value =
        serde_json::to_value(value).map_err(|error| TypedPayloadError::Encode(error.to_string()))?;
    let canonical = canonicalize_json(value);
    let payload = serde_json::to_vec(&canonical)
        .map_err(|error| TypedPayloadError::Encode(error.to_string()))?;
    WireEnvelopeV2::new(schema, producer, generation, payload).map_err(TypedPayloadError::Wire)
}

fn canonicalize_json(value: Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut sorted = BTreeMap::new();
            for (key, nested) in object {
                sorted.insert(key, canonicalize_json(nested));
            }
            let mut canonical = Map::new();
            for (key, nested) in sorted {
                canonical.insert(key, nested);
            }
            Value::Object(canonical)
        }
        Value::Array(array) => {
            Value::Array(array.into_iter().map(canonicalize_json).collect())
        }
        other => other,
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SchemaError {
    TooManyFields,
    InvalidFieldName(String),
    DuplicateField(String),
    RequiredOptionalOverlap(String),
    PayloadLimit,
    RegistryFull,
    DuplicateSchema(String),
}

impl fmt::Display for SchemaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for SchemaError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AdmissionError {
    UnknownSchema(String),
    PayloadTooLarge,
    Json(String),
    ExpectedObject,
    MissingRequiredField(String),
    UnknownField(String),
    NestingTooDeep,
    FieldCountExceeded,
}

impl fmt::Display for AdmissionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for AdmissionError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedPayloadError {
    InvalidSchemaIdentity,
    Schema(SchemaError),
    Admission(AdmissionError),
    SchemaMismatch { expected: String, observed: String },
    Encode(String),
    Decode(String),
    Wire(WireV2Error),
}

impl fmt::Display for TypedPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for TypedPayloadError {}
