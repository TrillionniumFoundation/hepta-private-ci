use std::error::Error;
use std::fmt;
use std::sync::Arc;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DecodeFrameError;
use crate::DecodedEnvelope;
use crate::FrozenAdmissionError;
use crate::FrozenSchemaRegistry;
use crate::MAX_WIRE_FRAME_BYTES;
use crate::NegotiatedWire;
use crate::NegotiationError;
use crate::NegotiationOffer;
use crate::PayloadCodec;
use crate::SchemaCodecError;
use crate::WireEnvelope;
use crate::WireEnvelopeV2;
use crate::WireError;
use crate::WireV2Error;
use crate::WireVersion;
use crate::decode_frame;
use crate::decode_typed;
use crate::encode_typed;
use crate::negotiate;

const TRANSCRIPT_DOMAIN: &[u8] = b"HPTA-NEGOTIATION-TRANSCRIPT-V1\0";
const SESSION_ID_DOMAIN: &[u8] = b"HPTA-WIRE-SESSION-V1\0";
const RECORD_MAC_DOMAIN: &[u8] = b"HPTA-AUTHENTICATED-RECORD-V1\0";
const AUTHENTICATED_RECORD_MAGIC: [u8; 4] = *b"HPTM";
const AUTHENTICATED_RECORD_FORMAT: u16 = 1;
const AUTHENTICATED_RECORD_PREFIX_BYTES: usize = 4 + 2 + 32 + 8 + 4;
const AUTHENTICATED_RECORD_TAG_BYTES: usize = 32;
pub const MIN_CHANNEL_BINDING_BYTES: usize = 16;
pub const MAX_CHANNEL_BINDING_BYTES: usize = 512;
pub const MAX_AUTHENTICATED_RECORD_BYTES: usize =
    AUTHENTICATED_RECORD_PREFIX_BYTES + MAX_WIRE_FRAME_BYTES + AUTHENTICATED_RECORD_TAG_BYTES;

/// Canonical digest of the ordered HPTN offers, selected posture, frozen
/// registry and authenticated transport channel binding.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NegotiationTranscript {
    digest: Digest32,
}

impl NegotiationTranscript {
    pub fn from_offers(
        initiator: &NegotiationOffer,
        responder: &NegotiationOffer,
        negotiated: NegotiatedWire,
        registry_digest: Digest32,
        channel_binding: &[u8],
    ) -> Result<Self, WireSessionError> {
        if !(MIN_CHANNEL_BINDING_BYTES..=MAX_CHANNEL_BINDING_BYTES)
            .contains(&channel_binding.len())
        {
            return Err(WireSessionError::ChannelBindingLength {
                actual: channel_binding.len(),
                minimum: MIN_CHANNEL_BINDING_BYTES,
                maximum: MAX_CHANNEL_BINDING_BYTES,
            });
        }
        let recomputed = negotiate(initiator, responder, negotiated.required_capabilities())
            .map_err(WireSessionError::Negotiation)?;
        if recomputed != negotiated {
            return Err(WireSessionError::NegotiationResultMismatch);
        }

        let initiator = initiator.encode();
        let responder = responder.encode();
        let mut encoded = Vec::new();
        encoded.extend_from_slice(TRANSCRIPT_DOMAIN);
        put_bytes(&mut encoded, &initiator);
        put_bytes(&mut encoded, &responder);
        encoded.extend_from_slice(&negotiated.version().as_u16().to_be_bytes());
        encoded.extend_from_slice(&negotiated.capabilities().bits().to_be_bytes());
        encoded.extend_from_slice(
            &negotiated
                .common_advertised_capabilities()
                .bits()
                .to_be_bytes(),
        );
        encoded.extend_from_slice(&negotiated.required_capabilities().bits().to_be_bytes());
        encoded.extend_from_slice(registry_digest.as_array());
        put_bytes(&mut encoded, channel_binding);
        Ok(Self {
            digest: Digest32::of_bytes(&encoded),
        })
    }

    pub const fn digest(self) -> Digest32 {
        self.digest
    }
}

/// Production session posture. It couples the negotiated version and
/// capabilities to one immutable registry, runtime role and authenticated
/// negotiation transcript.
#[derive(Clone, Debug)]
pub struct WireSession {
    negotiated: NegotiatedWire,
    role: StableId,
    registry: Arc<FrozenSchemaRegistry>,
    transcript: NegotiationTranscript,
    session_id: Digest32,
}

impl WireSession {
    pub fn new(
        negotiated: NegotiatedWire,
        role: StableId,
        registry: Arc<FrozenSchemaRegistry>,
        transcript: NegotiationTranscript,
    ) -> Self {
        let version = negotiated.version().as_u16().to_be_bytes();
        let capabilities = negotiated.capabilities().bits().to_be_bytes();
        let session_id = Digest32::of_parts(&[
            SESSION_ID_DOMAIN,
            transcript.digest().as_array(),
            registry.snapshot_digest().as_array(),
            &version,
            &capabilities,
        ]);
        Self {
            negotiated,
            role,
            registry,
            transcript,
            session_id,
        }
    }

    pub const fn negotiated(&self) -> NegotiatedWire {
        self.negotiated
    }

    pub fn role(&self) -> &StableId {
        &self.role
    }

    pub fn registry(&self) -> &FrozenSchemaRegistry {
        &self.registry
    }

    pub const fn transcript(&self) -> NegotiationTranscript {
        self.transcript
    }

    pub const fn session_id(&self) -> Digest32 {
        self.session_id
    }

    pub fn admit_envelope(&self, envelope: &DecodedEnvelope) -> Result<(), WireSessionError> {
        self.registry
            .admit_envelope(self.negotiated, &self.role, envelope)
            .map(|_| ())
            .map_err(|source| WireSessionError::Admission {
                context: SessionErrorContext::for_admission(self.session_id, &source),
                source,
            })
    }

    pub fn decode_frame(&self, encoded: &[u8]) -> Result<DecodedEnvelope, WireSessionError> {
        let envelope = decode_frame(encoded).map_err(|source| WireSessionError::Decode {
            context: SessionErrorContext {
                session_id: self.session_id,
                byte_offset: decode_error_offset(&source, encoded.len()),
            },
            source,
        })?;
        self.admit_envelope(&envelope)?;
        Ok(envelope)
    }

    pub fn encode_typed_envelope<C: PayloadCodec>(
        &self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<DecodedEnvelope, WireSessionError> {
        let payload = encode_typed(
            self.registry.inner(),
            self.negotiated.version(),
            codec,
            value,
        )
        .map_err(WireSessionError::Codec)?;
        let envelope = match self.negotiated.version() {
            WireVersion::V1 => DecodedEnvelope::V1(
                WireEnvelope::new(
                    codec.descriptor().schema().clone(),
                    producer,
                    generation,
                    payload,
                )
                .map_err(WireSessionError::V1)?,
            ),
            WireVersion::V2 => DecodedEnvelope::V2(
                WireEnvelopeV2::new(
                    codec.descriptor().schema().clone(),
                    producer,
                    generation,
                    payload,
                )
                .map_err(WireSessionError::V2)?,
            ),
        };
        self.admit_envelope(&envelope)?;
        Ok(envelope)
    }

    pub fn decode_typed_envelope<C: PayloadCodec>(
        &self,
        envelope: &DecodedEnvelope,
        codec: &C,
    ) -> Result<C::Value, WireSessionError> {
        self.admit_envelope(envelope)?;
        decode_typed(
            self.registry.inner(),
            envelope.version(),
            envelope.schema(),
            codec,
            envelope.payload(),
        )
        .map_err(WireSessionError::Codec)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SessionErrorContext {
    session_id: Digest32,
    byte_offset: Option<usize>,
}

impl SessionErrorContext {
    const fn for_admission(session_id: Digest32, error: &FrozenAdmissionError) -> Self {
        let byte_offset = match error {
            FrozenAdmissionError::VersionMismatch { byte_offset, .. } => Some(*byte_offset),
            _ => None,
        };
        Self {
            session_id,
            byte_offset,
        }
    }

    pub const fn session_id(self) -> Digest32 {
        self.session_id
    }

    pub const fn byte_offset(self) -> Option<usize> {
        self.byte_offset
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireSessionError {
    ChannelBindingLength {
        actual: usize,
        minimum: usize,
        maximum: usize,
    },
    Negotiation(NegotiationError),
    NegotiationResultMismatch,
    Decode {
        context: SessionErrorContext,
        source: DecodeFrameError,
    },
    Admission {
        context: SessionErrorContext,
        source: FrozenAdmissionError,
    },
    Codec(SchemaCodecError),
    V1(WireError),
    V2(WireV2Error),
}

impl fmt::Display for WireSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ChannelBindingLength {
                actual,
                minimum,
                maximum,
            } => write!(
                formatter,
                "authenticated channel binding length {actual} is outside {minimum}..={maximum}"
            ),
            Self::Negotiation(error) => error.fmt(formatter),
            Self::NegotiationResultMismatch => {
                formatter.write_str("negotiation result does not match the ordered transcript")
            }
            Self::Decode { context, source } => write!(
                formatter,
                "session {} frame decode failed at byte {:?}: {source}",
                context.session_id,
                context.byte_offset
            ),
            Self::Admission { context, source } => write!(
                formatter,
                "session {} frame admission failed at byte {:?}: {source}",
                context.session_id,
                context.byte_offset
            ),
            Self::Codec(error) => error.fmt(formatter),
            Self::V1(error) => error.fmt(formatter),
            Self::V2(error) => error.fmt(formatter),
        }
    }
}

impl Error for WireSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Negotiation(error) => Some(error),
            Self::Decode { source, .. } => Some(source),
            Self::Admission { source, .. } => Some(source),
            Self::Codec(error) => Some(error),
            Self::V1(error) => Some(error),
            Self::V2(error) => Some(error),
            _ => None,
        }
    }
}

/// A fixed-size HMAC-SHA-256 key. Its Debug representation never exposes key
/// bytes and an all-zero key is rejected.
#[derive(Clone)]
pub struct SessionMacKey([u8; 32]);

impl SessionMacKey {
    pub fn new(bytes: [u8; 32]) -> Result<Self, AuthenticatedSessionError> {
        if bytes.iter().all(|byte| *byte == 0) {
            return Err(AuthenticatedSessionError::ZeroMacKey);
        }
        Ok(Self(bytes))
    }
}

impl fmt::Debug for SessionMacKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SessionMacKey([REDACTED])")
    }
}

/// Replay-ordered authenticated record layer for a completed wire session.
///
/// The MAC covers the session identifier, monotonically increasing sequence
/// and exact encoded frame. Any terminal error poisons the connection-local
/// state; callers must establish a fresh authenticated session rather than
/// resetting sequence numbers in place.
#[derive(Debug)]
pub struct AuthenticatedWireSession {
    session: WireSession,
    key: SessionMacKey,
    next_send_sequence: u64,
    next_receive_sequence: u64,
    poisoned: bool,
}

impl AuthenticatedWireSession {
    pub fn new(session: WireSession, key: SessionMacKey) -> Self {
        Self {
            session,
            key,
            next_send_sequence: 1,
            next_receive_sequence: 1,
            poisoned: false,
        }
    }

    pub fn session(&self) -> &WireSession {
        &self.session
    }

    pub const fn is_poisoned(&self) -> bool {
        self.poisoned
    }

    pub fn seal_envelope(
        &mut self,
        envelope: &DecodedEnvelope,
    ) -> Result<Vec<u8>, AuthenticatedSessionError> {
        if self.poisoned {
            return Err(AuthenticatedSessionError::Poisoned);
        }
        self.session
            .admit_envelope(envelope)
            .map_err(AuthenticatedSessionError::Session)?;
        let frame = envelope.encode();
        if frame.len() > MAX_WIRE_FRAME_BYTES {
            return Err(AuthenticatedSessionError::FrameLength {
                actual: frame.len(),
                maximum: MAX_WIRE_FRAME_BYTES,
                byte_offset: AUTHENTICATED_RECORD_PREFIX_BYTES,
            });
        }
        let frame_length = u32::try_from(frame.len()).map_err(|_| {
            AuthenticatedSessionError::FrameLength {
                actual: frame.len(),
                maximum: MAX_WIRE_FRAME_BYTES,
                byte_offset: AUTHENTICATED_RECORD_PREFIX_BYTES,
            }
        })?;
        let sequence = self.next_send_sequence;
        let mut record = Vec::with_capacity(
            AUTHENTICATED_RECORD_PREFIX_BYTES + frame.len() + AUTHENTICATED_RECORD_TAG_BYTES,
        );
        record.extend_from_slice(&AUTHENTICATED_RECORD_MAGIC);
        record.extend_from_slice(&AUTHENTICATED_RECORD_FORMAT.to_be_bytes());
        record.extend_from_slice(self.session.session_id().as_array());
        record.extend_from_slice(&sequence.to_be_bytes());
        record.extend_from_slice(&frame_length.to_be_bytes());
        record.extend_from_slice(&frame);
        let tag = hmac_sha256(&self.key.0, &[RECORD_MAC_DOMAIN, &record]);
        record.extend_from_slice(tag.as_array());
        self.next_send_sequence = sequence
            .checked_add(1)
            .ok_or(AuthenticatedSessionError::SequenceOverflow)?;
        Ok(record)
    }

    pub fn seal_typed<C: PayloadCodec>(
        &mut self,
        producer: StableId,
        generation: Generation,
        codec: &C,
        value: &C::Value,
    ) -> Result<Vec<u8>, AuthenticatedSessionError> {
        let envelope = self
            .session
            .encode_typed_envelope(producer, generation, codec, value)
            .map_err(AuthenticatedSessionError::Session)?;
        self.seal_envelope(&envelope)
    }

    pub fn open_record(
        &mut self,
        record: &[u8],
    ) -> Result<DecodedEnvelope, AuthenticatedSessionError> {
        if self.poisoned {
            return Err(AuthenticatedSessionError::Poisoned);
        }
        match self.open_record_inner(record) {
            Ok(envelope) => Ok(envelope),
            Err(error) => {
                self.poisoned = true;
                Err(error)
            }
        }
    }

    pub fn open_typed<C: PayloadCodec>(
        &mut self,
        record: &[u8],
        codec: &C,
    ) -> Result<C::Value, AuthenticatedSessionError> {
        let envelope = self.open_record(record)?;
        self.session
            .decode_typed_envelope(&envelope, codec)
            .map_err(AuthenticatedSessionError::Session)
    }

    fn open_record_inner(
        &mut self,
        record: &[u8],
    ) -> Result<DecodedEnvelope, AuthenticatedSessionError> {
        let minimum = AUTHENTICATED_RECORD_PREFIX_BYTES + AUTHENTICATED_RECORD_TAG_BYTES;
        if record.len() < minimum {
            return Err(AuthenticatedSessionError::RecordTooShort {
                actual: record.len(),
                minimum,
                byte_offset: record.len(),
            });
        }
        if record[..4] != AUTHENTICATED_RECORD_MAGIC {
            return Err(AuthenticatedSessionError::Magic { byte_offset: 0 });
        }
        let format = read_u16(record, 4)?;
        if format != AUTHENTICATED_RECORD_FORMAT {
            return Err(AuthenticatedSessionError::Format {
                actual: format,
                expected: AUTHENTICATED_RECORD_FORMAT,
                byte_offset: 4,
            });
        }
        let session_end = 6 + 32;
        if !constant_time_eq(
            &record[6..session_end],
            self.session.session_id().as_array(),
        ) {
            return Err(AuthenticatedSessionError::SessionIdMismatch {
                session_id: self.session.session_id(),
                byte_offset: 6,
            });
        }
        let sequence = read_u64(record, session_end)?;
        if sequence != self.next_receive_sequence {
            return Err(AuthenticatedSessionError::SequenceMismatch {
                expected: self.next_receive_sequence,
                actual: sequence,
                session_id: self.session.session_id(),
                byte_offset: session_end,
            });
        }
        let length_offset = session_end + 8;
        let frame_length = usize::try_from(read_u32(record, length_offset)?).map_err(|_| {
            AuthenticatedSessionError::FrameLength {
                actual: usize::MAX,
                maximum: MAX_WIRE_FRAME_BYTES,
                byte_offset: length_offset,
            }
        })?;
        if frame_length > MAX_WIRE_FRAME_BYTES {
            return Err(AuthenticatedSessionError::FrameLength {
                actual: frame_length,
                maximum: MAX_WIRE_FRAME_BYTES,
                byte_offset: length_offset,
            });
        }
        let frame_start = AUTHENTICATED_RECORD_PREFIX_BYTES;
        let frame_end = frame_start.checked_add(frame_length).ok_or(
            AuthenticatedSessionError::LengthMismatch {
                actual: record.len(),
                expected: MAX_AUTHENTICATED_RECORD_BYTES,
                byte_offset: length_offset,
            },
        )?;
        let expected_length = frame_end.checked_add(AUTHENTICATED_RECORD_TAG_BYTES).ok_or(
            AuthenticatedSessionError::LengthMismatch {
                actual: record.len(),
                expected: MAX_AUTHENTICATED_RECORD_BYTES,
                byte_offset: length_offset,
            },
        )?;
        if record.len() != expected_length {
            return Err(AuthenticatedSessionError::LengthMismatch {
                actual: record.len(),
                expected: expected_length,
                byte_offset: length_offset,
            });
        }
        let observed_tag = &record[frame_end..expected_length];
        let expected_tag = hmac_sha256(
            &self.key.0,
            &[RECORD_MAC_DOMAIN, &record[..frame_end]],
        );
        if !constant_time_eq(observed_tag, expected_tag.as_array()) {
            return Err(AuthenticatedSessionError::MacMismatch {
                session_id: self.session.session_id(),
                byte_offset: frame_end,
            });
        }
        let envelope = self
            .session
            .decode_frame(&record[frame_start..frame_end])
            .map_err(AuthenticatedSessionError::Session)?;
        self.next_receive_sequence = sequence
            .checked_add(1)
            .ok_or(AuthenticatedSessionError::SequenceOverflow)?;
        Ok(envelope)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthenticatedSessionError {
    Poisoned,
    ZeroMacKey,
    RecordTooShort {
        actual: usize,
        minimum: usize,
        byte_offset: usize,
    },
    Magic {
        byte_offset: usize,
    },
    Format {
        actual: u16,
        expected: u16,
        byte_offset: usize,
    },
    SessionIdMismatch {
        session_id: Digest32,
        byte_offset: usize,
    },
    SequenceMismatch {
        expected: u64,
        actual: u64,
        session_id: Digest32,
        byte_offset: usize,
    },
    FrameLength {
        actual: usize,
        maximum: usize,
        byte_offset: usize,
    },
    LengthMismatch {
        actual: usize,
        expected: usize,
        byte_offset: usize,
    },
    MacMismatch {
        session_id: Digest32,
        byte_offset: usize,
    },
    SequenceOverflow,
    Session(WireSessionError),
}

impl fmt::Display for AuthenticatedSessionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Poisoned => formatter.write_str("authenticated wire session is poisoned"),
            Self::ZeroMacKey => formatter.write_str("authenticated wire MAC key is all zero"),
            Self::RecordTooShort {
                actual,
                minimum,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record ended at byte {byte_offset}: {actual} bytes, minimum is {minimum}"
            ),
            Self::Magic { byte_offset } => {
                write!(formatter, "authenticated record magic mismatch at byte {byte_offset}")
            }
            Self::Format {
                actual,
                expected,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record format at byte {byte_offset} is {actual}, expected {expected}"
            ),
            Self::SessionIdMismatch {
                session_id,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record session mismatch at byte {byte_offset} for session {session_id}"
            ),
            Self::SequenceMismatch {
                expected,
                actual,
                session_id,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record sequence at byte {byte_offset} is {actual}, expected {expected} for session {session_id}"
            ),
            Self::FrameLength {
                actual,
                maximum,
                byte_offset,
            } => write!(
                formatter,
                "authenticated frame length at byte {byte_offset} is {actual}, maximum is {maximum}"
            ),
            Self::LengthMismatch {
                actual,
                expected,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record length at byte {byte_offset} is {actual}, expected {expected}"
            ),
            Self::MacMismatch {
                session_id,
                byte_offset,
            } => write!(
                formatter,
                "authenticated record MAC mismatch at byte {byte_offset} for session {session_id}"
            ),
            Self::SequenceOverflow => formatter.write_str("authenticated record sequence overflow"),
            Self::Session(error) => error.fmt(formatter),
        }
    }
}

impl Error for AuthenticatedSessionError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Session(error) => Some(error),
            _ => None,
        }
    }
}

fn put_bytes(encoded: &mut Vec<u8>, value: &[u8]) {
    encoded.extend_from_slice(&(value.len() as u32).to_be_bytes());
    encoded.extend_from_slice(value);
}

fn decode_error_offset(error: &DecodeFrameError, encoded_length: usize) -> Option<usize> {
    match error {
        DecodeFrameError::Truncated => Some(encoded_length),
        DecodeFrameError::Magic => Some(0),
        DecodeFrameError::Version(_) => Some(4),
        DecodeFrameError::V1(_) | DecodeFrameError::V2(_) => None,
    }
}

fn hmac_sha256(key: &[u8; 32], parts: &[&[u8]]) -> Digest32 {
    let mut inner_pad = [0x36_u8; 64];
    let mut outer_pad = [0x5c_u8; 64];
    for (index, key_byte) in key.iter().enumerate() {
        inner_pad[index] ^= key_byte;
        outer_pad[index] ^= key_byte;
    }
    let capacity = parts
        .iter()
        .fold(inner_pad.len(), |total, part| total.saturating_add(part.len()));
    let mut inner = Vec::with_capacity(capacity);
    inner.extend_from_slice(&inner_pad);
    for part in parts {
        inner.extend_from_slice(part);
    }
    let inner_digest = Digest32::of_bytes(&inner);
    Digest32::of_parts(&[&outer_pad, inner_digest.as_array()])
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut difference = 0_u8;
    for (left, right) in left.iter().zip(right) {
        difference |= left ^ right;
    }
    difference == 0
}

fn read_u16(bytes: &[u8], start: usize) -> Result<u16, AuthenticatedSessionError> {
    let end = start.saturating_add(2);
    let raw: [u8; 2] = bytes
        .get(start..end)
        .ok_or(AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?
        .try_into()
        .map_err(|_| AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?;
    Ok(u16::from_be_bytes(raw))
}

fn read_u32(bytes: &[u8], start: usize) -> Result<u32, AuthenticatedSessionError> {
    let end = start.saturating_add(4);
    let raw: [u8; 4] = bytes
        .get(start..end)
        .ok_or(AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?
        .try_into()
        .map_err(|_| AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?;
    Ok(u32::from_be_bytes(raw))
}

fn read_u64(bytes: &[u8], start: usize) -> Result<u64, AuthenticatedSessionError> {
    let end = start.saturating_add(8);
    let raw: [u8; 8] = bytes
        .get(start..end)
        .ok_or(AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?
        .try_into()
        .map_err(|_| AuthenticatedSessionError::RecordTooShort {
            actual: bytes.len(),
            minimum: end,
            byte_offset: bytes.len(),
        })?;
    Ok(u64::from_be_bytes(raw))
}

#[cfg(test)]
mod tests {
    use std::error::Error;

    use crate::FrozenSchemaRegistryBuilder;
    use crate::SchemaDescriptor;
    use crate::SchemaPolicy;
    use crate::WireCapabilities;

    use super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct Message(String);

    struct Codec {
        descriptor: SchemaDescriptor,
    }

    impl PayloadCodec for Codec {
        type Value = Message;

        fn descriptor(&self) -> &SchemaDescriptor {
            &self.descriptor
        }

        fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
            if value.0.is_empty() {
                return Err(SchemaCodecError::Rejected("empty message"));
            }
            Ok(value.0.as_bytes().to_vec())
        }

        fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
            let value = std::str::from_utf8(payload)
                .map_err(|_| SchemaCodecError::Rejected("non-UTF-8 message"))?;
            if value.is_empty() {
                return Err(SchemaCodecError::Rejected("empty message"));
            }
            Ok(Message(value.to_string()))
        }
    }

    fn id(value: &str) -> Result<StableId, Box<dyn Error>> {
        Ok(StableId::new(value)?)
    }

    fn session(channel_binding: &[u8]) -> Result<(WireSession, Codec), Box<dyn Error>> {
        let schema = id("schema.secure-message.v1")?;
        let producer = id("producer.secure-test")?;
        let role = id("role.secure-test")?;
        let descriptor = SchemaDescriptor::new(
            schema,
            WireVersion::V2,
            WireVersion::V2,
            256,
        )?;
        let required = WireCapabilities::METADATA_BOUND_DIGEST
            .union(WireCapabilities::SCHEMA_ADMISSION);
        let policy = SchemaPolicy::new(
            descriptor.clone(),
            vec![producer],
            vec![role.clone()],
            required,
        )?;
        let mut builder = FrozenSchemaRegistryBuilder::new();
        builder.register(policy)?;
        let registry = Arc::new(builder.freeze()?);
        let offer = NegotiationOffer::current();
        let negotiated = negotiate(&offer, &offer, required)?;
        let transcript = NegotiationTranscript::from_offers(
            &offer,
            &offer,
            negotiated,
            registry.snapshot_digest(),
            channel_binding,
        )?;
        Ok((
            WireSession::new(negotiated, role, registry, transcript),
            Codec { descriptor },
        ))
    }

    #[test]
    fn typed_envelope_is_coupled_to_session_policy() -> Result<(), Box<dyn Error>> {
        let (session, codec) = session(&[7_u8; 32])?;
        let value = Message("hello".to_string());
        let envelope = session.encode_typed_envelope(
            id("producer.secure-test")?,
            Generation::new(1)?,
            &codec,
            &value,
        )?;
        assert_eq!(session.decode_typed_envelope(&envelope, &codec)?, value);
        Ok(())
    }

    #[test]
    fn authenticated_records_reject_tamper_replay_and_cross_session_use()
    -> Result<(), Box<dyn Error>> {
        let (sender_session, codec) = session(&[7_u8; 32])?;
        let (receiver_session, _) = session(&[7_u8; 32])?;
        let key = SessionMacKey::new([9_u8; 32])?;
        let mut sender = AuthenticatedWireSession::new(sender_session, key.clone());
        let mut receiver = AuthenticatedWireSession::new(receiver_session, key.clone());
        let record = sender.seal_typed(
            id("producer.secure-test")?,
            Generation::new(1)?,
            &codec,
            &Message("hello".to_string()),
        )?;
        assert_eq!(receiver.open_typed(&record, &codec)?, Message("hello".to_string()));
        assert!(matches!(
            receiver.open_record(&record),
            Err(AuthenticatedSessionError::SequenceMismatch { .. })
        ));
        assert!(receiver.is_poisoned());

        let (tamper_session, _) = session(&[7_u8; 32])?;
        let mut tamper_receiver = AuthenticatedWireSession::new(tamper_session, key.clone());
        let mut tampered = record.clone();
        let payload_index = AUTHENTICATED_RECORD_PREFIX_BYTES + 54;
        tampered[payload_index] ^= 1;
        assert!(matches!(
            tamper_receiver.open_record(&tampered),
            Err(AuthenticatedSessionError::MacMismatch { .. })
        ));

        let (other_session, _) = session(&[8_u8; 32])?;
        let mut other_receiver = AuthenticatedWireSession::new(other_session, key);
        assert!(matches!(
            other_receiver.open_record(&record),
            Err(AuthenticatedSessionError::SessionIdMismatch { .. })
        ));
        Ok(())
    }
}
