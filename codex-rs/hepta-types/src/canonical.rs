use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::StableId;

pub const MAX_CANONICAL_BYTES_V1: usize = 256 * 1024;
pub const MAX_CANONICAL_DEPTH_V1: usize = 32;
pub const MAX_CANONICAL_FIELDS_V1: usize = 1024;

const DOMAIN_V1: &[u8] = b"hepta.canonical-digest.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalValueV1 {
    Bool(bool),
    U64(u64),
    I64(i64),
    Bytes(Vec<u8>),
    Text(String),
    Digest(Digest32),
    Array(Vec<CanonicalValueV1>),
    Map(BTreeMap<String, CanonicalValueV1>),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalFieldV1 {
    pub name: String,
    pub value: CanonicalValueV1,
}

impl CanonicalFieldV1 {
    pub fn new(name: impl Into<String>, value: CanonicalValueV1) -> Self {
        Self {
            name: name.into(),
            value,
        }
    }
}

pub fn canonical_digest_v1(
    type_id: &str,
    schema_version: u32,
    fields: &[CanonicalFieldV1],
) -> Result<Digest32, CanonicalDigestError> {
    if schema_version == 0 {
        return Err(CanonicalDigestError::ZeroSchemaVersion);
    }
    StableId::parse(type_id).map_err(|_| CanonicalDigestError::InvalidTypeId)?;
    if fields.len() > MAX_CANONICAL_FIELDS_V1 {
        return Err(CanonicalDigestError::TooManyFields(fields.len()));
    }

    let mut ordered: Vec<&CanonicalFieldV1> = fields.iter().collect();
    ordered.sort_by(|left, right| left.name.as_bytes().cmp(right.name.as_bytes()));
    for pair in ordered.windows(2) {
        if pair[0].name == pair[1].name {
            return Err(CanonicalDigestError::DuplicateField);
        }
    }

    let mut encoder = EncoderV1::new();
    encoder.push(DOMAIN_V1)?;
    encoder.frame(type_id.as_bytes())?;
    encoder.push(&schema_version.to_be_bytes())?;
    encoder.push_len(ordered.len())?;
    for field in ordered {
        StableId::parse(&field.name).map_err(|_| CanonicalDigestError::InvalidFieldName)?;
        encoder.frame(field.name.as_bytes())?;
        encode_value(&mut encoder, &field.value, 0)?;
    }
    Ok(Digest32::of_bytes(&encoder.bytes))
}

fn encode_value(
    encoder: &mut EncoderV1,
    value: &CanonicalValueV1,
    depth: usize,
) -> Result<(), CanonicalDigestError> {
    if depth > MAX_CANONICAL_DEPTH_V1 {
        return Err(CanonicalDigestError::TooDeep);
    }
    match value {
        CanonicalValueV1::Bool(value) => {
            encoder.push(&[1, u8::from(*value)])?;
        }
        CanonicalValueV1::U64(value) => {
            encoder.push(&[2])?;
            encoder.push(&value.to_be_bytes())?;
        }
        CanonicalValueV1::I64(value) => {
            encoder.push(&[3])?;
            encoder.push(&value.to_be_bytes())?;
        }
        CanonicalValueV1::Bytes(value) => {
            encoder.push(&[4])?;
            encoder.frame(value)?;
        }
        CanonicalValueV1::Text(value) => {
            encoder.push(&[5])?;
            encoder.frame(value.as_bytes())?;
        }
        CanonicalValueV1::Digest(value) => {
            encoder.push(&[6])?;
            encoder.push(value.as_array())?;
        }
        CanonicalValueV1::Array(values) => {
            encoder.push(&[7])?;
            encoder.push_len(values.len())?;
            for value in values {
                encode_value(encoder, value, depth + 1)?;
            }
        }
        CanonicalValueV1::Map(values) => {
            if values.len() > MAX_CANONICAL_FIELDS_V1 {
                return Err(CanonicalDigestError::TooManyFields(values.len()));
            }
            encoder.push(&[8])?;
            encoder.push_len(values.len())?;
            for (name, value) in values {
                StableId::parse(name).map_err(|_| CanonicalDigestError::InvalidFieldName)?;
                encoder.frame(name.as_bytes())?;
                encode_value(encoder, value, depth + 1)?;
            }
        }
    }
    Ok(())
}

struct EncoderV1 {
    bytes: Vec<u8>,
}

impl EncoderV1 {
    fn new() -> Self {
        Self {
            bytes: Vec::with_capacity(256),
        }
    }

    fn push(&mut self, bytes: &[u8]) -> Result<(), CanonicalDigestError> {
        let next = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .ok_or(CanonicalDigestError::TooLarge)?;
        if next > MAX_CANONICAL_BYTES_V1 {
            return Err(CanonicalDigestError::TooLarge);
        }
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }

    fn push_len(&mut self, length: usize) -> Result<(), CanonicalDigestError> {
        let length = u32::try_from(length).map_err(|_| CanonicalDigestError::TooLarge)?;
        self.push(&length.to_be_bytes())
    }

    fn frame(&mut self, bytes: &[u8]) -> Result<(), CanonicalDigestError> {
        self.push_len(bytes.len())?;
        self.push(bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalDigestError {
    InvalidTypeId,
    InvalidFieldName,
    ZeroSchemaVersion,
    DuplicateField,
    TooManyFields(usize),
    TooDeep,
    TooLarge,
}

impl fmt::Display for CanonicalDigestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidTypeId => formatter.write_str("canonical type id is invalid"),
            Self::InvalidFieldName => formatter.write_str("canonical field name is invalid"),
            Self::ZeroSchemaVersion => formatter.write_str("canonical schema version must be non-zero"),
            Self::DuplicateField => formatter.write_str("canonical fields contain a duplicate name"),
            Self::TooManyFields(count) => write!(formatter, "canonical field count exceeds limit: {count}"),
            Self::TooDeep => formatter.write_str("canonical value nesting exceeds limit"),
            Self::TooLarge => formatter.write_str("canonical encoding exceeds size limit"),
        }
    }
}

impl Error for CanonicalDigestError {}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
