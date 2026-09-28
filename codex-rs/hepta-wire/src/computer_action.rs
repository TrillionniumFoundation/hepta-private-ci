//! Canonical bounded binary motor frame for local computer actions.
//!
//! The frame is a transport optimization for an already admitted semantic
//! action. It never carries authority, credentials, native code, shell text, or
//! a terminal-success claim. Effect owners still consume final-use authority and
//! independently observe terminal outcomes.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 4] = b"HAC1";
pub const COMPUTER_ACTION_FRAME_VERSION: u16 = 1;
const TARGET_FLAG: u16 = 1;
const KNOWN_FLAGS: u16 = TARGET_FLAG;
const FRAME_DOMAIN: &[u8] = b"hepta.computer-action.frame.v1";
const PAYLOAD_DOMAIN: &[u8] = b"hepta.computer-action.payload.v1";
const CHECKSUM_BYTES: usize = 32;
pub const MAX_COMPUTER_ACTION_FRAME_BYTES: usize = 128 * 1024;
const MAX_REFERENCE_BYTES: usize = 128;
// The first registered HAC1 profile is shared with JavaScript desktop owners.
// Reject unrepresentable u64s rather than rounding a target generation/deadline.
const MAX_PORTABLE_INTEGER: u64 = (1_u64 << 53) - 1;
const MAX_WAIT_MICROS: u64 = 60_000_000;
const MAX_SCROLL_MILLI: i32 = 100_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u16)]
pub enum ComputerActionOpcodeV1 {
    FocusTarget = 1,
    ActivateTarget = 2,
    TypeTextReference = 3,
    Scroll = 4,
    NavigateReference = 5,
    OpenPathReference = 6,
    RevealPathReference = 7,
    CopyTextReference = 8,
    NotifyReference = 9,
    WaitObservation = 10,
    RequestEvidence = 11,
    Stop = 12,
}

impl ComputerActionOpcodeV1 {
    fn from_code(value: u16) -> Result<Self, ComputerActionCodecError> {
        match value {
            1 => Ok(Self::FocusTarget),
            2 => Ok(Self::ActivateTarget),
            3 => Ok(Self::TypeTextReference),
            4 => Ok(Self::Scroll),
            5 => Ok(Self::NavigateReference),
            6 => Ok(Self::OpenPathReference),
            7 => Ok(Self::RevealPathReference),
            8 => Ok(Self::CopyTextReference),
            9 => Ok(Self::NotifyReference),
            10 => Ok(Self::WaitObservation),
            11 => Ok(Self::RequestEvidence),
            12 => Ok(Self::Stop),
            _ => Err(ComputerActionCodecError::UnknownOpcode(value)),
        }
    }

    const fn requires_target(self) -> bool {
        matches!(
            self,
            Self::FocusTarget | Self::ActivateTarget | Self::TypeTextReference | Self::Scroll
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ComputerActionPayloadV1 {
    None,
    Reference(StableId),
    ScrollDelta {
        horizontal_milli: i32,
        vertical_milli: i32,
    },
    WaitMicros(u64),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ComputerActionFrameV1 {
    pub operation_id: StableId,
    pub subject_id: StableId,
    pub actuator_id: StableId,
    pub opcode: ComputerActionOpcodeV1,
    pub target_ref: Option<StableId>,
    pub body_generation: u64,
    pub session_generation: u64,
    pub observation_revision: u64,
    pub deadline_monotonic_micros: u64,
    pub precondition_digest: Digest32,
    pub argument_payload_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub expected_postcondition_digest: Digest32,
    pub payload: ComputerActionPayloadV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ComputerActionCodecError {
    FrameTooLarge,
    Truncated,
    Magic,
    Version(u16),
    UnknownOpcode(u16),
    UnknownFlags(u16),
    ReservedBits,
    InvalidIdentifier,
    InvalidGeneration,
    InvalidDeadline,
    EmptyDigest(&'static str),
    TargetMismatch,
    PayloadMismatch,
    PayloadDigestMismatch,
    PayloadLimit,
    ChecksumMismatch,
    TrailingBytes,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for ComputerActionCodecError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ComputerActionCodecError {}

pub fn computer_action_payload_digest_v1(
    opcode: ComputerActionOpcodeV1,
    payload: &ComputerActionPayloadV1,
) -> Result<Digest32, ComputerActionCodecError> {
    let bytes = encode_payload(opcode, payload)?;
    Ok(Digest32::of_parts(&[PAYLOAD_DOMAIN, &bytes]))
}

pub fn computer_action_frame_digest_v1(
    frame: &ComputerActionFrameV1,
) -> Result<Digest32, ComputerActionCodecError> {
    let bytes = encode_frame_body(frame)?;
    Ok(Digest32::of_parts(&[FRAME_DOMAIN, &bytes]))
}

/// Digest consumed by the separately authorized effect owner. It binds the
/// semantic action, exact generations and target, argument payload digest,
/// externally resolved final-payload digest and expected postcondition. The
/// codec does not mint or validate the grant that consumes this value.
pub fn computer_action_authority_binding_digest_v1(
    frame: &ComputerActionFrameV1,
) -> Result<Digest32, ComputerActionCodecError> {
    computer_action_frame_digest_v1(frame)
}

pub fn encode_computer_action_frame_v1(
    frame: &ComputerActionFrameV1,
) -> Result<Vec<u8>, ComputerActionCodecError> {
    let body = encode_frame_body(frame)?;
    let digest = Digest32::of_parts(&[FRAME_DOMAIN, &body]);
    let capacity = body
        .len()
        .checked_add(CHECKSUM_BYTES)
        .ok_or(ComputerActionCodecError::Arithmetic)?;
    if capacity > MAX_COMPUTER_ACTION_FRAME_BYTES {
        return Err(ComputerActionCodecError::FrameTooLarge);
    }
    let mut bytes = Vec::with_capacity(capacity);
    bytes.extend_from_slice(&body);
    bytes.extend_from_slice(digest.as_array());
    Ok(bytes)
}

pub fn decode_computer_action_frame_v1(
    bytes: &[u8],
) -> Result<ComputerActionFrameV1, ComputerActionCodecError> {
    if bytes.len() > MAX_COMPUTER_ACTION_FRAME_BYTES {
        return Err(ComputerActionCodecError::FrameTooLarge);
    }
    if bytes.len() < CHECKSUM_BYTES {
        return Err(ComputerActionCodecError::Truncated);
    }
    let body_len = bytes.len() - CHECKSUM_BYTES;
    let (body, checksum) = bytes.split_at(body_len);
    let expected = Digest32::of_parts(&[FRAME_DOMAIN, body]);
    if checksum != expected.as_array() {
        return Err(ComputerActionCodecError::ChecksumMismatch);
    }

    let mut decoder = Decoder::new(body);
    if decoder.take(4)? != MAGIC {
        return Err(ComputerActionCodecError::Magic);
    }
    let version = decoder.u16()?;
    if version != COMPUTER_ACTION_FRAME_VERSION {
        return Err(ComputerActionCodecError::Version(version));
    }
    let opcode = ComputerActionOpcodeV1::from_code(decoder.u16()?)?;
    let flags = decoder.u16()?;
    if flags & !KNOWN_FLAGS != 0 {
        return Err(ComputerActionCodecError::UnknownFlags(flags));
    }
    if decoder.u16()? != 0 {
        return Err(ComputerActionCodecError::ReservedBits);
    }
    let body_generation = decoder.u64()?;
    let session_generation = decoder.u64()?;
    let observation_revision = decoder.u64()?;
    let deadline_monotonic_micros = decoder.u64()?;
    let operation_id = decoder.id()?;
    let subject_id = decoder.id()?;
    let actuator_id = decoder.id()?;
    let target_ref = if flags & TARGET_FLAG != 0 {
        Some(decoder.id()?)
    } else {
        None
    };
    let precondition_digest = decoder.digest()?;
    let argument_payload_digest = decoder.digest()?;
    let final_payload_digest = decoder.digest()?;
    let expected_postcondition_digest = decoder.digest()?;
    let payload_len =
        usize::try_from(decoder.u32()?).map_err(|_| ComputerActionCodecError::Arithmetic)?;
    let payload_bytes = decoder.take(payload_len)?;
    if !decoder.remaining().is_empty() {
        return Err(ComputerActionCodecError::TrailingBytes);
    }
    let payload = decode_payload(opcode, payload_bytes)?;
    let frame = ComputerActionFrameV1 {
        operation_id,
        subject_id,
        actuator_id,
        opcode,
        target_ref,
        body_generation,
        session_generation,
        observation_revision,
        deadline_monotonic_micros,
        precondition_digest,
        argument_payload_digest,
        final_payload_digest,
        expected_postcondition_digest,
        payload,
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_frame(&frame)?;
    Ok(frame)
}

fn encode_frame_body(frame: &ComputerActionFrameV1) -> Result<Vec<u8>, ComputerActionCodecError> {
    validate_frame(frame)?;
    let payload = encode_payload(frame.opcode, &frame.payload)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&COMPUTER_ACTION_FRAME_VERSION.to_be_bytes());
    bytes.extend_from_slice(&(frame.opcode as u16).to_be_bytes());
    let flags = if frame.target_ref.is_some() {
        TARGET_FLAG
    } else {
        0
    };
    bytes.extend_from_slice(&flags.to_be_bytes());
    bytes.extend_from_slice(&0_u16.to_be_bytes());
    for value in [
        frame.body_generation,
        frame.session_generation,
        frame.observation_revision,
        frame.deadline_monotonic_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    push_id(&mut bytes, &frame.operation_id)?;
    push_id(&mut bytes, &frame.subject_id)?;
    push_id(&mut bytes, &frame.actuator_id)?;
    if let Some(target) = &frame.target_ref {
        push_id(&mut bytes, target)?;
    }
    for digest in [
        frame.precondition_digest,
        frame.argument_payload_digest,
        frame.final_payload_digest,
        frame.expected_postcondition_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let payload_len =
        u32::try_from(payload.len()).map_err(|_| ComputerActionCodecError::PayloadLimit)?;
    bytes.extend_from_slice(&payload_len.to_be_bytes());
    bytes.extend_from_slice(&payload);
    if bytes
        .len()
        .checked_add(CHECKSUM_BYTES)
        .is_none_or(|length| length > MAX_COMPUTER_ACTION_FRAME_BYTES)
    {
        return Err(ComputerActionCodecError::FrameTooLarge);
    }
    Ok(bytes)
}

fn validate_frame(frame: &ComputerActionFrameV1) -> Result<(), ComputerActionCodecError> {
    if frame.authority.grants_any() {
        return Err(ComputerActionCodecError::AuthorityGranted);
    }
    if [
        frame.body_generation,
        frame.session_generation,
        frame.observation_revision,
    ]
    .iter()
    .any(|value| !(1..=MAX_PORTABLE_INTEGER).contains(value))
    {
        return Err(ComputerActionCodecError::InvalidGeneration);
    }
    if !(1..=MAX_PORTABLE_INTEGER).contains(&frame.deadline_monotonic_micros) {
        return Err(ComputerActionCodecError::InvalidDeadline);
    }
    for (name, digest) in [
        ("precondition", frame.precondition_digest),
        ("argument payload", frame.argument_payload_digest),
        ("final payload", frame.final_payload_digest),
        ("postcondition", frame.expected_postcondition_digest),
    ] {
        if digest.is_zero() {
            return Err(ComputerActionCodecError::EmptyDigest(name));
        }
    }
    if frame.opcode.requires_target() != frame.target_ref.is_some() {
        return Err(ComputerActionCodecError::TargetMismatch);
    }
    if computer_action_payload_digest_v1(frame.opcode, &frame.payload)?
        != frame.argument_payload_digest
    {
        return Err(ComputerActionCodecError::PayloadDigestMismatch);
    }
    Ok(())
}

fn encode_payload(
    opcode: ComputerActionOpcodeV1,
    payload: &ComputerActionPayloadV1,
) -> Result<Vec<u8>, ComputerActionCodecError> {
    match (opcode, payload) {
        (
            ComputerActionOpcodeV1::FocusTarget
            | ComputerActionOpcodeV1::ActivateTarget
            | ComputerActionOpcodeV1::RequestEvidence
            | ComputerActionOpcodeV1::Stop,
            ComputerActionPayloadV1::None,
        ) => Ok(Vec::new()),
        (
            ComputerActionOpcodeV1::TypeTextReference
            | ComputerActionOpcodeV1::NavigateReference
            | ComputerActionOpcodeV1::OpenPathReference
            | ComputerActionOpcodeV1::RevealPathReference
            | ComputerActionOpcodeV1::CopyTextReference
            | ComputerActionOpcodeV1::NotifyReference,
            ComputerActionPayloadV1::Reference(reference),
        ) => {
            let mut bytes = Vec::new();
            push_id(&mut bytes, reference)?;
            Ok(bytes)
        }
        (
            ComputerActionOpcodeV1::Scroll,
            ComputerActionPayloadV1::ScrollDelta {
                horizontal_milli,
                vertical_milli,
            },
        ) => {
            if horizontal_milli.unsigned_abs() > MAX_SCROLL_MILLI as u32
                || vertical_milli.unsigned_abs() > MAX_SCROLL_MILLI as u32
                || (*horizontal_milli == 0 && *vertical_milli == 0)
            {
                return Err(ComputerActionCodecError::PayloadLimit);
            }
            let mut bytes = Vec::with_capacity(8);
            bytes.extend_from_slice(&horizontal_milli.to_be_bytes());
            bytes.extend_from_slice(&vertical_milli.to_be_bytes());
            Ok(bytes)
        }
        (ComputerActionOpcodeV1::WaitObservation, ComputerActionPayloadV1::WaitMicros(wait))
            if (1..=MAX_WAIT_MICROS).contains(wait) =>
        {
            Ok(wait.to_be_bytes().to_vec())
        }
        _ => Err(ComputerActionCodecError::PayloadMismatch),
    }
}

fn decode_payload(
    opcode: ComputerActionOpcodeV1,
    bytes: &[u8],
) -> Result<ComputerActionPayloadV1, ComputerActionCodecError> {
    match opcode {
        ComputerActionOpcodeV1::FocusTarget
        | ComputerActionOpcodeV1::ActivateTarget
        | ComputerActionOpcodeV1::RequestEvidence
        | ComputerActionOpcodeV1::Stop => {
            if bytes.is_empty() {
                Ok(ComputerActionPayloadV1::None)
            } else {
                Err(ComputerActionCodecError::PayloadMismatch)
            }
        }
        ComputerActionOpcodeV1::TypeTextReference
        | ComputerActionOpcodeV1::NavigateReference
        | ComputerActionOpcodeV1::OpenPathReference
        | ComputerActionOpcodeV1::RevealPathReference
        | ComputerActionOpcodeV1::CopyTextReference
        | ComputerActionOpcodeV1::NotifyReference => {
            let mut decoder = Decoder::new(bytes);
            let reference = decoder.id()?;
            if !decoder.remaining().is_empty() {
                return Err(ComputerActionCodecError::TrailingBytes);
            }
            Ok(ComputerActionPayloadV1::Reference(reference))
        }
        ComputerActionOpcodeV1::Scroll => {
            if bytes.len() != 8 {
                return Err(ComputerActionCodecError::PayloadMismatch);
            }
            let mut decoder = Decoder::new(bytes);
            Ok(ComputerActionPayloadV1::ScrollDelta {
                horizontal_milli: decoder.i32()?,
                vertical_milli: decoder.i32()?,
            })
        }
        ComputerActionOpcodeV1::WaitObservation => {
            if bytes.len() != 8 {
                return Err(ComputerActionCodecError::PayloadMismatch);
            }
            let mut decoder = Decoder::new(bytes);
            Ok(ComputerActionPayloadV1::WaitMicros(decoder.u64()?))
        }
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ComputerActionCodecError> {
    let raw = value.as_str().as_bytes();
    if raw.is_empty() || raw.len() > MAX_REFERENCE_BYTES {
        return Err(ComputerActionCodecError::InvalidIdentifier);
    }
    let length = u16::try_from(raw.len()).map_err(|_| ComputerActionCodecError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

struct Decoder<'a> {
    remaining: &'a [u8],
}

impl<'a> Decoder<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { remaining: bytes }
    }

    fn remaining(&self) -> &'a [u8] {
        self.remaining
    }

    fn take(&mut self, length: usize) -> Result<&'a [u8], ComputerActionCodecError> {
        if self.remaining.len() < length {
            return Err(ComputerActionCodecError::Truncated);
        }
        let (value, remaining) = self.remaining.split_at(length);
        self.remaining = remaining;
        Ok(value)
    }

    fn u16(&mut self) -> Result<u16, ComputerActionCodecError> {
        let mut bytes = [0_u8; 2];
        bytes.copy_from_slice(self.take(2)?);
        Ok(u16::from_be_bytes(bytes))
    }

    fn u32(&mut self) -> Result<u32, ComputerActionCodecError> {
        let mut bytes = [0_u8; 4];
        bytes.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(bytes))
    }

    fn i32(&mut self) -> Result<i32, ComputerActionCodecError> {
        let mut bytes = [0_u8; 4];
        bytes.copy_from_slice(self.take(4)?);
        Ok(i32::from_be_bytes(bytes))
    }

    fn u64(&mut self) -> Result<u64, ComputerActionCodecError> {
        let mut bytes = [0_u8; 8];
        bytes.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(bytes))
    }

    fn id(&mut self) -> Result<StableId, ComputerActionCodecError> {
        let length = usize::from(self.u16()?);
        if length == 0 || length > MAX_REFERENCE_BYTES {
            return Err(ComputerActionCodecError::InvalidIdentifier);
        }
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| ComputerActionCodecError::InvalidIdentifier)?;
        StableId::new(value.to_owned()).map_err(|_| ComputerActionCodecError::InvalidIdentifier)
    }

    fn digest(&mut self) -> Result<Digest32, ComputerActionCodecError> {
        let mut bytes = [0_u8; 32];
        bytes.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(bytes))
    }
}

#[cfg(test)]
#[path = "computer_action_tests.rs"]
mod tests;
