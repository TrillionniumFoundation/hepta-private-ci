//! Proposal-only compiled computer-use transport.
//!
//! This crate is intentionally a fixed-ABI *data plane* scaffold.  It can
//! validate and queue five bounded UI actions without a model-to-tool RPC on
//! the hot path, but it never accepts machine code, writes executable memory,
//! grants capabilities or invokes an OS/browser API.  A separately owned,
//! reviewed sandbox may implement [`SandboxActionPortV1`] later.

#![forbid(unsafe_code)]

mod action;
mod guarded_wire;
mod native_compute;
mod native_duplex;
mod ui_guard;

pub use guarded_wire::{
    GuardedWireErrorV1, receive_guarded_shadow_data_v1, send_guarded_shadow_data_v1,
};
pub use native_compute::{
    NATIVE_COMPUTE_FRAME_BYTES_V1, NATIVE_COMPUTE_MAX_LANES_V1,
    NATIVE_COMPUTE_RESULT_BYTES_V1, NativeComputeErrorV1, NativeComputeFrameV1,
    NativeComputeObservationV1, NativeComputeVerifierV1,
    approved_q24_dot_kernel_digest_v1, decode_shadow_native_result_v1,
    run_shadow_native_compute_v1,
};
pub use native_duplex::{FrameDuplexV1, FrameWireErrorV1};

pub use ui_guard::{
    UiGuardErrorV1, UiGuardedPlanV1, UiGuardedShadowProposalV1, UiReadbackV1,
    propose_ui_guarded_shadow_v1, verify_ui_guarded_shadow_v1,
};

pub use action::{
    ACTION_ABI_VERSION_V1, ACTION_FRAME_BYTES_V1, ActionArgumentsV1, ActionErrorV1, ActionFrameV1,
    ActionOpcodeV1, CapabilityGrantV1, CapabilityV1,
};

use std::collections::VecDeque;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

const MAX_QUEUE_CAPACITY: usize = 1024;
const MAX_PROPOSAL_ACTIONS: usize = 64;

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
#[derive(Debug, Eq, PartialEq)]
pub struct VerifiedActionV1(ActionFrameV1);

impl VerifiedActionV1 {
    #[must_use]
    pub fn frame(&self) -> &ActionFrameV1 {
        &self.0
    }
}

impl ActionVerifierV1 {
    /// Validate without materializing an owned clone on a data-plane hot path.
    pub fn verify(&self, action: &ActionFrameV1) -> Result<(), ActionErrorV1> {
        if self.generation == 0 || !self.grant.is_well_formed() {
            return Err(ActionErrorV1::InvalidCapabilityGrant);
        }
        if action.generation != self.generation {
            return Err(ActionErrorV1::GenerationMismatch);
        }
        if action.capability_digest != self.grant.digest
            || !self
                .grant
                .allows(action.arguments.opcode().required_capability())
        {
            return Err(ActionErrorV1::CapabilityDenied);
        }
        action.encode().map(|_| ())
    }

    pub fn verify_and_bind(
        &self,
        action: &ActionFrameV1,
    ) -> Result<VerifiedActionV1, ActionErrorV1> {
        self.verify(action)?;
        Ok(VerifiedActionV1(action.clone()))
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
        if capacity == 0 || capacity > MAX_QUEUE_CAPACITY {
            return Err(ActionErrorV1::MissingBinding);
        }
        if verifier.generation == 0 || !verifier.grant.is_well_formed() {
            return Err(ActionErrorV1::InvalidCapabilityGrant);
        }
        Ok(Self {
            verifier,
            capacity,
            next_sequence: 1,
            frames: VecDeque::with_capacity(capacity),
        })
    }

    pub fn push(&mut self, action: ActionFrameV1) -> Result<(), ActionErrorV1> {
        self.push_batch(std::slice::from_ref(&action))
    }

    /// Prevalidate the entire consecutive, bounded batch before the first
    /// queue mutation. Invalid grants, stale generations, sequence gaps,
    /// capacity pressure and sequence overflow never cause partial enqueue.
    ///
    /// This is local transport only, NOT compilation, a syscall, or permission
    /// to perform an external action. Production effect execution still needs
    /// a separately authorized sandbox with per-effect revocation fences.
    pub fn push_batch(&mut self, actions: &[ActionFrameV1]) -> Result<(), ActionErrorV1> {
        if actions.is_empty() || actions.len() > MAX_PROPOSAL_ACTIONS {
            return Err(ActionErrorV1::ProposalLimit);
        }
        let mut encoded = Vec::with_capacity(actions.len());
        for (offset, action) in actions.iter().enumerate() {
            self.verifier.verify(action)?;
            let sequence = u64::try_from(offset)
                .ok()
                .and_then(|offset| self.next_sequence.checked_add(offset))
                .ok_or(ActionErrorV1::SequenceMismatch)?;
            if action.sequence != sequence {
                return Err(ActionErrorV1::SequenceMismatch);
            }
            encoded.push(action.encode()?);
        }
        let last_exclusive = self
            .next_sequence
            .checked_add(u64::try_from(actions.len()).map_err(|_| ActionErrorV1::SequenceMismatch)?)
            .ok_or(ActionErrorV1::SequenceMismatch)?;
        if self
            .frames
            .len()
            .checked_add(actions.len())
            .is_none_or(|length| length > self.capacity)
        {
            return Err(ActionErrorV1::QueueFull);
        }
        self.frames.extend(encoded);
        self.next_sequence = last_exclusive;
        Ok(())
    }

    /// Revalidate the front frame before consuming it. A malformed or stale
    /// frame must not silently advance the queue: retaining the head lets the
    /// separate owner quarantine or reconcile the exact offending bytes.
    ///
    /// This check is not a substitute for a fresh authority/revocation check
    /// at the independent sandbox immediately before each external effect.
    pub fn pop(&mut self) -> Result<VerifiedActionV1, ActionErrorV1> {
        let frame = self.frames.front().ok_or(ActionErrorV1::QueueEmpty)?;
        let action = ActionFrameV1::decode(frame)?;
        let verified = self.verifier.verify_and_bind(&action)?;
        let _consumed_frame = self.frames.pop_front().ok_or(ActionErrorV1::QueueEmpty)?;
        Ok(verified)
    }

    /// Pop for a separately authorized owner only after its latest verified
    /// generation, grant digest and capability mask are supplied. This avoids
    /// treating the verifier captured at queue construction as current.
    ///
    /// This method still does not grant OS effects: a sandbox must fetch and
    /// independently check fresh revocation/final-use state at effect time.
    /// Any mismatch retains the entire original queue for owner reconciliation.
    pub fn pop_with_current_verifier(
        &mut self,
        current: ActionVerifierV1,
    ) -> Result<VerifiedActionV1, ActionErrorV1> {
        if current.generation == 0 || !current.grant.is_well_formed() {
            return Err(ActionErrorV1::InvalidCapabilityGrant);
        }
        if current.generation != self.verifier.generation {
            return Err(ActionErrorV1::GenerationMismatch);
        }
        if current.grant.digest != self.verifier.grant.digest {
            return Err(ActionErrorV1::CapabilityDenied);
        }
        let frame = self.frames.front().ok_or(ActionErrorV1::QueueEmpty)?;
        let action = ActionFrameV1::decode(frame)?;
        self.verifier.verify(&action)?;
        let verified = current.verify_and_bind(&action)?;
        let _consumed_frame = self.frames.pop_front().ok_or(ActionErrorV1::QueueEmpty)?;
        Ok(verified)
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
#[path = "tests.rs"]
mod tests;
