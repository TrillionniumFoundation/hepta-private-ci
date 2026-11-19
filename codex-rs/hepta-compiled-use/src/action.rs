//! Fixed typed action ABI and digest-bound frame validation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

pub const ACTION_ABI_VERSION_V1: u16 = 1;
pub const ACTION_FRAME_BYTES_V1: usize = 256;
pub(crate) const ACTION_PAYLOAD_OFFSET: usize = 92;
const ACTION_PAYLOAD_BYTES: usize = ACTION_FRAME_BYTES_V1 - ACTION_PAYLOAD_OFFSET;
const MAX_TEXT_BYTES: usize = ACTION_PAYLOAD_BYTES - 4;
const MAX_CAPTURE_PIXELS: u64 = 16_777_216;
const ACTION_MAGIC: &[u8; 4] = b"HCU1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum ActionOpcodeV1 {
    ReadAccessibilityTree = 1,
    Click = 2,
    TypeText = 3,
    Scroll = 4,
    CaptureRegion = 5,
}

impl ActionOpcodeV1 {
    fn from_byte(value: u8) -> Option<Self> {
        Some(match value {
            1 => Self::ReadAccessibilityTree,
            2 => Self::Click,
            3 => Self::TypeText,
            4 => Self::Scroll,
            5 => Self::CaptureRegion,
            _ => return None,
        })
    }

    pub(crate) const fn required_capability(self) -> CapabilityV1 {
        match self {
            Self::ReadAccessibilityTree => CapabilityV1::ReadAccessibilityTree,
            Self::Click => CapabilityV1::Click,
            Self::TypeText => CapabilityV1::TypeText,
            Self::Scroll => CapabilityV1::Scroll,
            Self::CaptureRegion => CapabilityV1::CaptureRegion,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u16)]
pub enum CapabilityV1 {
    ReadAccessibilityTree = 1,
    Click = 2,
    TypeText = 4,
    Scroll = 8,
    CaptureRegion = 16,
}

impl CapabilityV1 {
    const fn bit(self) -> u16 {
        self as u16
    }
}

const KNOWN_CAPABILITY_MASK: u16 = CapabilityV1::ReadAccessibilityTree as u16
    | CapabilityV1::Click as u16
    | CapabilityV1::TypeText as u16
    | CapabilityV1::Scroll as u16
    | CapabilityV1::CaptureRegion as u16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CapabilityGrantV1 {
    pub digest: Digest32,
    pub allowed: u16,
}

impl CapabilityGrantV1 {
    pub fn allows(self, capability: CapabilityV1) -> bool {
        self.allowed & capability.bit() != 0
    }

    pub(crate) fn is_well_formed(self) -> bool {
        !self.digest.is_zero() && self.allowed & !KNOWN_CAPABILITY_MASK == 0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionArgumentsV1 {
    ReadAccessibilityTree,
    /// `target_digest` identifies an element in a previously read accessibility tree.
    Click {
        target_digest: Digest32,
        x: i32,
        y: i32,
    },
    TypeText { text: String },
    Scroll { delta: i32 },
    CaptureRegion { x: i32, y: i32, width: u32, height: u32 },
}

impl ActionArgumentsV1 {
    pub(crate) fn opcode(&self) -> ActionOpcodeV1 {
        match self {
            Self::ReadAccessibilityTree => ActionOpcodeV1::ReadAccessibilityTree,
            Self::Click { .. } => ActionOpcodeV1::Click,
            Self::TypeText { .. } => ActionOpcodeV1::TypeText,
            Self::Scroll { .. } => ActionOpcodeV1::Scroll,
            Self::CaptureRegion { .. } => ActionOpcodeV1::CaptureRegion,
        }
    }

    fn encode(&self) -> Result<Vec<u8>, ActionErrorV1> {
        let mut bytes = Vec::with_capacity(ACTION_PAYLOAD_BYTES);
        match self {
            Self::ReadAccessibilityTree => {}
            Self::Click {
                target_digest,
                x,
                y,
            } => {
                if target_digest.is_zero() {
                    return Err(ActionErrorV1::MissingBinding);
                }
                bytes.extend_from_slice(target_digest.as_array());
                bytes.extend_from_slice(&x.to_be_bytes());
                bytes.extend_from_slice(&y.to_be_bytes());
            }
            Self::TypeText { text } => {
                let raw = text.as_bytes();
                if raw.is_empty() || raw.len() > MAX_TEXT_BYTES {
                    return Err(ActionErrorV1::TextLimit);
                }
                let len = u32::try_from(raw.len()).map_err(|_| ActionErrorV1::PayloadLimit)?;
                bytes.extend_from_slice(&len.to_be_bytes());
                bytes.extend_from_slice(raw);
            }
            Self::Scroll { delta } => bytes.extend_from_slice(&delta.to_be_bytes()),
            Self::CaptureRegion {
                x,
                y,
                width,
                height,
            } => {
                if *width == 0
                    || *height == 0
                    || u64::from(*width).saturating_mul(u64::from(*height)) > MAX_CAPTURE_PIXELS
                {
                    return Err(ActionErrorV1::InvalidGeometry);
                }
                bytes.extend_from_slice(&x.to_be_bytes());
                bytes.extend_from_slice(&y.to_be_bytes());
                bytes.extend_from_slice(&width.to_be_bytes());
                bytes.extend_from_slice(&height.to_be_bytes());
            }
        }
        if bytes.len() > ACTION_PAYLOAD_BYTES {
            return Err(ActionErrorV1::PayloadLimit);
        }
        Ok(bytes)
    }

    fn decode(opcode: ActionOpcodeV1, payload: &[u8]) -> Result<Self, ActionErrorV1> {
        let take_i32 = |bytes: &[u8]| -> Result<i32, ActionErrorV1> {
            let value: [u8; 4] = bytes.try_into().map_err(|_| ActionErrorV1::PayloadShape)?;
            Ok(i32::from_be_bytes(value))
        };
        match opcode {
            ActionOpcodeV1::ReadAccessibilityTree if payload.is_empty() => {
                Ok(Self::ReadAccessibilityTree)
            }
            ActionOpcodeV1::Click if payload.len() == 40 => {
                let target_digest = Digest32::from_array(
                    payload[..32]
                        .try_into()
                        .map_err(|_| ActionErrorV1::PayloadShape)?,
                );
                if target_digest.is_zero() {
                    return Err(ActionErrorV1::MissingBinding);
                }
                Ok(Self::Click {
                    target_digest,
                    x: take_i32(&payload[32..36])?,
                    y: take_i32(&payload[36..])?,
                })
            }
            ActionOpcodeV1::TypeText if payload.len() >= 4 => {
                let length = u32::from_be_bytes(
                    payload[..4]
                        .try_into()
                        .map_err(|_| ActionErrorV1::PayloadShape)?,
                ) as usize;
                if length == 0 || length != payload.len() - 4 || length > MAX_TEXT_BYTES {
                    return Err(ActionErrorV1::PayloadShape);
                }
                let text = std::str::from_utf8(&payload[4..])
                    .map_err(|_| ActionErrorV1::TextEncoding)?
                    .to_owned();
                Ok(Self::TypeText { text })
            }
            ActionOpcodeV1::Scroll if payload.len() == 4 => Ok(Self::Scroll {
                delta: take_i32(payload)?,
            }),
            ActionOpcodeV1::CaptureRegion if payload.len() == 16 => {
                let width = u32::from_be_bytes(
                    payload[8..12]
                        .try_into()
                        .map_err(|_| ActionErrorV1::PayloadShape)?,
                );
                let height = u32::from_be_bytes(
                    payload[12..16]
                        .try_into()
                        .map_err(|_| ActionErrorV1::PayloadShape)?,
                );
                if width == 0
                    || height == 0
                    || u64::from(width).saturating_mul(u64::from(height)) > MAX_CAPTURE_PIXELS
                {
                    return Err(ActionErrorV1::InvalidGeometry);
                }
                Ok(Self::CaptureRegion {
                    x: take_i32(&payload[..4])?,
                    y: take_i32(&payload[4..8])?,
                    width,
                    height,
                })
            }
            _ => Err(ActionErrorV1::PayloadShape),
        }
    }
}

/// One fixed-size, digest-bound action frame.  It is data only; there is no
/// executable payload or pointer in the ABI.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionFrameV1 {
    pub generation: u64,
    pub sequence: u64,
    pub capability_digest: Digest32,
    pub arguments: ActionArgumentsV1,
}

impl ActionFrameV1 {
    pub fn encode(&self) -> Result<[u8; ACTION_FRAME_BYTES_V1], ActionErrorV1> {
        if self.generation == 0 || self.sequence == 0 || self.capability_digest.is_zero() {
            return Err(ActionErrorV1::MissingBinding);
        }
        let opcode = self.arguments.opcode();
        let payload = self.arguments.encode()?;
        let digest = action_digest(
            self.generation,
            self.sequence,
            self.capability_digest,
            opcode,
            &payload,
        );
        let mut output = [0_u8; ACTION_FRAME_BYTES_V1];
        output[..4].copy_from_slice(ACTION_MAGIC);
        output[4..6].copy_from_slice(&ACTION_ABI_VERSION_V1.to_be_bytes());
        output[6] = opcode as u8;
        output[8..16].copy_from_slice(&self.generation.to_be_bytes());
        output[16..24].copy_from_slice(&self.sequence.to_be_bytes());
        output[24..56].copy_from_slice(self.capability_digest.as_array());
        output[56..88].copy_from_slice(digest.as_array());
        output[88..92].copy_from_slice(
            &u32::try_from(payload.len())
                .map_err(|_| ActionErrorV1::PayloadLimit)?
                .to_be_bytes(),
        );
        output[ACTION_PAYLOAD_OFFSET..ACTION_PAYLOAD_OFFSET + payload.len()]
            .copy_from_slice(&payload);
        Ok(output)
    }

    pub fn decode(bytes: &[u8; ACTION_FRAME_BYTES_V1]) -> Result<Self, ActionErrorV1> {
        if &bytes[..4] != ACTION_MAGIC
            || u16::from_be_bytes(
                bytes[4..6]
                    .try_into()
                    .map_err(|_| ActionErrorV1::AbiMismatch)?,
            )
                != ACTION_ABI_VERSION_V1
            || bytes[7] != 0
        {
            return Err(ActionErrorV1::AbiMismatch);
        }
        let opcode = ActionOpcodeV1::from_byte(bytes[6]).ok_or(ActionErrorV1::UnknownOpcode)?;
        let generation = u64::from_be_bytes(
            bytes[8..16]
                .try_into()
                .map_err(|_| ActionErrorV1::AbiMismatch)?,
        );
        let sequence = u64::from_be_bytes(
            bytes[16..24]
                .try_into()
                .map_err(|_| ActionErrorV1::AbiMismatch)?,
        );
        let capability_digest = Digest32::from_array(
            bytes[24..56]
                .try_into()
                .map_err(|_| ActionErrorV1::AbiMismatch)?,
        );
        let claimed_digest = Digest32::from_array(
            bytes[56..88]
                .try_into()
                .map_err(|_| ActionErrorV1::AbiMismatch)?,
        );
        let payload_len = u32::from_be_bytes(
            bytes[88..92]
                .try_into()
                .map_err(|_| ActionErrorV1::AbiMismatch)?,
        ) as usize;
        if generation == 0 || sequence == 0 || capability_digest.is_zero() {
            return Err(ActionErrorV1::MissingBinding);
        }
        if payload_len > ACTION_PAYLOAD_BYTES {
            return Err(ActionErrorV1::PayloadLimit);
        }
        if bytes[ACTION_PAYLOAD_OFFSET + payload_len..]
            .iter()
            .any(|byte| *byte != 0)
        {
            return Err(ActionErrorV1::NonCanonicalPadding);
        }
        let payload = &bytes[ACTION_PAYLOAD_OFFSET..ACTION_PAYLOAD_OFFSET + payload_len];
        if claimed_digest
            != action_digest(generation, sequence, capability_digest, opcode, payload)
        {
            return Err(ActionErrorV1::DigestMismatch);
        }
        Ok(Self {
            generation,
            sequence,
            capability_digest,
            arguments: ActionArgumentsV1::decode(opcode, payload)?,
        })
    }
}

fn action_digest(
    generation: u64,
    sequence: u64,
    capability_digest: Digest32,
    opcode: ActionOpcodeV1,
    payload: &[u8],
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.compiled-use.action.v1\0",
        &generation.to_be_bytes(),
        &sequence.to_be_bytes(),
        capability_digest.as_array(),
        &[opcode as u8],
        payload,
    ])
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionErrorV1 {
    AbiMismatch,
    UnknownOpcode,
    MissingBinding,
    PayloadLimit,
    PayloadShape,
    TextLimit,
    TextEncoding,
    InvalidGeometry,
    NonCanonicalPadding,
    DigestMismatch,
    InvalidCapabilityGrant,
    CapabilityDenied,
    GenerationMismatch,
    SequenceMismatch,
    QueueFull,
    QueueEmpty,
    ProposalLimit,
}

impl fmt::Display for ActionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ActionErrorV1 {}
