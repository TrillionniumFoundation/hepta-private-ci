//! Research-only guarded proposal transport over exact 256B action frames.
//!
//! HGP1 + 32-byte guarded proposal digest precedes a complete bounded batch.
//! The receiver must hold its OWN source-bound proposal and current readback.
//! This is a data consistency boundary, NOT a peer authentication protocol,
//! OS effect authorization or executable code transport.

use crate::{
    ActionVerifierV1, FrameDuplexV1, FrameWireErrorV1, UiGuardErrorV1,
    UiGuardedShadowProposalV1, UiReadbackV1, VerifiedActionV1,
    verify_ui_guarded_shadow_v1,
};
use std::error::Error as StdError;
use std::fmt;
use std::io::{Read, Write};

const GUARD_MAGIC: &[u8; 4] = b"HGP1";
const PREAMBLE_BYTES: usize = 36;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GuardedWireErrorV1 {
    Guard(UiGuardErrorV1),
    PreambleMismatch,
    FrameMismatch,
    Io(std::io::ErrorKind),
    Frame(FrameWireErrorV1),
}
impl fmt::Display for GuardedWireErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GuardedWireErrorV1 {}
impl From<UiGuardErrorV1> for GuardedWireErrorV1 {
    fn from(value: UiGuardErrorV1) -> Self {
        Self::Guard(value)
    }
}
impl From<FrameWireErrorV1> for GuardedWireErrorV1 {
    fn from(value: FrameWireErrorV1) -> Self {
        Self::Frame(value)
    }
}

/// A *single-use*, proposal-bound, data-only session. Before any byte is
/// written, validate all actions against the entire externally supplied UI
/// readback. The digest is a claim, not a cryptographically authenticated peer
/// credential. The stream is consumed and closed after this one proposal.
///
/// Transport I/O errors may occur after some bytes were sent; no external UI
/// effect is performed, and the receiver only returns a complete verified
/// batch. Do not use this method as an atomic OS-effects operation.
pub fn send_guarded_shadow_data_v1<T: Read + Write>(
    mut io: T,
    verifier: ActionVerifierV1,
    proposal: &UiGuardedShadowProposalV1,
    readback: &UiReadbackV1,
    now_ms: u64,
) -> Result<(), GuardedWireErrorV1> {
    verify_ui_guarded_shadow_v1(verifier, proposal, readback, now_ms)?;
    let actions = &proposal.proposed_actions.actions;
    let capacity = u64::try_from(actions.len())
        .map_err(|_| GuardedWireErrorV1::PreambleMismatch)?;
    let mut preamble = [0_u8; PREAMBLE_BYTES];
    preamble[..4].copy_from_slice(GUARD_MAGIC);
    preamble[4..].copy_from_slice(proposal.guarded_digest.as_array());
    io.write_all(&preamble)
        .map_err(|error| GuardedWireErrorV1::Io(error.kind()))?;
    let mut frames = FrameDuplexV1::new(io, verifier, capacity)?;
    for action in actions {
        frames.send(action)?;
    }
    Ok(())
}

/// Receiver verifies its OWN independently supplied proposal/readback before
/// reading the guard preamble. An unguarded, stale, replayed-across-source,
/// incomplete or altered frame stream is rejected without returning actions.
///
/// A matching digest is NOT proof of source-owner authenticity: both peers
/// may fabricate the same source claim. All future effects require separate
/// trusted current revocation and VerifiedUseToken checks at the OS boundary.
pub fn receive_guarded_shadow_data_v1<T: Read + Write>(
    mut io: T,
    verifier: ActionVerifierV1,
    proposal: &UiGuardedShadowProposalV1,
    readback: &UiReadbackV1,
    now_ms: u64,
) -> Result<Vec<VerifiedActionV1>, GuardedWireErrorV1> {
    verify_ui_guarded_shadow_v1(verifier, proposal, readback, now_ms)?;
    let mut preamble = [0_u8; PREAMBLE_BYTES];
    io.read_exact(&mut preamble)
        .map_err(|error| GuardedWireErrorV1::Io(error.kind()))?;
    if preamble[..4] != GUARD_MAGIC[..]
        || preamble[4..] != proposal.guarded_digest.as_array()[..]
    {
        return Err(GuardedWireErrorV1::PreambleMismatch);
    }
    let expected = &proposal.proposed_actions.actions;
    let capacity = u64::try_from(expected.len())
        .map_err(|_| GuardedWireErrorV1::PreambleMismatch)?;
    let mut frames = FrameDuplexV1::new(io, verifier, capacity)?;
    let mut complete = Vec::with_capacity(expected.len());
    for original in expected {
        let verified = frames.receive()?;
        if verified.frame() != original {
            return Err(GuardedWireErrorV1::FrameMismatch);
        }
        complete.push(verified);
    }
    Ok(complete)
}

#[cfg(all(test, unix))]
#[path = "guarded_wire_tests.rs"]
mod tests;
