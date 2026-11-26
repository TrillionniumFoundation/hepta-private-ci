//! Versioned application receipt attachment for the unified V2 Neuron store.
//!
//! The checkpoint payload remains the sole replay input for Neuron state.  A
//! typed application receipt may be attached to the exact same durable commit
//! without creating another ledger or changing historical checkpoint bytes.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HPTNFR02";
const VERSION: u16 = 2;
const HEADER_BYTES: usize = 86;
const CHECKSUM_BYTES: usize = 32;
const MAX_SCHEMA_ID_BYTES: usize = 128;
const MAX_EXTENSION_PAYLOAD_BYTES: usize = 1024 * 1024;
const DIGEST_DOMAIN: &[u8] = b"hepta.neuron.full-receipt-envelope.v2";
const EXTENSION_DOMAIN: &[u8] = b"hepta.neuron.receipt-extension.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronReceiptExtensionV2 {
    pub schema_id: StableId,
    pub schema_version: u16,
    pub payload_digest: Digest32,
    pub payload: Vec<u8>,
}

impl NeuronReceiptExtensionV2 {
    pub fn new(
        schema_id: StableId,
        schema_version: u16,
        payload: Vec<u8>,
    ) -> Result<Self, NeuronReceiptExtensionErrorV2> {
        if schema_version == 0 || payload.is_empty() || payload.len() > MAX_EXTENSION_PAYLOAD_BYTES
        {
            return Err(NeuronReceiptExtensionErrorV2::InvalidExtension);
        }
        let payload_digest = Digest32::of_bytes(&payload);
        let value = Self {
            schema_id,
            schema_version,
            payload_digest,
            payload,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), NeuronReceiptExtensionErrorV2> {
        let schema = self.schema_id.as_str().as_bytes();
        if schema.is_empty()
            || schema.len() > MAX_SCHEMA_ID_BYTES
            || self.schema_version == 0
            || self.payload.is_empty()
            || self.payload.len() > MAX_EXTENSION_PAYLOAD_BYTES
            || self.payload_digest.is_zero()
            || self.payload_digest != Digest32::of_bytes(&self.payload)
        {
            return Err(NeuronReceiptExtensionErrorV2::InvalidExtension);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, NeuronReceiptExtensionErrorV2> {
        self.validate()?;
        let schema = self.schema_id.as_str().as_bytes();
        let schema_len =
            u16::try_from(schema.len()).map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
        Ok(Digest32::of_parts(&[
            EXTENSION_DOMAIN,
            &schema_len.to_be_bytes(),
            schema,
            &self.schema_version.to_be_bytes(),
            self.payload_digest.as_array(),
        ]))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronReceiptExtensionErrorV2 {
    InvalidExtension,
    InvalidEnvelope,
    CheckpointMismatch,
    PayloadMismatch,
    UnsupportedVersion,
    Arithmetic,
}

impl fmt::Display for NeuronReceiptExtensionErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronReceiptExtensionErrorV2 {}

/// Preserve historical full-receipt bytes when there is no attachment.  This
/// is important for exact replay and for old stores whose two payload fields
/// intentionally contain the same canonical checkpoint encoding.
pub fn encode_full_receipt_v2(
    checkpoint_bytes: &[u8],
    extension: Option<&NeuronReceiptExtensionV2>,
) -> Result<Vec<u8>, NeuronReceiptExtensionErrorV2> {
    if checkpoint_bytes.is_empty() {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    let Some(extension) = extension else {
        return Ok(checkpoint_bytes.to_vec());
    };
    extension.validate()?;
    let checkpoint_len = u32::try_from(checkpoint_bytes.len())
        .map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let schema = extension.schema_id.as_str().as_bytes();
    let schema_len =
        u16::try_from(schema.len()).map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let payload_len = u32::try_from(extension.payload.len())
        .map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let capacity = HEADER_BYTES
        .checked_add(checkpoint_bytes.len())
        .and_then(|value| value.checked_add(schema.len()))
        .and_then(|value| value.checked_add(extension.payload.len()))
        .and_then(|value| value.checked_add(CHECKSUM_BYTES))
        .ok_or(NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let mut bytes = Vec::with_capacity(capacity);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&VERSION.to_be_bytes());
    bytes.extend_from_slice(&checkpoint_len.to_be_bytes());
    bytes.extend_from_slice(&schema_len.to_be_bytes());
    bytes.extend_from_slice(&extension.schema_version.to_be_bytes());
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(Digest32::of_bytes(checkpoint_bytes).as_array());
    bytes.extend_from_slice(extension.payload_digest.as_array());
    bytes.extend_from_slice(checkpoint_bytes);
    bytes.extend_from_slice(schema);
    bytes.extend_from_slice(&extension.payload);
    let checksum = Digest32::of_parts(&[DIGEST_DOMAIN, &bytes]);
    bytes.extend_from_slice(checksum.as_array());
    Ok(bytes)
}

pub fn decode_full_receipt_v2(
    checkpoint_bytes: &[u8],
    full_receipt_bytes: &[u8],
) -> Result<Option<NeuronReceiptExtensionV2>, NeuronReceiptExtensionErrorV2> {
    if checkpoint_bytes.is_empty() || full_receipt_bytes.is_empty() {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    if full_receipt_bytes == checkpoint_bytes {
        return Ok(None);
    }
    if full_receipt_bytes.len() < HEADER_BYTES + CHECKSUM_BYTES
        || full_receipt_bytes.get(..MAGIC.len()) != Some(MAGIC.as_slice())
    {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    let version = u16::from_be_bytes(read_array::<2>(full_receipt_bytes, 8)?);
    if version != VERSION {
        return Err(NeuronReceiptExtensionErrorV2::UnsupportedVersion);
    }
    let checkpoint_len =
        usize::try_from(u32::from_be_bytes(read_array::<4>(full_receipt_bytes, 10)?))
            .map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let schema_len = usize::from(u16::from_be_bytes(read_array::<2>(full_receipt_bytes, 14)?));
    let schema_version = u16::from_be_bytes(read_array::<2>(full_receipt_bytes, 16)?);
    let payload_len = usize::try_from(u32::from_be_bytes(read_array::<4>(full_receipt_bytes, 18)?))
        .map_err(|_| NeuronReceiptExtensionErrorV2::Arithmetic)?;
    if schema_len == 0
        || schema_len > MAX_SCHEMA_ID_BYTES
        || schema_version == 0
        || payload_len == 0
        || payload_len > MAX_EXTENSION_PAYLOAD_BYTES
    {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    let expected_checkpoint_digest =
        Digest32::from_array(read_array::<32>(full_receipt_bytes, 22)?);
    let expected_payload_digest = Digest32::from_array(read_array::<32>(full_receipt_bytes, 54)?);
    let payload_end = HEADER_BYTES
        .checked_add(checkpoint_len)
        .and_then(|value| value.checked_add(schema_len))
        .and_then(|value| value.checked_add(payload_len))
        .ok_or(NeuronReceiptExtensionErrorV2::Arithmetic)?;
    let total = payload_end
        .checked_add(CHECKSUM_BYTES)
        .ok_or(NeuronReceiptExtensionErrorV2::Arithmetic)?;
    if total != full_receipt_bytes.len() {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    let checkpoint = full_receipt_bytes
        .get(HEADER_BYTES..HEADER_BYTES + checkpoint_len)
        .ok_or(NeuronReceiptExtensionErrorV2::InvalidEnvelope)?;
    if checkpoint != checkpoint_bytes
        || expected_checkpoint_digest != Digest32::of_bytes(checkpoint_bytes)
    {
        return Err(NeuronReceiptExtensionErrorV2::CheckpointMismatch);
    }
    let schema_start = HEADER_BYTES + checkpoint_len;
    let schema_end = schema_start + schema_len;
    let schema = std::str::from_utf8(
        full_receipt_bytes
            .get(schema_start..schema_end)
            .ok_or(NeuronReceiptExtensionErrorV2::InvalidEnvelope)?,
    )
    .map_err(|_| NeuronReceiptExtensionErrorV2::InvalidEnvelope)?;
    let payload = full_receipt_bytes
        .get(schema_end..payload_end)
        .ok_or(NeuronReceiptExtensionErrorV2::InvalidEnvelope)?
        .to_vec();
    if expected_payload_digest != Digest32::of_bytes(&payload) {
        return Err(NeuronReceiptExtensionErrorV2::PayloadMismatch);
    }
    let expected_checksum =
        Digest32::from_array(read_array::<32>(full_receipt_bytes, payload_end)?);
    let actual_checksum = Digest32::of_parts(&[
        DIGEST_DOMAIN,
        full_receipt_bytes
            .get(..payload_end)
            .ok_or(NeuronReceiptExtensionErrorV2::InvalidEnvelope)?,
    ]);
    if expected_checksum != actual_checksum {
        return Err(NeuronReceiptExtensionErrorV2::InvalidEnvelope);
    }
    let schema_id = StableId::new(schema.to_owned())
        .map_err(|_| NeuronReceiptExtensionErrorV2::InvalidEnvelope)?;
    let extension = NeuronReceiptExtensionV2 {
        schema_id,
        schema_version,
        payload_digest: expected_payload_digest,
        payload,
    };
    extension.validate()?;
    Ok(Some(extension))
}

fn read_array<const N: usize>(
    bytes: &[u8],
    offset: usize,
) -> Result<[u8; N], NeuronReceiptExtensionErrorV2> {
    bytes
        .get(offset..offset + N)
        .ok_or(NeuronReceiptExtensionErrorV2::InvalidEnvelope)?
        .try_into()
        .map_err(|_| NeuronReceiptExtensionErrorV2::InvalidEnvelope)
}

#[cfg(test)]
#[path = "receipt_extension_v2_tests.rs"]
mod tests;
