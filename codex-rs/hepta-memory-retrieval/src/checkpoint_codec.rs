//! Bounded, versioned storage of the actual engram and generated recall.
//!
//! Content hashes must come from the durable owner, not from the untrusted
//! payload. These codecs preserve every field and re-run the existing logical
//! validators; they do not confer owner freshness or write authority.

use codex_hepta_types::Digest32;

use crate::EngramSnapshotV1;
use crate::GeneratedRecallV1;

#[path = "checkpoint_codec_values.rs"]
mod values;

pub const MAX_ENGRAM_CHECKPOINT_BYTES_V1: usize = 1_048_576;
pub const MAX_RECALL_CHECKPOINT_BYTES_V1: usize = 524_288;
const ENGRAM_MAGIC: &[u8] = b"HEPTA-ENGRAM-CHECKPOINT-V1\0";
const RECALL_MAGIC: &[u8] = b"HEPTA-RECALL-CHECKPOINT-V1\0";
const MAX_COLLECTION_ITEMS: usize = 32_768;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryCheckpointCodecErrorV1 {
    SizeLimit,
    Truncated,
    TrailingBytes,
    ContentDigestMismatch,
    InvalidValue(&'static str),
    InvalidContract(String),
}

impl std::fmt::Display for MemoryCheckpointCodecErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for MemoryCheckpointCodecErrorV1 {}

type Result<T> = std::result::Result<T, MemoryCheckpointCodecErrorV1>;

/// Encode all graph state, including node support and signed synapse weights.
pub fn encode_engram_checkpoint_v1(value: &EngramSnapshotV1) -> Result<Vec<u8>> {
    let bytes = encode(value, ENGRAM_MAGIC, MAX_ENGRAM_CHECKPOINT_BYTES_V1)?;
    value
        .validate()
        .map_err(|error| MemoryCheckpointCodecErrorV1::InvalidContract(error.to_string()))?;
    Ok(bytes)
}

/// Recover a complete graph whose byte identity was retained by its owner.
pub fn decode_engram_checkpoint_v1(
    bytes: &[u8],
    expected_content_digest: Digest32,
) -> Result<EngramSnapshotV1> {
    let value: EngramSnapshotV1 = decode(
        bytes,
        expected_content_digest,
        ENGRAM_MAGIC,
        MAX_ENGRAM_CHECKPOINT_BYTES_V1,
    )?;
    value
        .validate()
        .map_err(|error| MemoryCheckpointCodecErrorV1::InvalidContract(error.to_string()))?;
    Ok(value)
}

/// Encode the full packet, engram receipt and generator completeness evidence.
pub fn encode_recall_checkpoint_v1(value: &GeneratedRecallV1) -> Result<Vec<u8>> {
    let bytes = encode(value, RECALL_MAGIC, MAX_RECALL_CHECKPOINT_BYTES_V1)?;
    value
        .validate()
        .map_err(|error| MemoryCheckpointCodecErrorV1::InvalidContract(error.to_string()))?;
    Ok(bytes)
}

/// Recover an exact recall, including abstention and every support reference.
pub fn decode_recall_checkpoint_v1(
    bytes: &[u8],
    expected_content_digest: Digest32,
) -> Result<GeneratedRecallV1> {
    let value: GeneratedRecallV1 = decode(
        bytes,
        expected_content_digest,
        RECALL_MAGIC,
        MAX_RECALL_CHECKPOINT_BYTES_V1,
    )?;
    value
        .validate()
        .map_err(|error| MemoryCheckpointCodecErrorV1::InvalidContract(error.to_string()))?;
    Ok(value)
}

/// Internal fixed-schema encoding. Implementations must consume at least one
/// byte and reject unknown tags; collection lengths never reserve allocations.
trait Codec: Sized {
    fn write(&self, writer: &mut Writer) -> Result<()>;
    fn read(reader: &mut Reader<'_>) -> Result<Self>;
}

struct Writer {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Writer {
    fn append(&mut self, bytes: &[u8]) -> Result<()> {
        if bytes.len() > self.maximum.saturating_sub(self.bytes.len()) {
            return Err(MemoryCheckpointCodecErrorV1::SizeLimit);
        }
        self.bytes.extend_from_slice(bytes);
        Ok(())
    }
}

struct Reader<'a> {
    remaining: &'a [u8],
}

impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8]> {
        if count > self.remaining.len() {
            return Err(MemoryCheckpointCodecErrorV1::Truncated);
        }
        let (value, remaining) = self.remaining.split_at(count);
        self.remaining = remaining;
        Ok(value)
    }
}

fn encode<T: Codec>(value: &T, magic: &[u8], maximum: usize) -> Result<Vec<u8>> {
    let mut writer = Writer {
        bytes: Vec::new(),
        maximum,
    };
    writer.append(magic)?;
    value.write(&mut writer)?;
    Ok(writer.bytes)
}

fn decode<T: Codec>(
    bytes: &[u8],
    expected: Digest32,
    magic: &[u8],
    maximum: usize,
) -> Result<T> {
    if bytes.len() > maximum {
        return Err(MemoryCheckpointCodecErrorV1::SizeLimit);
    }
    if expected.is_zero() || Digest32::of_bytes(bytes) != expected {
        return Err(MemoryCheckpointCodecErrorV1::ContentDigestMismatch);
    }
    let mut reader = Reader { remaining: bytes };
    if reader.take(magic.len())? != magic {
        return Err(MemoryCheckpointCodecErrorV1::InvalidValue("schema"));
    }
    let value = T::read(&mut reader)?;
    if !reader.remaining.is_empty() {
        return Err(MemoryCheckpointCodecErrorV1::TrailingBytes);
    }
    Ok(value)
}

macro_rules! integer {
    ($type:ty, $width:expr) => {
        impl Codec for $type {
            fn write(&self, writer: &mut Writer) -> Result<()> {
                writer.append(&self.to_be_bytes())
            }
            fn read(reader: &mut Reader<'_>) -> Result<Self> {
                let mut bytes = [0; $width];
                bytes.copy_from_slice(reader.take($width)?);
                Ok(Self::from_be_bytes(bytes))
            }
        }
    };
}

integer!(u8, 1);
integer!(u32, 4);
integer!(u64, 8);
integer!(i64, 8);

impl<T: Codec> Codec for Vec<T> {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        if self.len() > MAX_COLLECTION_ITEMS {
            return Err(MemoryCheckpointCodecErrorV1::SizeLimit);
        }
        u32::try_from(self.len())
            .map_err(|_| MemoryCheckpointCodecErrorV1::SizeLimit)?
            .write(writer)?;
        for value in self {
            value.write(writer)?;
        }
        Ok(())
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        let count = usize::try_from(u32::read(reader)?)
            .map_err(|_| MemoryCheckpointCodecErrorV1::SizeLimit)?;
        if count > MAX_COLLECTION_ITEMS || count > reader.remaining.len() {
            return Err(MemoryCheckpointCodecErrorV1::SizeLimit);
        }
        let mut values = Vec::new();
        for _ in 0..count {
            values.push(T::read(reader)?);
        }
        Ok(values)
    }
}

impl<T: Codec> Codec for Option<T> {
    fn write(&self, writer: &mut Writer) -> Result<()> {
        u8::from(self.is_some()).write(writer)?;
        if let Some(value) = self {
            value.write(writer)?;
        }
        Ok(())
    }
    fn read(reader: &mut Reader<'_>) -> Result<Self> {
        match u8::read(reader)? {
            0 => Ok(None),
            1 => Ok(Some(T::read(reader)?)),
            _ => Err(MemoryCheckpointCodecErrorV1::InvalidValue("option tag")),
        }
    }
}

#[cfg(test)]
#[path = "checkpoint_codec_tests.rs"]
mod tests;
