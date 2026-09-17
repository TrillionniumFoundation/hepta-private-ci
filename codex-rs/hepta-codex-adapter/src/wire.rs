use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::CapabilitySet;
use codex_hepta_wire::NegotiatedWire;
use codex_hepta_wire::PayloadCodecError;
use codex_hepta_wire::SchemaError;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WirePayload;
use codex_hepta_wire::WireV2Error;
use codex_hepta_wire::WireVersion;

use crate::CodexOperationIntent;

pub const CODEX_OPERATION_INTENT_SCHEMA: &str = "runtime.codex.operation-intent.v1";
const MAX_CODEX_INTENT_PAYLOAD_BYTES: usize = 512;

impl WirePayload for CodexOperationIntent {
    const SCHEMA_ID: &'static str = CODEX_OPERATION_INTENT_SCHEMA;

    fn encode_payload(&self) -> Result<Vec<u8>, PayloadCodecError> {
        let mut bytes = Vec::with_capacity(MAX_CODEX_INTENT_PAYLOAD_BYTES);
        push_id(&mut bytes, &self.operation_id)?;
        push_id(&mut bytes, &self.thread_id)?;
        push_id(&mut bytes, &self.method_id)?;
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(self.lease_payload_digest.as_array());
        bytes.extend_from_slice(&self.deadline_ms.to_be_bytes());
        Ok(bytes)
    }

    fn decode_payload(payload: &[u8]) -> Result<Self, PayloadCodecError> {
        let mut cursor = 0_usize;
        let operation_id = read_id(payload, &mut cursor)?;
        let thread_id = read_id(payload, &mut cursor)?;
        let method_id = read_id(payload, &mut cursor)?;
        let payload_digest = read_digest(payload, &mut cursor)?;
        let lease_payload_digest = read_digest(payload, &mut cursor)?;
        let deadline_ms = read_u64(payload, &mut cursor)?;
        if cursor != payload.len() {
            return Err(PayloadCodecError::new("codex intent trailing bytes"));
        }
        if payload_digest.is_zero() || lease_payload_digest.is_zero() {
            return Err(PayloadCodecError::new("codex intent zero payload digest"));
        }
        Ok(Self {
            operation_id,
            thread_id,
            method_id,
            payload_digest,
            lease_payload_digest,
            deadline_ms,
        })
    }
}

pub fn codex_wire_schema_registry() -> Result<SchemaRegistry, WireIntegrationError> {
    let mut registry = SchemaRegistry::new();
    registry
        .register::<CodexOperationIntent>(
            &[WireVersion::V2],
            MAX_CODEX_INTENT_PAYLOAD_BYTES,
        )
        .map_err(WireIntegrationError::Schema)?;
    Ok(registry)
}

pub fn encode_codex_intent_frame(
    negotiated: NegotiatedWire,
    producer: StableId,
    generation: Generation,
    intent: &CodexOperationIntent,
) -> Result<Vec<u8>, WireIntegrationError> {
    require_v2_protocol(negotiated)?;
    let registry = codex_wire_schema_registry()?;
    let envelope = registry
        .encode_v2(producer, generation, intent)
        .map_err(WireIntegrationError::Schema)?;
    Ok(envelope.encode())
}

pub fn decode_codex_intent_frame(
    negotiated: NegotiatedWire,
    encoded: &[u8],
) -> Result<CodexOperationIntent, WireIntegrationError> {
    require_v2_protocol(negotiated)?;
    let envelope = WireEnvelopeV2::decode(encoded).map_err(WireIntegrationError::V2)?;
    let registry = codex_wire_schema_registry()?;
    registry
        .decode_v2::<CodexOperationIntent>(&envelope)
        .map_err(WireIntegrationError::Schema)
}

fn require_v2_protocol(negotiated: NegotiatedWire) -> Result<(), WireIntegrationError> {
    let required = CapabilitySet::FULL_FRAME_INTEGRITY.union(CapabilitySet::SCHEMA_ADMISSION);
    if negotiated.version() != WireVersion::V2
        || !negotiated.capabilities().contains(required)
    {
        return Err(WireIntegrationError::NegotiationMismatch);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), PayloadCodecError> {
    let raw = value.as_str().as_bytes();
    let length = u16::try_from(raw.len())
        .map_err(|_| PayloadCodecError::new("codex intent id length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn read_id(payload: &[u8], cursor: &mut usize) -> Result<StableId, PayloadCodecError> {
    let length = usize::from(read_u16(payload, cursor)?);
    if length == 0 || length > 128 {
        return Err(PayloadCodecError::new("codex intent id length"));
    }
    let end = cursor
        .checked_add(length)
        .ok_or_else(|| PayloadCodecError::new("codex intent id overflow"))?;
    let raw = payload
        .get(*cursor..end)
        .ok_or_else(|| PayloadCodecError::new("codex intent id truncated"))?;
    let value = std::str::from_utf8(raw)
        .map_err(|_| PayloadCodecError::new("codex intent id utf8"))?;
    let value = StableId::new(value)
        .map_err(|_| PayloadCodecError::new("codex intent id canonicalization"))?;
    *cursor = end;
    Ok(value)
}

fn read_digest(payload: &[u8], cursor: &mut usize) -> Result<Digest32, PayloadCodecError> {
    let end = cursor
        .checked_add(32)
        .ok_or_else(|| PayloadCodecError::new("codex intent digest overflow"))?;
    let raw: [u8; 32] = payload
        .get(*cursor..end)
        .ok_or_else(|| PayloadCodecError::new("codex intent digest truncated"))?
        .try_into()
        .map_err(|_| PayloadCodecError::new("codex intent digest width"))?;
    *cursor = end;
    Ok(Digest32::from_array(raw))
}

fn read_u16(payload: &[u8], cursor: &mut usize) -> Result<u16, PayloadCodecError> {
    let end = cursor
        .checked_add(2)
        .ok_or_else(|| PayloadCodecError::new("codex intent u16 overflow"))?;
    let raw: [u8; 2] = payload
        .get(*cursor..end)
        .ok_or_else(|| PayloadCodecError::new("codex intent u16 truncated"))?
        .try_into()
        .map_err(|_| PayloadCodecError::new("codex intent u16 width"))?;
    *cursor = end;
    Ok(u16::from_be_bytes(raw))
}

fn read_u64(payload: &[u8], cursor: &mut usize) -> Result<u64, PayloadCodecError> {
    let end = cursor
        .checked_add(8)
        .ok_or_else(|| PayloadCodecError::new("codex intent u64 overflow"))?;
    let raw: [u8; 8] = payload
        .get(*cursor..end)
        .ok_or_else(|| PayloadCodecError::new("codex intent u64 truncated"))?
        .try_into()
        .map_err(|_| PayloadCodecError::new("codex intent u64 width"))?;
    *cursor = end;
    Ok(u64::from_be_bytes(raw))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireIntegrationError {
    NegotiationMismatch,
    Schema(SchemaError),
    V2(WireV2Error),
}

impl fmt::Display for WireIntegrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NegotiationMismatch => formatter.write_str(
                "Codex wire integration requires negotiated HPTA V2 full-frame integrity and schema admission",
            ),
            Self::Schema(error) => write!(formatter, "Codex wire schema error: {error}"),
            Self::V2(error) => write!(formatter, "Codex HPTA V2 frame error: {error}"),
        }
    }
}

impl StdError for WireIntegrationError {}

#[cfg(test)]
mod tests {
    use codex_hepta_wire::NegotiationOffer;
    use codex_hepta_wire::VersionOffer;
    use codex_hepta_wire::negotiate;

    use super::*;

    fn negotiated_v2() -> NegotiatedWire {
        let capabilities = CapabilitySet::FULL_FRAME_INTEGRITY
            .union(CapabilitySet::SCHEMA_ADMISSION)
            .union(CapabilitySet::STREAMING_DECODE);
        let offer = NegotiationOffer::new(
            vec![VersionOffer::new(WireVersion::V2, capabilities)],
            CapabilitySet::FULL_FRAME_INTEGRITY.union(CapabilitySet::SCHEMA_ADMISSION),
        )
        .expect("offer");
        negotiate(&offer, &offer).expect("negotiation")
    }

    fn intent() -> CodexOperationIntent {
        CodexOperationIntent {
            operation_id: StableId::new("operation.7").expect("operation"),
            thread_id: StableId::new("thread.9").expect("thread"),
            method_id: StableId::new("turn.start").expect("method"),
            payload_digest: Digest32::of_bytes(b"payload"),
            lease_payload_digest: Digest32::of_bytes(b"payload"),
            deadline_ms: 42_000,
        }
    }

    #[test]
    fn product_adapter_round_trips_typed_intent_over_v2() {
        let intent = intent();
        let frame = encode_codex_intent_frame(
            negotiated_v2(),
            StableId::new("runtime.codex").expect("producer"),
            Generation::new(3).expect("generation"),
            &intent,
        )
        .expect("encode");
        assert_eq!(
            decode_codex_intent_frame(negotiated_v2(), &frame),
            Ok(intent)
        );
    }

    #[test]
    fn v1_or_missing_capabilities_cannot_enter_v2_product_path() {
        let offer = NegotiationOffer::new(
            vec![VersionOffer::new(WireVersion::V1, CapabilitySet::NONE)],
            CapabilitySet::NONE,
        )
        .expect("offer");
        let negotiated = negotiate(&offer, &offer).expect("V1 negotiation");
        assert_eq!(
            encode_codex_intent_frame(
                negotiated,
                StableId::new("runtime.codex").expect("producer"),
                Generation::new(1).expect("generation"),
                &intent(),
            ),
            Err(WireIntegrationError::NegotiationMismatch)
        );
    }
}
