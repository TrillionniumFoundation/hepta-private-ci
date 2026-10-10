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
    canonical_encode_v1(type_id, schema_version, fields).map(|encoded| Digest32::of_bytes(&encoded))
}

/// Validates exact canonical V1 bytes without constructing domain objects or
/// granting authority. Successful validation returns the SHA-256 digest of the
/// validated byte sequence.
pub fn canonical_validate_v1(encoded: &[u8]) -> Result<Digest32, CanonicalDigestError> {
    if encoded.len() > MAX_CANONICAL_BYTES_V1 {
        return Err(CanonicalDigestError::TooLarge);
    }
    let mut reader = Reader::new(encoded);
    if reader.take(MAGIC.len())? != MAGIC {
        return Err(CanonicalDigestError::InvalidMagic);
    }
    if reader.read_u16()? != ENCODING_VERSION {
        return Err(CanonicalDigestError::InvalidEncodingVersion);
    }
    if reader.read_len_u16()? != DOMAIN {
        return Err(CanonicalDigestError::InvalidDomain);
    }
    let type_id = std::str::from_utf8(reader.read_len_u16()?)
        .map_err(|_| CanonicalDigestError::InvalidTypeId)?;
    validate_id_profile_raw(type_id, IdProfileV1::Namespaced)
        .map_err(|_| CanonicalDigestError::InvalidTypeId)?;
    if reader.read_u32()? == 0 {
        return Err(CanonicalDigestError::InvalidSchemaVersion);
    }
    let field_count =
        usize::try_from(reader.read_u32()?).map_err(|_| CanonicalDigestError::TooManyItems)?;
    if field_count > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
        return Err(CanonicalDigestError::TooManyItems);
    }
    let mut previous: Option<&[u8]> = None;
    for _ in 0..field_count {
        let name_bytes = reader.read_len_u16()?;
        let name =
            std::str::from_utf8(name_bytes).map_err(|_| CanonicalDigestError::InvalidLabel)?;
        validate_label(name)?;
        if let Some(previous) = previous {
            if name_bytes == previous {
                return Err(CanonicalDigestError::DuplicateField);
            }
            if name_bytes < previous {
                return Err(CanonicalDigestError::NonCanonicalOrder);
            }
        }
        previous = Some(name_bytes);
        validate_encoded_value(&mut reader, 0)?;
    }
    if !reader.is_complete() {
        return Err(CanonicalDigestError::TrailingBytes);
    }
    Ok(Digest32::of_bytes(encoded))
}

fn validate_encoded_value(
    reader: &mut Reader<'_>,
    depth: usize,
) -> Result<(), CanonicalDigestError> {
    match reader.read_u8()? {
        0x01 => match reader.read_u8()? {
            0 | 1 => Ok(()),
            _ => Err(CanonicalDigestError::InvalidBool),
        },
        0x02 => reader.take(8).map(|_| ()),
        0x03 => reader.take(16).map(|_| ()),
        0x04 => reader.take(8).map(|_| ()),
        0x05 => reader.read_len_u32().map(|_| ()),
        0x06 => {
            let bytes = reader.read_len_u32()?;
            let text = std::str::from_utf8(bytes).map_err(|_| CanonicalDigestError::InvalidText)?;
            if text.contains('\0') {
                return Err(CanonicalDigestError::InvalidText);
            }
            Ok(())
        }
        0x07 => reader.take(32).map(|_| ()),
        0x08 => {
            let bytes = reader.read_len_u16()?;
            let stable_id =
                std::str::from_utf8(bytes).map_err(|_| CanonicalDigestError::InvalidTypeId)?;
            validate_id_profile_raw(stable_id, IdProfileV1::Stable)
                .map_err(|_| CanonicalDigestError::InvalidTypeId)
        }
        0x09 => {
            if depth >= MAX_CANONICAL_DEPTH_V1 {
                return Err(CanonicalDigestError::DepthExceeded);
            }
            let count = usize::try_from(reader.read_u32()?)
                .map_err(|_| CanonicalDigestError::TooManyItems)?;
            if count > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
                return Err(CanonicalDigestError::TooManyItems);
            }
            for _ in 0..count {
                validate_encoded_value(reader, depth + 1)?;
            }
            Ok(())
        }
        0x0a => {
            if depth >= MAX_CANONICAL_DEPTH_V1 {
                return Err(CanonicalDigestError::DepthExceeded);
            }
            let count = usize::try_from(reader.read_u32()?)
                .map_err(|_| CanonicalDigestError::TooManyItems)?;
            if count > MAX_CANONICAL_CONTAINER_ITEMS_V1 {
                return Err(CanonicalDigestError::TooManyItems);
            }
            let mut previous: Option<&[u8]> = None;
            for _ in 0..count {
                let key_bytes = reader.read_len_u16()?;
                let key = std::str::from_utf8(key_bytes)
                    .map_err(|_| CanonicalDigestError::InvalidLabel)?;
                validate_label(key)?;
                if let Some(previous) = previous {
                    if key_bytes == previous {
                        return Err(CanonicalDigestError::DuplicateMapKey);
                    }
                    if key_bytes < previous {
                        return Err(CanonicalDigestError::NonCanonicalOrder);
                    }
                }
                previous = Some(key_bytes);
                validate_encoded_value(reader, depth + 1)?;
            }
            Ok(())
        }
        _ => Err(CanonicalDigestError::InvalidTag),
    }
}

struct Reader<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Reader<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(&mut self, count: usize) -> Result<&'a [u8], CanonicalDigestError> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(CanonicalDigestError::Truncated)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(CanonicalDigestError::Truncated)?;
        self.offset = end;
        Ok(value)
    }

    fn read_u8(&mut self) -> Result<u8, CanonicalDigestError> {
        Ok(self.take(1)?[0])
    }

    fn read_u16(&mut self) -> Result<u16, CanonicalDigestError> {
        let bytes = self.take(2)?;
        Ok(u16::from_be_bytes([bytes[0], bytes[1]]))
    }

    fn read_u32(&mut self) -> Result<u32, CanonicalDigestError> {
        let bytes = self.take(4)?;
        Ok(u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
    }

    fn read_len_u16(&mut self) -> Result<&'a [u8], CanonicalDigestError> {
        let length = usize::from(self.read_u16()?);
        self.take(length)
    }

    fn read_len_u32(&mut self) -> Result<&'a [u8], CanonicalDigestError> {
        let length =
            usize::try_from(self.read_u32()?).map_err(|_| CanonicalDigestError::TooLarge)?;
        self.take(length)
    }

    const fn is_complete(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

fn encode_value(
    value: CanonicalValueV1<'_>,
    output: &mut Vec<u8>,
    depth: usize,
) -> Result<(), CanonicalDigestError> {
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
            if depth >= MAX_CANONICAL_DEPTH_V1 {
                return Err(CanonicalDigestError::DepthExceeded);
            }
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
            if depth >= MAX_CANONICAL_DEPTH_V1 {
                return Err(CanonicalDigestError::DepthExceeded);
            }
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
    InvalidMagic,
    InvalidEncodingVersion,
    InvalidDomain,
    InvalidBool,
    InvalidTag,
    NonCanonicalOrder,
    TrailingBytes,
    Truncated,
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
