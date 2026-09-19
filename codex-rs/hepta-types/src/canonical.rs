use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::StableId;

const CANONICAL_PREFIX_V1: &[u8] = b"HEPTA-CANONICAL-DIGEST-V1\0";
const MAX_DOMAIN_BYTES_V1: usize = 128;
const MAX_FIELD_NAME_BYTES_V1: usize = 128;
const MAX_FIELDS_V1: usize = 1024;
pub const MAX_CANONICAL_COLLECTION_BYTES_V1: usize = 256 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalValueV1<'a> {
    Bytes(&'a [u8]),
    Text(&'a str),
    U64(u64),
    I64(i64),
    Bool(bool),
    Digest(Digest32),
    StableId(&'a StableId),
}

impl CanonicalValueV1<'_> {
    const fn tag(self) -> u8 {
        match self {
            Self::Bytes(_) => 1,
            Self::Text(_) => 2,
            Self::U64(_) => 3,
            Self::I64(_) => 4,
            Self::Bool(_) => 5,
            Self::Digest(_) => 6,
            Self::StableId(_) => 7,
        }
    }

    fn encoded_len(self) -> usize {
        match self {
            Self::Bytes(value) => value.len(),
            Self::Text(value) => value.len(),
            Self::U64(_) | Self::I64(_) => 8,
            Self::Bool(_) => 1,
            Self::Digest(_) => 32,
            Self::StableId(value) => value.as_str().len(),
        }
    }

    fn append_to(self, output: &mut Vec<u8>) {
        match self {
            Self::Bytes(value) => output.extend_from_slice(value),
            Self::Text(value) => output.extend_from_slice(value.as_bytes()),
            Self::U64(value) => output.extend_from_slice(&value.to_be_bytes()),
            Self::I64(value) => output.extend_from_slice(&value.to_be_bytes()),
            Self::Bool(value) => output.push(u8::from(value)),
            Self::Digest(value) => output.extend_from_slice(value.as_array()),
            Self::StableId(value) => output.extend_from_slice(value.as_str().as_bytes()),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalFieldV1<'a> {
    pub name: &'a str,
    pub value: CanonicalValueV1<'a>,
}

/// Encodes the language-neutral Platform Types V1 canonical byte sequence.
///
/// Framing is:
/// prefix || u16(domain_len) || domain || u16(field_count) || fields.
/// Each field is u16(name_len) || name || u8(type_tag) || u32(value_len)
/// || value. Integers are big-endian, booleans are 0/1, field names must be
/// strictly byte-sorted, and the full collection is capped at 256 KiB.
pub fn canonical_encode_v1(
    domain: &str,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<Vec<u8>, CanonicalDigestError> {
    validate_domain(domain)?;
    if fields.len() > MAX_FIELDS_V1 {
        return Err(CanonicalDigestError::TooManyFields(fields.len()));
    }

    let mut total = CANONICAL_PREFIX_V1
        .len()
        .checked_add(2 + domain.len() + 2)
        .ok_or(CanonicalDigestError::CollectionTooLarge)?;
    let mut previous_name: Option<&[u8]> = None;
    for field in fields {
        validate_field_name(field.name)?;
        if previous_name.is_some_and(|previous| previous >= field.name.as_bytes()) {
            return Err(CanonicalDigestError::FieldsNotCanonical);
        }
        previous_name = Some(field.name.as_bytes());
        let value_len = field.value.encoded_len();
        if value_len > MAX_CANONICAL_COLLECTION_BYTES_V1 {
            return Err(CanonicalDigestError::ValueTooLarge(value_len));
        }
        total = total
            .checked_add(2 + field.name.len() + 1 + 4 + value_len)
            .ok_or(CanonicalDigestError::CollectionTooLarge)?;
        if total > MAX_CANONICAL_COLLECTION_BYTES_V1 {
            return Err(CanonicalDigestError::CollectionTooLarge);
        }
    }

    let mut output = Vec::with_capacity(total);
    output.extend_from_slice(CANONICAL_PREFIX_V1);
    output.extend_from_slice(&(domain.len() as u16).to_be_bytes());
    output.extend_from_slice(domain.as_bytes());
    output.extend_from_slice(&(fields.len() as u16).to_be_bytes());
    for field in fields {
        output.extend_from_slice(&(field.name.len() as u16).to_be_bytes());
        output.extend_from_slice(field.name.as_bytes());
        output.push(field.value.tag());
        output.extend_from_slice(&(field.value.encoded_len() as u32).to_be_bytes());
        field.value.append_to(&mut output);
    }
    Ok(output)
}

/// Computes SHA-256 over the explicitly versioned, domain-separated canonical
/// byte sequence returned by canonical_encode_v1.
pub fn canonical_digest_v1(
    domain: &str,
    fields: &[CanonicalFieldV1<'_>],
) -> Result<Digest32, CanonicalDigestError> {
    canonical_encode_v1(domain, fields).map(|encoded| Digest32::of_bytes(&encoded))
}

fn validate_domain(domain: &str) -> Result<(), CanonicalDigestError> {
    if domain.is_empty() {
        return Err(CanonicalDigestError::EmptyDomain);
    }
    if domain.len() > MAX_DOMAIN_BYTES_V1 {
        return Err(CanonicalDigestError::DomainTooLarge(domain.len()));
    }
    if !is_canonical_token(domain) {
        return Err(CanonicalDigestError::InvalidDomain);
    }
    Ok(())
}

fn validate_field_name(name: &str) -> Result<(), CanonicalDigestError> {
    if name.is_empty() {
        return Err(CanonicalDigestError::EmptyFieldName);
    }
    if name.len() > MAX_FIELD_NAME_BYTES_V1 {
        return Err(CanonicalDigestError::FieldNameTooLarge(name.len()));
    }
    if !is_canonical_token(name) {
        return Err(CanonicalDigestError::InvalidFieldName);
    }
    Ok(())
}

fn is_canonical_token(value: &str) -> bool {
    value.bytes().all(|byte| {
        byte.is_ascii_lowercase()
            || byte.is_ascii_digit()
            || matches!(byte, b'.' | b'_' | b'-')
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalDigestError {
    EmptyDomain,
    DomainTooLarge(usize),
    InvalidDomain,
    TooManyFields(usize),
    EmptyFieldName,
    FieldNameTooLarge(usize),
    InvalidFieldName,
    FieldsNotCanonical,
    ValueTooLarge(usize),
    CollectionTooLarge,
}

impl fmt::Display for CanonicalDigestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CanonicalDigestError {}

#[cfg(test)]
#[path = "canonical_tests.rs"]
mod tests;
