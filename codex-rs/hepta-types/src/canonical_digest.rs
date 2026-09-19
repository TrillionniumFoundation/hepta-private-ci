use std::collections::BTreeMap;
use std::error::Error;
use std::fmt;

use crate::BoundedBytes;
use crate::Digest32;
use crate::StableId;

pub const MAX_CANONICAL_BYTES_V1: usize = 256 * 1024;
const MAX_FIELDS_V1: usize = 256;
const MAX_COLLECTION_ITEMS_V1: usize = 4096;
const MAX_NESTING_DEPTH_V1: usize = 8;
const MAX_FIELD_NAME_BYTES_V1: usize = 128;
const MAX_MAP_KEY_BYTES_V1: usize = 256;
const DOMAIN_PREFIX_V1: &[u8] = b"HEPTA-CANONICAL-DIGEST-V1\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalFieldV1<'a> {
    pub name: &'a str,
    pub value: CanonicalValueV1<'a>,
}

impl<'a> CanonicalFieldV1<'a> {
    pub const fn new(name: &'a str, value: CanonicalValueV1<'a>) -> Self {
        Self { name, value }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalMapEntryV1<'a> {
    pub key: &'a str,
    pub value: CanonicalValueV1<'a>,
}

impl<'a> CanonicalMapEntryV1<'a> {
    pub const fn new(key: &'a str, value: CanonicalValueV1<'a>) -> Self {
        Self { key, value }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalValueV1<'a> {
    Bytes(&'a [u8]),
    Text(&'a str),
    U64(u64),
    I64(i64),
    Bool(bool),
    Digest(Digest32),
    Array(&'a [CanonicalValueV1<'a>]),
    Map(&'a [CanonicalMapEntryV1<'a>]),
}

pub fn canonical_digest_v1(
    type_id: &StableId,
    schema_version: u32,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<Digest32, CanonicalDigestError> {
    let encoded = canonical_encode_v1(type_id, schema_version, fields)?;
    Ok(Digest32::of_bytes(encoded.as_slice()))
}

pub fn canonical_encode_v1(
    type_id: &StableId,
    schema_version: u32,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<BoundedBytes<MAX_CANONICAL_BYTES_V1>, CanonicalDigestError> {
    if schema_version == 0 {
        return Err(CanonicalDigestError::ZeroSchemaVersion);
    }
    if fields.len() > MAX_FIELDS_V1 {
        return Err(CanonicalDigestError::TooManyFields);
    }

    let mut encoder = Encoder::new();
    encoder.extend(DOMAIN_PREFIX_V1)?;
    encoder.write_u16_bytes(type_id.as_str().as_bytes())?;
    encoder.extend(&schema_version.to_be_bytes())?;

    let field_count =
        u16::try_from(fields.len()).map_err(|_| CanonicalDigestError::TooManyFields)?;
    encoder.extend(&field_count.to_be_bytes())?;

    let mut ordered = BTreeMap::new();
    for field in fields {
        validate_field_name(field.name)?;
        if ordered.insert(field.name, field.value).is_some() {
            return Err(CanonicalDigestError::DuplicateField);
        }
    }

    for (name, value) in ordered {
        encoder.write_u16_bytes(name.as_bytes())?;
        encoder.write_value(value, 0)?;
    }

    BoundedBytes::new(encoder.bytes).map_err(|_| CanonicalDigestError::SizeLimit)
}

fn validate_field_name(name: &str) -> Result<(), CanonicalDigestError> {
    if name.is_empty()
        || name.len() > MAX_FIELD_NAME_BYTES_V1
        || !name.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-')
        })
    {
        return Err(CanonicalDigestError::InvalidFieldName);
    }
    Ok(())
}

fn validate_map_key(key: &str) -> Result<(), CanonicalDigestError> {
    if key.is_empty() || key.len() > MAX_MAP_KEY_BYTES_V1 || key.contains('\0') {
        return Err(CanonicalDigestError::InvalidMapKey);
    }
    Ok(())
}

struct Encoder {
    bytes: Vec<u8>,
}

impl Encoder {
    fn new() -> Self {
        Self { bytes: Vec::new() }
    }

    fn extend(&mut self, value: &[u8]) -> Result<(), CanonicalDigestError> {
        let next = self
            .bytes
            .len()
            .checked_add(value.len())
            .ok_or(CanonicalDigestError::SizeLimit)?;
        if next > MAX_CANONICAL_BYTES_V1 {
            return Err(CanonicalDigestError::SizeLimit);
        }
        self.bytes.extend_from_slice(value);
        Ok(())
    }

    fn write_u16_bytes(&mut self, value: &[u8]) -> Result<(), CanonicalDigestError> {
        let length =
            u16::try_from(value.len()).map_err(|_| CanonicalDigestError::LengthOverflow)?;
        self.extend(&length.to_be_bytes())?;
        self.extend(value)
    }

    fn write_u32_bytes(&mut self, value: &[u8]) -> Result<(), CanonicalDigestError> {
        let length =
            u32::try_from(value.len()).map_err(|_| CanonicalDigestError::LengthOverflow)?;
        self.extend(&length.to_be_bytes())?;
        self.extend(value)
    }

    fn write_value(
        &mut self,
        value: CanonicalValueV1<'_>,
        depth: usize,
    ) -> Result<(), CanonicalDigestError> {
        if depth > MAX_NESTING_DEPTH_V1 {
            return Err(CanonicalDigestError::NestingDepth);
        }

        match value {
            CanonicalValueV1::Bytes(bytes) => {
                self.extend(&[1])?;
                self.write_u32_bytes(bytes)
            }
            CanonicalValueV1::Text(text) => {
                self.extend(&[2])?;
                self.write_u32_bytes(text.as_bytes())
            }
            CanonicalValueV1::U64(number) => {
                self.extend(&[3])?;
                self.extend(&number.to_be_bytes())
            }
            CanonicalValueV1::I64(number) => {
                self.extend(&[4])?;
                self.extend(&number.to_be_bytes())
            }
            CanonicalValueV1::Bool(value) => {
                self.extend(&[5])?;
                self.extend(&[u8::from(value)])
            }
            CanonicalValueV1::Digest(digest) => {
                self.extend(&[6])?;
                self.extend(digest.as_array())
            }
            CanonicalValueV1::Array(items) => {
                if items.len() > MAX_COLLECTION_ITEMS_V1 {
                    return Err(CanonicalDigestError::TooManyCollectionItems);
                }
                self.extend(&[7])?;
                let count = u32::try_from(items.len())
                    .map_err(|_| CanonicalDigestError::TooManyCollectionItems)?;
                self.extend(&count.to_be_bytes())?;
                for item in items {
                    self.write_value(*item, depth + 1)?;
                }
                Ok(())
            }
            CanonicalValueV1::Map(entries) => {
                if entries.len() > MAX_COLLECTION_ITEMS_V1 {
                    return Err(CanonicalDigestError::TooManyCollectionItems);
                }
                self.extend(&[8])?;
                let count = u32::try_from(entries.len())
                    .map_err(|_| CanonicalDigestError::TooManyCollectionItems)?;
                self.extend(&count.to_be_bytes())?;

                let mut ordered = BTreeMap::new();
                for entry in entries {
                    validate_map_key(entry.key)?;
                    if ordered.insert(entry.key, entry.value).is_some() {
                        return Err(CanonicalDigestError::DuplicateMapKey);
                    }
                }
                for (key, item) in ordered {
                    self.write_u16_bytes(key.as_bytes())?;
                    self.write_value(item, depth + 1)?;
                }
                Ok(())
            }
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalDigestError {
    ZeroSchemaVersion,
    TooManyFields,
    InvalidFieldName,
    DuplicateField,
    InvalidMapKey,
    DuplicateMapKey,
    TooManyCollectionItems,
    NestingDepth,
    SizeLimit,
    LengthOverflow,
}

impl fmt::Display for CanonicalDigestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ZeroSchemaVersion => formatter.write_str("schema version must be non-zero"),
            Self::TooManyFields => formatter.write_str("too many canonical fields"),
            Self::InvalidFieldName => formatter.write_str("invalid canonical field name"),
            Self::DuplicateField => formatter.write_str("duplicate canonical field name"),
            Self::InvalidMapKey => formatter.write_str("invalid canonical map key"),
            Self::DuplicateMapKey => formatter.write_str("duplicate canonical map key"),
            Self::TooManyCollectionItems => {
                formatter.write_str("too many canonical collection items")
            }
            Self::NestingDepth => formatter.write_str("canonical value nesting is too deep"),
            Self::SizeLimit => formatter.write_str("canonical encoding exceeds 256 KiB"),
            Self::LengthOverflow => formatter.write_str("canonical length cannot be represented"),
        }
    }
}

impl Error for CanonicalDigestError {}

#[cfg(test)]
#[path = "canonical_digest_tests.rs"]
mod tests;
