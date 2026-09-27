//! Versioned, bounded semantic input for a read-only retrieval model.
//!
//! This is not the numeric NeuronFeatureRequestV1, a capability, a source
//! authorization, or a durable owner. The existing inference owner retains
//! operation identity and must authorize/revalidate sources at actual use.
//! Prediction order is abstain, then source IDs sorted by ASCII, independent
//! of the source order bound into the exact request bytes.

use std::collections::BTreeSet;
use std::str::FromStr;

use codex_hepta_types::Digest32;

const REQUEST_MAGIC: &[u8] = b"HPTARQ\x01\x00";
const REPLY_MAGIC: &[u8] = b"HPTARS\x01\x00";
const MAX_INTEGER: u64 = i64::MAX as u64;
pub const MAX_RETRIEVAL_FRAME_BYTES: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalSourceV1 {
    pub source_id: String,
    pub revision: u64,
    pub content_sha256: String,
    pub text: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRetrievalRequestV1 {
    pub operation_id: String,
    pub workspace_id: String,
    pub generation: u64,
    pub objective_digest: String,
    pub observation_digest: String,
    pub bundle_digest: String,
    /// Absolute Unix milliseconds. The runtime supplies the trusted clock.
    pub deadline_ms: u64,
    pub query: String,
    pub sources: Vec<RetrievalSourceV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRetrievalReplyV1 {
    pub request_digest: Digest32,
    pub bundle_digest: Digest32,
    pub prediction_ppm: Vec<u32>,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub latency_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RetrievalWireError {
    Identity,
    Digest,
    Bounds,
    SourceChanged,
    DuplicateSource,
    Expired,
    Profile,
    Truncated,
    Trailing,
    Binding,
    Probability,
}

impl std::fmt::Display for RetrievalWireError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for RetrievalWireError {}

impl SemanticRetrievalRequestV1 {
    pub fn validate_at(&self, now_ms: u64) -> Result<(), RetrievalWireError> {
        self.encode()?;
        if now_ms >= self.deadline_ms {
            return Err(RetrievalWireError::Expired);
        }
        Ok(())
    }

    /// Encode the complete scoped request. No JSON parser, text rendering or
    /// architecture-dependent numeric cast participates in its wire identity.
    pub fn encode(&self) -> Result<Vec<u8>, RetrievalWireError> {
        valid_identity(&self.operation_id)?;
        valid_identity(&self.workspace_id)?;
        if self.generation == 0
            || self.generation > MAX_INTEGER
            || self.deadline_ms == 0
            || self.deadline_ms > MAX_INTEGER
            || self.sources.is_empty()
            || self.sources.len() > 15
        {
            return Err(RetrievalWireError::Bounds);
        }
        let mut bytes = REQUEST_MAGIC.to_vec();
        push_text(&mut bytes, &self.operation_id, 128)?;
        push_text(&mut bytes, &self.workspace_id, 128)?;
        bytes.extend_from_slice(&self.generation.to_be_bytes());
        for value in [
            &self.objective_digest,
            &self.observation_digest,
            &self.bundle_digest,
        ] {
            bytes.extend_from_slice(parse_digest(value)?.as_array());
        }
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        push_text(&mut bytes, &self.query, 2048)?;
        let count = u32::try_from(self.sources.len()).map_err(|_| RetrievalWireError::Bounds)?;
        bytes.extend_from_slice(&count.to_be_bytes());
        let mut seen = BTreeSet::new();
        for source in &self.sources {
            valid_identity(&source.source_id)?;
            if !seen.insert(&source.source_id) {
                return Err(RetrievalWireError::DuplicateSource);
            }
            if source.revision == 0 || source.revision > MAX_INTEGER {
                return Err(RetrievalWireError::Bounds);
            }
            let digest = parse_digest(&source.content_sha256)?;
            if source.text.is_empty() || source.text.len() > 2048 {
                return Err(RetrievalWireError::Bounds);
            }
            if Digest32::of_bytes(source.text.as_bytes()) != digest {
                return Err(RetrievalWireError::SourceChanged);
            }
            push_text(&mut bytes, &source.source_id, 128)?;
            bytes.extend_from_slice(&source.revision.to_be_bytes());
            bytes.extend_from_slice(digest.as_array());
            push_text(&mut bytes, &source.text, 2048)?;
        }
        if bytes.len() > MAX_RETRIEVAL_FRAME_BYTES {
            return Err(RetrievalWireError::Bounds);
        }
        Ok(bytes)
    }

    /// Recover exactly the existing V1 bytes. Decoding does not revalidate
    /// present-day source authorization; the consumer owns that use boundary.
    pub fn decode(raw: &[u8]) -> Result<Self, RetrievalWireError> {
        if raw.len() > MAX_RETRIEVAL_FRAME_BYTES {
            return Err(RetrievalWireError::Bounds);
        }
        let mut reader = Reader { remaining: raw };
        if reader.take(REQUEST_MAGIC.len())? != REQUEST_MAGIC {
            return Err(RetrievalWireError::Profile);
        }
        let operation_id = reader.text(128)?;
        let workspace_id = reader.text(128)?;
        let generation = reader.u64()?;
        let objective_digest = reader.digest_hex()?;
        let observation_digest = reader.digest_hex()?;
        let bundle_digest = reader.digest_hex()?;
        let deadline_ms = reader.u64()?;
        let query = reader.text(2048)?;
        let count = reader.u32()?;
        if count == 0 || count > 15 {
            return Err(RetrievalWireError::Bounds);
        }
        let mut sources = Vec::new();
        for _ in 0..count {
            sources.push(RetrievalSourceV1 {
                source_id: reader.text(128)?,
                revision: reader.u64()?,
                content_sha256: reader.digest_hex()?,
                text: reader.text(2048)?,
            });
        }
        if !reader.remaining.is_empty() {
            return Err(RetrievalWireError::Trailing);
        }
        let request = Self {
            operation_id,
            workspace_id,
            generation,
            objective_digest,
            observation_digest,
            bundle_digest,
            deadline_ms,
            query,
            sources,
        };
        if request.encode()?.as_slice() != raw {
            return Err(RetrievalWireError::Binding);
        }
        Ok(request)
    }

    /// Decode a complete reply only for this exact request. This proves byte
    /// correspondence, not model execution, authority, calibration or success.
    pub fn decode_reply(&self, raw: &[u8]) -> Result<SemanticRetrievalReplyV1, RetrievalWireError> {
        if raw.len() > MAX_RETRIEVAL_FRAME_BYTES {
            return Err(RetrievalWireError::Bounds);
        }
        let request_digest = Digest32::of_bytes(&self.encode()?);
        let bundle_digest = parse_digest(&self.bundle_digest)?;
        let mut reader = Reader { remaining: raw };
        if reader.take(REPLY_MAGIC.len())? != REPLY_MAGIC {
            return Err(RetrievalWireError::Profile);
        }
        if reader.take(32)? != request_digest.as_array()
            || reader.take(32)? != bundle_digest.as_array()
        {
            return Err(RetrievalWireError::Binding);
        }
        let count = reader.u32()?;
        if usize::try_from(count).map_err(|_| RetrievalWireError::Bounds)? != self.sources.len() + 1
        {
            return Err(RetrievalWireError::Binding);
        }
        let mut prediction_ppm = Vec::new();
        let mut total = 0_u64;
        for _ in 0..count {
            let value = reader.u32()?;
            if value > 1_000_000 {
                return Err(RetrievalWireError::Probability);
            }
            total += u64::from(value);
            prediction_ppm.push(value);
        }
        if total != 1_000_000 {
            return Err(RetrievalWireError::Probability);
        }
        let input_tokens = reader.u64()?;
        let output_tokens = reader.u64()?;
        let latency_micros = reader.u64()?;
        if input_tokens == 0
            || input_tokens > 131_072
            || output_tokens > 131_072
            || latency_micros > MAX_INTEGER
        {
            return Err(RetrievalWireError::Bounds);
        }
        if !reader.remaining.is_empty() {
            return Err(RetrievalWireError::Trailing);
        }
        Ok(SemanticRetrievalReplyV1 {
            request_digest,
            bundle_digest,
            prediction_ppm,
            input_tokens,
            output_tokens,
            latency_micros,
        })
    }
}

fn valid_identity(value: &str) -> Result<(), RetrievalWireError> {
    if value.is_empty()
        || value.len() > 128
        || !value.as_bytes()[0].is_ascii_alphanumeric()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:/-".contains(&byte))
    {
        return Err(RetrievalWireError::Identity);
    }
    Ok(())
}

fn parse_digest(value: &str) -> Result<Digest32, RetrievalWireError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(RetrievalWireError::Digest);
    }
    let digest = Digest32::from_str(value).map_err(|_| RetrievalWireError::Digest)?;
    if digest.is_zero() {
        return Err(RetrievalWireError::Digest);
    }
    Ok(digest)
}

fn push_text(bytes: &mut Vec<u8>, value: &str, maximum: usize) -> Result<(), RetrievalWireError> {
    if value.is_empty() || value.len() > maximum {
        return Err(RetrievalWireError::Bounds);
    }
    let length = u32::try_from(value.len()).map_err(|_| RetrievalWireError::Bounds)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

struct Reader<'a> {
    remaining: &'a [u8],
}

impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], RetrievalWireError> {
        if count > self.remaining.len() {
            return Err(RetrievalWireError::Truncated);
        }
        let (value, remaining) = self.remaining.split_at(count);
        self.remaining = remaining;
        Ok(value)
    }

    fn text(&mut self, maximum: usize) -> Result<String, RetrievalWireError> {
        let length = usize::try_from(self.u32()?).map_err(|_| RetrievalWireError::Bounds)?;
        if length == 0 || length > maximum {
            return Err(RetrievalWireError::Bounds);
        }
        std::str::from_utf8(self.take(length)?)
            .map(str::to_owned)
            .map_err(|_| RetrievalWireError::Profile)
    }

    fn digest_hex(&mut self) -> Result<String, RetrievalWireError> {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let mut value = String::with_capacity(64);
        for &byte in self.take(32)? {
            value.push(char::from(HEX[usize::from(byte >> 4)]));
            value.push(char::from(HEX[usize::from(byte & 15)]));
        }
        Ok(value)
    }

    fn u32(&mut self) -> Result<u32, RetrievalWireError> {
        let bytes = self
            .take(4)?
            .try_into()
            .map_err(|_| RetrievalWireError::Truncated)?;
        Ok(u32::from_be_bytes(bytes))
    }

    fn u64(&mut self) -> Result<u64, RetrievalWireError> {
        let bytes = self
            .take(8)?
            .try_into()
            .map_err(|_| RetrievalWireError::Truncated)?;
        Ok(u64::from_be_bytes(bytes))
    }
}

#[cfg(test)]
#[path = "semantic_retrieval_tests.rs"]
mod tests;
