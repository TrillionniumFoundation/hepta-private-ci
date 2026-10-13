//! Proposal-only compiled computer-use transport.
//!
//! This crate is intentionally a fixed-ABI *data plane* scaffold.  It can
//! validate and queue five bounded UI actions without a model-to-tool RPC on
//! the hot path, but it never accepts machine code, writes executable memory,
//! grants capabilities or invokes an OS/browser API.  A separately owned,
//! reviewed sandbox may implement [`SandboxActionPortV1`] later.

#![forbid(unsafe_code)]

use std::collections::VecDeque;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

pub const ACTION_ABI_VERSION_V1: u16 = 1;
pub const ACTION_FRAME_BYTES_V1: usize = 256;
const ACTION_PAYLOAD_OFFSET: usize = 92;
const ACTION_PAYLOAD_BYTES: usize = ACTION_FRAME_BYTES_V1 - ACTION_PAYLOAD_OFFSET;
const MAX_QUEUE_CAPACITY: usize = 1024;
const MAX_PROPOSAL_ACTIONS: usize = 64;
const MAX_TEXT_BYTES: usize = ACTION_PAYLOAD_BYTES - 4;
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

    const fn required_capability(self) -> CapabilityV1 {
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CapabilityGrantV1 {
    pub digest: Digest32,
    pub allowed: u16,
}

impl CapabilityGrantV1 {
    pub fn allows(self, capability: CapabilityV1) -> bool {
        self.allowed & capability.bit() != 0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ActionArgumentsV1 {
    ReadAccessibilityTree,
    Click { x: i32, y: i32 },
    TypeText { text: String },
    Scroll { delta: i32 },
    CaptureRegion { x: i32, y: i32, width: u32, height: u32 },
}

impl ActionArgumentsV1 {
    fn opcode(&self) -> ActionOpcodeV1 {
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
            Self::Click { x, y } => {
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
                if *width == 0 || *height == 0 {
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
            ActionOpcodeV1::Click if payload.len() == 8 => Ok(Self::Click {
                x: take_i32(&payload[..4])?,
                y: take_i32(&payload[4..])?,
            }),
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
                if width == 0 || height == 0 {
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

/// A compiled-use action plan is persisted as a proposal before a product
/// caller binds it to a sandbox. It contains only typed frames, never code.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompiledUseProposalV1 {
    pub generation: u64,
    pub capability_digest: Digest32,
    pub actions: Vec<ActionFrameV1>,
    pub proposal_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn propose_compiled_use_v1(
    verifier: ActionVerifierV1,
    actions: Vec<ActionFrameV1>,
) -> Result<CompiledUseProposalV1, ActionErrorV1> {
    if actions.is_empty() || actions.len() > MAX_PROPOSAL_ACTIONS {
        return Err(ActionErrorV1::ProposalLimit);
    }
    for (index, action) in actions.iter().enumerate() {
        verifier.verify(action)?;
        let expected = u64::try_from(index)
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or(ActionErrorV1::SequenceMismatch)?;
        if action.sequence != expected {
            return Err(ActionErrorV1::SequenceMismatch);
        }
    }
    let mut bytes = b"hepta.compiled-use.proposal.v1\0".to_vec();
    bytes.extend_from_slice(&verifier.generation.to_be_bytes());
    bytes.extend_from_slice(verifier.grant.digest.as_array());
    for action in &actions {
        bytes.extend_from_slice(&action.encode()?);
    }
    Ok(CompiledUseProposalV1 {
        generation: verifier.generation,
        capability_digest: verifier.grant.digest,
        actions,
        proposal_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn verify_compiled_use_proposal_v1(
    verifier: ActionVerifierV1,
    proposal: &CompiledUseProposalV1,
) -> Result<(), ActionErrorV1> {
    if proposal.authority.grants_any()
        || proposal.generation != verifier.generation
        || proposal.capability_digest != verifier.grant.digest
    {
        return Err(ActionErrorV1::CapabilityDenied);
    }
    let rebuilt = propose_compiled_use_v1(verifier, proposal.actions.clone())?;
    if rebuilt.proposal_digest != proposal.proposal_digest {
        return Err(ActionErrorV1::DigestMismatch);
    }
    Ok(())
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

/// Validates frames before they enter the local queue.  This is a verifier,
/// not an authority issuer; the grant digest and mask must be supplied by the
/// existing control plane.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ActionVerifierV1 {
    pub generation: u64,
    pub grant: CapabilityGrantV1,
}

/// A frame that passed the exact verifier binding. The inner frame is private
/// so a sandbox port cannot be called with an unchecked action by accident.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedActionV1(ActionFrameV1);

impl VerifiedActionV1 {
    #[must_use]
    pub fn frame(&self) -> &ActionFrameV1 {
        &self.0
    }
}

impl ActionVerifierV1 {
    pub fn verify(&self, action: &ActionFrameV1) -> Result<(), ActionErrorV1> {
        self.verify_and_bind(action).map(|_| ())
    }

    pub fn verify_and_bind(
        &self,
        action: &ActionFrameV1,
    ) -> Result<VerifiedActionV1, ActionErrorV1> {
        if action.generation != self.generation {
            return Err(ActionErrorV1::GenerationMismatch);
        }
        if action.capability_digest != self.grant.digest
            || !self.grant.allows(action.arguments.opcode().required_capability())
        {
            return Err(ActionErrorV1::CapabilityDenied);
        }
        action.encode().map(|_| VerifiedActionV1(action.clone()))
    }
}

/// Bounded shared-memory-shaped queue.  The backing is deliberately owned by
/// this process and represented as fixed frames; an OS shared-memory adapter
/// can implement the same ABI later without granting this crate unsafe memory
/// access or execution authority.
#[derive(Debug)]
pub struct SharedMemoryQueueV1 {
    verifier: ActionVerifierV1,
    capacity: usize,
    next_sequence: u64,
    frames: VecDeque<[u8; ACTION_FRAME_BYTES_V1]>,
}

impl SharedMemoryQueueV1 {
    pub fn new(verifier: ActionVerifierV1, capacity: usize) -> Result<Self, ActionErrorV1> {
        if capacity == 0 || capacity > MAX_QUEUE_CAPACITY || verifier.generation == 0 {
            return Err(ActionErrorV1::MissingBinding);
        }
        if verifier.grant.digest.is_zero() {
            return Err(ActionErrorV1::MissingBinding);
        }
        Ok(Self {
            verifier,
            capacity,
            next_sequence: 1,
            frames: VecDeque::with_capacity(capacity),
        })
    }

    pub fn push(&mut self, action: ActionFrameV1) -> Result<(), ActionErrorV1> {
        let _verified = self.verifier.verify_and_bind(&action)?;
        if action.sequence != self.next_sequence {
            return Err(ActionErrorV1::SequenceMismatch);
        }
        if self.frames.len() >= self.capacity {
            return Err(ActionErrorV1::QueueFull);
        }
        self.frames.push_back(action.encode()?);
        self.next_sequence = self
            .next_sequence
            .checked_add(1)
            .ok_or(ActionErrorV1::SequenceMismatch)?;
        Ok(())
    }

    /// Pop a frame only after rechecking its ABI, digest, capability and
    /// generation against this queue's verifier.
    pub fn pop(&mut self) -> Result<VerifiedActionV1, ActionErrorV1> {
        let frame = self.frames.pop_front().ok_or(ActionErrorV1::QueueEmpty)?;
        let action = ActionFrameV1::decode(&frame)?;
        self.verifier.verify_and_bind(&action)
    }

    pub fn len(&self) -> usize {
        self.frames.len()
    }

    pub fn is_empty(&self) -> bool {
        self.frames.is_empty()
    }
}

/// A capability-aware execution boundary owned by a separate sandbox.  This
/// crate only defines the ABI and verification contract.
pub trait SandboxActionPortV1 {
    type Output;
    type Error: StdError;

    fn submit(&mut self, action: VerifiedActionV1) -> Result<Self::Output, Self::Error>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SandboxErrorV1 {
    NotConfigured,
    Denied,
}
impl fmt::Display for SandboxErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for SandboxErrorV1 {}

/// Safe default: the scaffold can never turn a proposal into an OS effect.
#[derive(Debug, Default)]
pub struct DenyByDefaultSandboxV1;

impl SandboxActionPortV1 for DenyByDefaultSandboxV1 {
    type Output = ();
    type Error = SandboxErrorV1;

    fn submit(&mut self, _action: VerifiedActionV1) -> Result<Self::Output, Self::Error> {
        Err(SandboxErrorV1::NotConfigured)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }
    fn grant() -> CapabilityGrantV1 {
        CapabilityGrantV1 {
            digest: digest(b"grant"),
            allowed: u16::MAX,
        }
    }
    fn verifier() -> ActionVerifierV1 {
        ActionVerifierV1 {
            generation: 7,
            grant: grant(),
        }
    }
    fn click(sequence: u64) -> ActionFrameV1 {
        ActionFrameV1 {
            generation: 7,
            sequence,
            capability_digest: grant().digest,
            arguments: ActionArgumentsV1::Click { x: 3, y: 4 },
        }
    }

    #[test]
    fn fixed_abi_round_trips_without_executable_payload() {
        let frame = click(1).encode().expect("encode");
        assert_eq!(frame.len(), ACTION_FRAME_BYTES_V1);
        assert!(frame[ACTION_PAYLOAD_OFFSET + 8..].iter().all(|b| *b == 0));
        assert_eq!(ActionFrameV1::decode(&frame).expect("decode"), click(1));
    }

    #[test]
    fn queue_is_bounded_and_sequence_fenced() {
        let mut queue = SharedMemoryQueueV1::new(verifier(), 1).expect("queue");
        queue.push(click(1)).expect("first");
        assert_eq!(queue.push(click(3)), Err(ActionErrorV1::SequenceMismatch));
        assert_eq!(queue.push(click(2)), Err(ActionErrorV1::QueueFull));
        assert_eq!(queue.pop().expect("pop").frame(), &click(1));
        queue.push(click(2)).expect("second");
    }

    #[test]
    fn verifier_rejects_wrong_capability_and_generation() {
        let mut action = click(1);
        action.capability_digest = digest(b"other");
        assert_eq!(verifier().verify(&action), Err(ActionErrorV1::CapabilityDenied));
        action = click(1);
        action.generation = 8;
        assert_eq!(verifier().verify(&action), Err(ActionErrorV1::GenerationMismatch));
    }

    #[test]
    fn malformed_padding_and_digest_are_rejected() {
        let mut frame = click(1).encode().expect("encode");
        frame[ACTION_PAYLOAD_OFFSET + 8] = 1;
        assert_eq!(ActionFrameV1::decode(&frame), Err(ActionErrorV1::NonCanonicalPadding));
        let mut frame = click(1).encode().expect("encode");
        frame[56] ^= 1;
        assert_eq!(ActionFrameV1::decode(&frame), Err(ActionErrorV1::DigestMismatch));
    }

    #[test]
    fn compiled_plan_is_proposal_only_and_sequence_bound() {
        let proposal = propose_compiled_use_v1(verifier(), vec![click(1), click(2)])
            .expect("proposal");
        assert_eq!(proposal.actions.len(), 2);
        assert!(!proposal.authority.grants_any());
        assert!(!proposal.proposal_digest.is_zero());
        assert_eq!(
            propose_compiled_use_v1(verifier(), vec![click(1), click(3)]),
            Err(ActionErrorV1::SequenceMismatch)
        );
        verify_compiled_use_proposal_v1(verifier(), &proposal).expect("verify proposal");
        let mut tampered = proposal;
        tampered.actions[0].arguments = ActionArgumentsV1::Click { x: 9, y: 9 };
        assert_eq!(
            verify_compiled_use_proposal_v1(verifier(), &tampered),
            Err(ActionErrorV1::DigestMismatch)
        );
    }

    #[test]
    fn default_sandbox_never_executes() {
        let mut sandbox = DenyByDefaultSandboxV1;
        let verified = verifier().verify_and_bind(&click(1)).expect("verified");
        assert_eq!(sandbox.submit(verified), Err(SandboxErrorV1::NotConfigured));
    }
}
