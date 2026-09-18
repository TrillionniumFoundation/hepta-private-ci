use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::IdProfileV1;
use crate::StableId;
use crate::identity::validate_id_profile_raw;

pub const MAX_CANONICAL_BYTES_V1: usize = 262_144;
pub const MAX_CANONICAL_CONTAINER_ITEMS_V1: usize = 4_096;
pub const MAX_CANONICAL_DEPTH_V1: usize = 16;

const MAGIC: [u8; 4] = *b"HPTC";
const ENCODING_VERSION: u16 = 1;
const DOMAIN: &[u8] = b"hepta.platform.types.canonical-digest.v1";
const MAX_LABEL_BYTES: usize = 128;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalFieldV1<'a> {
    pub name: &'a str,
    pub value: CanonicalValueV1<'a>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalMapEntryV1<'a> {
    pub key: &'a str,
    pub value: CanonicalValueV1<'a>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalValueV1<'a> {
    Bool(bool),
    U64(u64),
    U128(u128),
    I64(i64),
    Bytes(&'a [u8]),
    Text(&'a str),
    Digest(Digest32),
    StableId(&'a StableId),
    Array(&'a [CanonicalValueV1<'a>]),
    Map(&'a [CanonicalMapEntryV1<'a>]),
}

/// Returns the exact V1 bytes hashed by `canonical_digest_v1`.
pub fn canonical_encode_v1(
    type_id: &StableId,
    schema_version: u32,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<Vec<u8>, CanonicalDigestError> {
    if schema_version == 0 {
        return Err(CanonicalDigestError::InvalidSchemaVersion);
    }
    validate_id_profile_raw(type_id.as_str(), IdProfileV1::Namespaced)
        .map_err(|_| CanonicalDigestError::InvalidTypeId)?;
    if fields.len() > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
        return Err(CanonicalDigestError::TooManyItems);
    }

    let mut output = Vec::new();
    append(&mut output, &MAGIC)?;
    append_u16(&mut output, ENCODING_VERSION)?;
    append_len_u16(&mut output, DOMAIN)?;
    append_len_u16(&mut output, type_id.as_str().as_bytes())?;
    append_u32(&mut output, schema_version)?;
    append_u32(
        &mut output,
        u32::try_from(fields.len()).map_err(|_| CanonicalDigestError::TooManyItems)?,
    )?;

    let mut ordered: Vec<&CanonicalFieldV1<'_>> = fields.iter().collect();
    ordered.sort_unstable_by(|left, right| left.name.as_bytes().cmp(right.name.as_bytes()));
    let mut previous: Option<&[u8]> = None;
    for field in ordered {
        validate_label(field.name)?;
        if previous == Some(field.name.as_bytes()) {
            return Err(CanonicalDigestError::DuplicateField);
        }
        previous = Some(field.name.as_bytes());
        append_len_u16(&mut output, field.name.as_bytes())?;
        encode_value(field.value, &mut output, 0)?;
    }
    Ok(output)
}

/// Domain-separated, length-framed canonical SHA-256 digest.
pub fn canonical_digest_v1(
    type_id: &StableId,
    schema_version: u32,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<Digest32, CanonicalDigestError> {
    canonical_encode_v1(type_id, schema_version, fields)
        .map(|encoded| Digest32::of_bytes(&encoded))
}

fn encode_value(
    value: CanonicalValueV1<'_>,
    output: &mut Vec<u8>,
    depth: usize,
) -> Result<(), CanonicalDigestError> {
    if depth > MAX_CANONICAL_DEPTH_V1 {
        return Err(CanonicalDigestError::DepthExceeded);
    }
    match value {
        CanonicalValueV1::Bool(value) => {
            append_u8(output, 0x01)?;
            append_u8(output, u8::from(value))
        }
        CanonicalValueV1::U64(value) => {
            append_u8(output, 0x02)?;
            append(output, &value.to_be_bytes())
        }
        CanonicalValueV1::U128(value) => {
            append_u8(output, 0x03)?;
            append(output, &value.to_be_bytes())
        }
        CanonicalValueV1::I64(value) => {
            append_u8(output, 0x04)?;
            append(output, &value.to_be_bytes())
        }
        CanonicalValueV1::Bytes(value) => {
            append_u8(output, 0x05)?;
            append_len_u32(output, value)
        }
        CanonicalValueV1::Text(value) => {
            if value.contains('\0') {
                return Err(CanonicalDigestError::InvalidText);
            }
            append_u8(output, 0x06)?;
            append_len_u32(output, value.as_bytes())
        }
        CanonicalValueV1::Digest(value) => {
            append_u8(output, 0x07)?;
            append(output, value.as_array())
        }
        CanonicalValueV1::StableId(value) => {
            append_u8(output, 0x08)?;
            append_len_u16(output, value.as_str().as_bytes())
        }
        CanonicalValueV1::Array(values) => {
            if values.len() > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
                return Err(CanonicalDigestError::TooManyItems);
            }
            append_u8(output, 0x09)?;
            append_u32(
                output,
                u32::try_from(values.len()).map_err(|_| CanonicalDigestError::TooManyItems)?,
            )?;
            for value in values {
                encode_value(*value, output, depth + 1)?;
            }
            Ok(())
        }
        CanonicalValueV1::Map(entries) => {
            if entries.len() > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
                return Err(CanonicalDigestError::TooManyItems);
            }
            append_u8(output, 0x0a)?;
            append_u32(
                output,
                u32::try_from(entries.len()).map_err(|_| CanonicalDigestError::TooManyItems)?,
            )?;
            let mut ordered: Vec<&CanonicalMapEntryV1<'_>> = entries.iter().collect();
            ordered.sort_unstable_by(|left, right| left.key.as_bytes().cmp(right.key.as_bytes()));
            let mut previous: Option<&[u8]> = None;
            for entry in ordered {
                validate_label(entry.key)?;
                if previous == Some(entry.key.as_bytes()) {
                    return Err(CanonicalDigestError::DuplicateMapKey);
                }
                previous = Some(entry.key.as_bytes());
                append_len_u16(output, entry.key.as_bytes())?;
                encode_value(entry.value, output, depth + 1)?;
            }
            Ok(())
        }
    }
}

fn validate_label(value: &str) -> Result<(), CanonicalDigestError> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || bytes.len() > MAX_LABEL_BYTES
        || !bytes[0].is_ascii_alphanumeric()
        || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        || bytes.iter().any(|byte| {
            !(byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'.' | b'_' | b'-' | b':'))
        })
    {
        return Err(CanonicalDigestError::InvalidLabel);
    }
    Ok(())
}

fn append(output: &mut Vec<u8>, value: &[u8]) -> Result<(), CanonicalDigestError> {
    let length = output
        .len()
        .checked_add(value.len())
        .ok_or(CanonicalDigestError::TooLarge)?;
    if length > MAX_CANONICAL_BYTES_V1 {
        return Err(CanonicalDigestError::TooLarge);
    }
    output.extend_from_slice(value);
    Ok(())
}

fn append_u8(output: &mut Vec<u8>, value: u8) -> Result<(), CanonicalDigestError> {
    append(output, &[value])
}

fn append_u16(output: &mut Vec<u8>, value: u16) -> Result<(), CanonicalDigestError> {
    append(output, &value.to_be_bytes())
}

fn append_u32(output: &mut Vec<u8>, value: u32) -> Result<(), CanonicalDigestError> {
    append(output, &value.to_be_bytes())
}

fn append_len_u16(output: &mut Vec<u8>, value: &[u8]) -> Result<(), CanonicalDigestError> {
    let length = u16::try_from(value.len()).map_err(|_| CanonicalDigestError::TooLarge)?;
    append_u16(output, length)?;
    append(output, value)
}

fn append_len_u32(output: &mut Vec<u8>, value: &[u8]) -> Result<(), CanonicalDigestError> {
    let length = u32::try_from(value.len()).map_err(|_| CanonicalDigestError::TooLarge)?;
    append_u32(output, length)?;
    append(output, value)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalDigestError {
    InvalidSchemaVersion,
    InvalidTypeId,
    InvalidLabel,
    InvalidText,
    DuplicateField,
    DuplicateMapKey,
    TooManyItems,
    DepthExceeded,
    TooLarge,
}

impl fmt::Display for CanonicalDigestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CanonicalDigestError {}

#[cfg(test)]
#[path = "canonical_digest_tests.rs"]
mod tests;
