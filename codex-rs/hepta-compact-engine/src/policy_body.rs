//! Canonical immutable policy bytes using the existing V2 semantic preimage.

use crate::CompactionPolicyV2;
use crate::MAX_PROTECTED_COMPACTION_REFS;
use crate::QualifiedCompactionError;
use codex_hepta_types::Digest32;
use codex_hepta_types::IdProfileV1;
use codex_hepta_types::StableId;
use std::error::Error;
use std::fmt;

pub const MAX_COMPACTION_POLICY_BODY_BYTES_V2: usize = 1024 * 1024;
const DOMAIN: &[u8] = b"hepta.compaction-policy.v2";
const MAX_ID_BYTES: usize = 128;

/// Explicit schema profile for these bytes. It is not a publication grant.
pub fn compaction_policy_body_schema_digest_v2() -> Digest32 {
    Digest32::of_bytes(b"hepta.compact.policy-body.schema.v2")
}

#[derive(Debug)]
pub enum PolicyBodyErrorV2 {
    Size,
    Malformed(&'static str),
    InvalidPolicy(QualifiedCompactionError),
}
impl fmt::Display for PolicyBodyErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for PolicyBodyErrorV2 {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::InvalidPolicy(error) => Some(error),
            Self::Size | Self::Malformed(_) => None,
        }
    }
}

/// Encode the exact preimage already hashed by CompactionPolicyV2::digest.
/// Protected IDs are a semantic set there, so output sorts the validated set.
pub fn encode_compaction_policy_body_v2(
    policy: &CompactionPolicyV2,
) -> Result<Vec<u8>, PolicyBodyErrorV2> {
    policy
        .validate()
        .map_err(PolicyBodyErrorV2::InvalidPolicy)?;
    let mut length = DOMAIN.len() + 8 + policy.policy_id.as_str().len() + 64 + 16;
    for id in &policy.protected_record_ids {
        length = length
            .checked_add(8 + id.as_str().len())
            .ok_or(PolicyBodyErrorV2::Size)?;
    }
    if length > MAX_COMPACTION_POLICY_BODY_BYTES_V2 {
        return Err(PolicyBodyErrorV2::Size);
    }
    let mut protected = policy.protected_record_ids.iter().collect::<Vec<_>>();
    protected.sort();
    let mut bytes = Vec::with_capacity(length);
    bytes.extend_from_slice(DOMAIN);
    append_id(&mut bytes, &policy.policy_id);
    bytes.extend_from_slice(policy.algorithm_digest.as_array());
    bytes.extend_from_slice(policy.compatibility_digest.as_array());
    bytes.extend_from_slice(&u64::from(policy.maximum_retained_records).to_be_bytes());
    bytes.extend_from_slice(&(protected.len() as u64).to_be_bytes());
    for id in protected {
        append_id(&mut bytes, id);
    }
    Ok(bytes)
}

/// Decode one bounded canonical policy body. No alternate ordering, spelling,
/// duplicate IDs, trailing bytes or unknown domain is accepted.
pub fn decode_compaction_policy_body_v2(
    bytes: &[u8],
) -> Result<CompactionPolicyV2, PolicyBodyErrorV2> {
    if bytes.len() > MAX_COMPACTION_POLICY_BODY_BYTES_V2 {
        return Err(PolicyBodyErrorV2::Size);
    }
    let mut reader = Reader { remaining: bytes };
    if reader.take(DOMAIN.len())? != DOMAIN {
        return Err(PolicyBodyErrorV2::Malformed("domain"));
    }
    let policy_id = reader.id()?;
    let algorithm_digest = reader.digest()?;
    let compatibility_digest = reader.digest()?;
    let maximum_retained_records = u32::try_from(reader.number()?)
        .map_err(|_| PolicyBodyErrorV2::Malformed("retention overflow"))?;
    let count = usize::try_from(reader.number()?).map_err(|_| PolicyBodyErrorV2::Size)?;
    if count > MAX_PROTECTED_COMPACTION_REFS {
        return Err(PolicyBodyErrorV2::Size);
    }
    // Every nonempty bounded ID requires at least an 8-byte length and 1 byte.
    // Refuse impossible counts before allocating the vector or any IDs.
    let minimum = count.checked_mul(9).ok_or(PolicyBodyErrorV2::Size)?;
    if reader.remaining.len() < minimum {
        return Err(PolicyBodyErrorV2::Malformed("truncated IDs"));
    }
    let mut protected_record_ids = Vec::<StableId>::with_capacity(count);
    for _ in 0..count {
        let id = reader.id()?;
        if protected_record_ids
            .last()
            .is_some_and(|previous| previous >= &id)
        {
            return Err(PolicyBodyErrorV2::Malformed("noncanonical ID order"));
        }
        protected_record_ids.push(id);
    }
    if !reader.remaining.is_empty() {
        return Err(PolicyBodyErrorV2::Malformed("trailing bytes"));
    }
    let policy = CompactionPolicyV2 {
        policy_id,
        algorithm_digest,
        compatibility_digest,
        maximum_retained_records,
        protected_record_ids,
    };
    policy
        .validate()
        .map_err(PolicyBodyErrorV2::InvalidPolicy)?;
    Ok(policy)
}

fn append_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
struct Reader<'a> {
    remaining: &'a [u8],
}
impl<'a> Reader<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], PolicyBodyErrorV2> {
        let (value, rest) = self
            .remaining
            .split_at_checked(length)
            .ok_or(PolicyBodyErrorV2::Malformed("truncated"))?;
        self.remaining = rest;
        Ok(value)
    }
    fn number(&mut self) -> Result<u64, PolicyBodyErrorV2> {
        Ok(u64::from_be_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| PolicyBodyErrorV2::Malformed("integer"))?,
        ))
    }
    fn digest(&mut self) -> Result<Digest32, PolicyBodyErrorV2> {
        Ok(Digest32::from_array(
            self.take(32)?
                .try_into()
                .map_err(|_| PolicyBodyErrorV2::Malformed("digest"))?,
        ))
    }
    fn id(&mut self) -> Result<StableId, PolicyBodyErrorV2> {
        let length = usize::try_from(self.number()?).map_err(|_| PolicyBodyErrorV2::Size)?;
        if !(1..=MAX_ID_BYTES).contains(&length) {
            return Err(PolicyBodyErrorV2::Malformed("ID length"));
        }
        let raw = std::str::from_utf8(self.take(length)?)
            .map_err(|_| PolicyBodyErrorV2::Malformed("ID UTF8"))?;
        StableId::with_profile(raw, IdProfileV1::Stable)
            .map_err(|_| PolicyBodyErrorV2::Malformed("ID grammar"))
    }
}

#[cfg(test)]
#[path = "policy_body_tests.rs"]
mod tests;
