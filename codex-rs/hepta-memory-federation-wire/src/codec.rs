use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::decode_typed;
use codex_hepta_wire::encode_typed;

use crate::protocol::AuthenticatedFederationFrameV1;
use crate::protocol::AuthenticatedFrontierV1;
use crate::protocol::DecodedFederationFrameV1;
use crate::protocol::FEDERATION_MAC_BYTES;
use crate::protocol::FEDERATION_NONCE_BYTES;
use crate::protocol::FederationCancelAckMessageV1;
use crate::protocol::FederationCancelMessageV1;
use crate::protocol::FederationCancellationDispositionV1;
use crate::protocol::FederationCancellationReasonV1;
use crate::protocol::FederationNonceV1;
use crate::protocol::FederationQueryMessageV1;
use crate::protocol::FederationResponseMessageV1;
use crate::protocol::FederationWireMessageV1;

pub const AUTHENTICATED_FRAME_SCHEMA_V1: &str = "hepta-memory-federation-authenticated-frame-v1";
pub const AUTHENTICATED_FRAME_FORMAT_VERSION_V1: u16 = 1;
pub const MAX_AUTHENTICATED_FRAME_BYTES: usize = 256 * 1024;

const MAGIC: [u8; 4] = *b"HMF1";
const MAX_ID_BYTES: usize = 1_024;

#[derive(Clone, Debug)]
pub struct AuthenticatedFrameCodecV1 {
    descriptor: SchemaDescriptor,
}

impl AuthenticatedFrameCodecV1 {
    pub fn new() -> Result<Self, FederationCodecError> {
        let schema = StableId::new(AUTHENTICATED_FRAME_SCHEMA_V1.to_string())
            .map_err(|_| FederationCodecError::Identity)?;
        let descriptor = SchemaDescriptor::new(
            schema,
            WireVersion::V2,
            WireVersion::V2,
            MAX_AUTHENTICATED_FRAME_BYTES,
        )
        .map_err(|_| FederationCodecError::Descriptor)?;
        Ok(Self { descriptor })
    }
}

impl PayloadCodec for AuthenticatedFrameCodecV1 {
    type Value = AuthenticatedFederationFrameV1;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        encode_frame(value).map_err(|_| SchemaCodecError::Rejected("federation frame encode"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        decode_frame(payload).map_err(|_| SchemaCodecError::Rejected("federation frame decode"))
    }
}

pub fn registered_codec_v1()
-> Result<(SchemaRegistry, AuthenticatedFrameCodecV1), FederationCodecError> {
    let codec = AuthenticatedFrameCodecV1::new()?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(|_| FederationCodecError::Descriptor)?;
    Ok((registry, codec))
}

pub fn encode_registered_frame_v1(
    registry: &SchemaRegistry,
    codec: &AuthenticatedFrameCodecV1,
    frame: &AuthenticatedFederationFrameV1,
) -> Result<Vec<u8>, SchemaCodecError> {
    encode_typed(registry, WireVersion::V2, codec, frame)
}

pub fn decode_registered_frame_v1(
    registry: &SchemaRegistry,
    codec: &AuthenticatedFrameCodecV1,
    payload: &[u8],
) -> Result<AuthenticatedFederationFrameV1, SchemaCodecError> {
    decode_typed(
        registry,
        WireVersion::V2,
        codec.descriptor().schema(),
        codec,
        payload,
    )
}

fn encode_frame(frame: &AuthenticatedFederationFrameV1) -> Result<Vec<u8>, FederationCodecError> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&MAGIC);
    bytes.extend_from_slice(&AUTHENTICATED_FRAME_FORMAT_VERSION_V1.to_be_bytes());
    push_id(&mut bytes, &frame.sender_peer_id)?;
    push_id(&mut bytes, &frame.receiver_peer_id)?;
    push_id(&mut bytes, &frame.key_id)?;
    bytes.extend_from_slice(&frame.key_generation.to_be_bytes());
    bytes.extend_from_slice(&frame.issued_unix_ms.to_be_bytes());
    bytes.extend_from_slice(&frame.expires_unix_ms.to_be_bytes());
    bytes.extend_from_slice(frame.nonce.as_bytes());
    encode_message_into(&frame.message, &mut bytes);
    bytes.extend_from_slice(frame.mac());
    if bytes.len() > MAX_AUTHENTICATED_FRAME_BYTES {
        return Err(FederationCodecError::Oversize);
    }
    Ok(bytes)
}

fn decode_frame(payload: &[u8]) -> Result<AuthenticatedFederationFrameV1, FederationCodecError> {
    if payload.is_empty() || payload.len() > MAX_AUTHENTICATED_FRAME_BYTES {
        return Err(FederationCodecError::Oversize);
    }
    let mut reader = Reader::new(payload);
    if reader.take_array::<4>()? != MAGIC {
        return Err(FederationCodecError::Magic);
    }
    let version = reader.read_u16()?;
    if version != AUTHENTICATED_FRAME_FORMAT_VERSION_V1 {
        return Err(FederationCodecError::Version(version));
    }
    let sender_peer_id = reader.read_id()?;
    let receiver_peer_id = reader.read_id()?;
    let key_id = reader.read_id()?;
    let key_generation = reader.read_u64()?;
    let issued_unix_ms = reader.read_u64()?;
    let expires_unix_ms = reader.read_u64()?;
    let nonce = FederationNonceV1::from_bytes(reader.take_array::<FEDERATION_NONCE_BYTES>()?);
    let message = decode_message(&mut reader)?;
    let mac = reader.take_array::<FEDERATION_MAC_BYTES>()?;
    reader.require_eof()?;
    Ok(AuthenticatedFederationFrameV1::from_decoded_parts(
        DecodedFederationFrameV1 {
            sender_peer_id,
            receiver_peer_id,
            key_id,
            key_generation,
            issued_unix_ms,
            expires_unix_ms,
            nonce,
            message,
            mac,
        },
    ))
}

pub(crate) fn encode_message_into(message: &FederationWireMessageV1, bytes: &mut Vec<u8>) {
    match message {
        FederationWireMessageV1::Query(query) => {
            bytes.push(1);
            push_id_infallible(bytes, &query.query_id);
            push_digest(bytes, query.query_binding_digest);
            push_digest(bytes, query.scope_digest);
            push_digest(bytes, query.purpose_digest);
            push_digest(bytes, query.generation_vector_digest);
            bytes.extend_from_slice(&query.maximum_results.to_be_bytes());
        }
        FederationWireMessageV1::Response(response) => {
            bytes.push(2);
            push_id_infallible(bytes, &response.query_id);
            push_digest(bytes, response.query_binding_digest);
            push_digest(bytes, response.response_digest);
            push_digest(bytes, response.result_digest);
            encode_frontier(&response.frontier, bytes);
            bytes.push(u8::from(response.terminal_observed));
        }
        FederationWireMessageV1::Cancel(cancel) => {
            bytes.push(3);
            push_id_infallible(bytes, &cancel.query_id);
            push_digest(bytes, cancel.query_binding_digest);
            push_id_infallible(bytes, &cancel.cancellation_id);
            bytes.push(match cancel.reason {
                FederationCancellationReasonV1::CallerCancelled => 1,
                FederationCancellationReasonV1::DeadlineExpired => 2,
                FederationCancellationReasonV1::AuthorityRevoked => 3,
            });
        }
        FederationWireMessageV1::CancelAck(ack) => {
            bytes.push(4);
            push_id_infallible(bytes, &ack.query_id);
            push_digest(bytes, ack.query_binding_digest);
            push_id_infallible(bytes, &ack.cancellation_id);
            bytes.push(match ack.disposition {
                FederationCancellationDispositionV1::ObservedBeforeTerminal => 1,
                FederationCancellationDispositionV1::TerminalAlreadyObserved => 2,
                FederationCancellationDispositionV1::UnknownAttempt => 3,
            });
            bytes.extend_from_slice(&ack.observed_unix_ms.to_be_bytes());
        }
    }
}

fn decode_message(
    reader: &mut Reader<'_>,
) -> Result<FederationWireMessageV1, FederationCodecError> {
    match reader.read_u8()? {
        1 => Ok(FederationWireMessageV1::Query(FederationQueryMessageV1 {
            query_id: reader.read_id()?,
            query_binding_digest: reader.read_digest()?,
            scope_digest: reader.read_digest()?,
            purpose_digest: reader.read_digest()?,
            generation_vector_digest: reader.read_digest()?,
            maximum_results: reader.read_u32()?,
        })),
        2 => Ok(FederationWireMessageV1::Response(
            FederationResponseMessageV1 {
                query_id: reader.read_id()?,
                query_binding_digest: reader.read_digest()?,
                response_digest: reader.read_digest()?,
                result_digest: reader.read_digest()?,
                frontier: decode_frontier(reader)?,
                terminal_observed: reader.read_bool()?,
            },
        )),
        3 => {
            let query_id = reader.read_id()?;
            let query_binding_digest = reader.read_digest()?;
            let cancellation_id = reader.read_id()?;
            let reason = match reader.read_u8()? {
                1 => FederationCancellationReasonV1::CallerCancelled,
                2 => FederationCancellationReasonV1::DeadlineExpired,
                3 => FederationCancellationReasonV1::AuthorityRevoked,
                _ => return Err(FederationCodecError::Enum),
            };
            Ok(FederationWireMessageV1::Cancel(FederationCancelMessageV1 {
                query_id,
                query_binding_digest,
                cancellation_id,
                reason,
            }))
        }
        4 => {
            let query_id = reader.read_id()?;
            let query_binding_digest = reader.read_digest()?;
            let cancellation_id = reader.read_id()?;
            let disposition = match reader.read_u8()? {
                1 => FederationCancellationDispositionV1::ObservedBeforeTerminal,
                2 => FederationCancellationDispositionV1::TerminalAlreadyObserved,
                3 => FederationCancellationDispositionV1::UnknownAttempt,
                _ => return Err(FederationCodecError::Enum),
            };
            Ok(FederationWireMessageV1::CancelAck(
                FederationCancelAckMessageV1 {
                    query_id,
                    query_binding_digest,
                    cancellation_id,
                    disposition,
                    observed_unix_ms: reader.read_u64()?,
                },
            ))
        }
        _ => Err(FederationCodecError::Enum),
    }
}

fn encode_frontier(frontier: &AuthenticatedFrontierV1, bytes: &mut Vec<u8>) {
    push_id_infallible(bytes, &frontier.owner_peer_id);
    bytes.extend_from_slice(&frontier.generation.to_be_bytes());
    bytes.extend_from_slice(&frontier.frontier.to_be_bytes());
    push_digest(bytes, frontier.state_digest);
    push_digest(bytes, frontier.parent_witness_digest);
    bytes.extend_from_slice(&frontier.observed_unix_ms.to_be_bytes());
}

fn decode_frontier(
    reader: &mut Reader<'_>,
) -> Result<AuthenticatedFrontierV1, FederationCodecError> {
    Ok(AuthenticatedFrontierV1 {
        owner_peer_id: reader.read_id()?,
        generation: reader.read_u64()?,
        frontier: reader.read_u64()?,
        state_digest: reader.read_digest()?,
        parent_witness_digest: reader.read_digest()?,
        observed_unix_ms: reader.read_u64()?,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), FederationCodecError> {
    let raw = value.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_ID_BYTES {
        return Err(FederationCodecError::Identity);
    }
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| FederationCodecError::Identity)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_id_infallible(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

struct Reader<'a> {
    payload: &'a [u8],
    cursor: usize,
}

impl<'a> Reader<'a> {
    const fn new(payload: &'a [u8]) -> Self {
        Self { payload, cursor: 0 }
    }

    fn read_u8(&mut self) -> Result<u8, FederationCodecError> {
        Ok(self.take(1)?[0])
    }

    fn read_u16(&mut self) -> Result<u16, FederationCodecError> {
        Ok(u16::from_be_bytes(self.take_array()?))
    }

    fn read_u32(&mut self) -> Result<u32, FederationCodecError> {
        Ok(u32::from_be_bytes(self.take_array()?))
    }

    fn read_u64(&mut self) -> Result<u64, FederationCodecError> {
        Ok(u64::from_be_bytes(self.take_array()?))
    }

    fn read_bool(&mut self) -> Result<bool, FederationCodecError> {
        match self.read_u8()? {
            0 => Ok(false),
            1 => Ok(true),
            _ => Err(FederationCodecError::Boolean),
        }
    }

    fn read_id(&mut self) -> Result<StableId, FederationCodecError> {
        let length = usize::try_from(self.read_u32()?).map_err(|_| FederationCodecError::Length)?;
        if length == 0 || length > MAX_ID_BYTES {
            return Err(FederationCodecError::Identity);
        }
        let value =
            std::str::from_utf8(self.take(length)?).map_err(|_| FederationCodecError::Utf8)?;
        StableId::new(value.to_string()).map_err(|_| FederationCodecError::Identity)
    }

    fn read_digest(&mut self) -> Result<Digest32, FederationCodecError> {
        Ok(Digest32::from_array(self.take_array()?))
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], FederationCodecError> {
        let end = self
            .cursor
            .checked_add(length)
            .ok_or(FederationCodecError::Length)?;
        let value = self
            .payload
            .get(self.cursor..end)
            .ok_or(FederationCodecError::Truncated)?;
        self.cursor = end;
        Ok(value)
    }

    fn take_array<const N: usize>(&mut self) -> Result<[u8; N], FederationCodecError> {
        self.take(N)?
            .try_into()
            .map_err(|_| FederationCodecError::Truncated)
    }

    fn require_eof(&self) -> Result<(), FederationCodecError> {
        if self.cursor == self.payload.len() {
            Ok(())
        } else {
            Err(FederationCodecError::TrailingBytes)
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationCodecError {
    Descriptor,
    Magic,
    Version(u16),
    Identity,
    Oversize,
    Truncated,
    TrailingBytes,
    Length,
    Utf8,
    Boolean,
    Enum,
}

impl fmt::Display for FederationCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Descriptor => formatter.write_str("federation schema descriptor is invalid"),
            Self::Magic => formatter.write_str("federation wire magic is invalid"),
            Self::Version(version) => {
                write!(formatter, "unsupported federation wire version {version}")
            }
            Self::Identity => formatter.write_str("federation wire identity is invalid"),
            Self::Oversize => formatter.write_str("federation frame is empty or oversized"),
            Self::Truncated => formatter.write_str("federation frame is truncated"),
            Self::TrailingBytes => formatter.write_str("federation frame has trailing bytes"),
            Self::Length => formatter.write_str("federation frame length is invalid"),
            Self::Utf8 => formatter.write_str("federation identity is not UTF-8"),
            Self::Boolean => formatter.write_str("federation boolean encoding is invalid"),
            Self::Enum => formatter.write_str("federation enum encoding is invalid"),
        }
    }
}

impl Error for FederationCodecError {}
