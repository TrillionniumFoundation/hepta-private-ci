//! Replay fencing for envelopes that were authenticated by a trusted upstream
//! boundary.
//!
//! This crate does not verify a signature, authenticate a principal, evaluate
//! authorization policy, reserve quota or dispatch an effect. It cannot mint a
//! grant, widen scope, select, promote, merge or release. Successful receipts
//! always carry `AuthorityPosture::DENY_ALL`.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_REPLAY_KEYS: usize = 16_384;

/// Envelope fields supplied only after a trusted upstream authentication
/// boundary has verified the referenced authentication material.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreverifiedAuthEnvelope {
    pub message_id: StableId,
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    /// Opaque reference to authentication material already verified upstream.
    /// A nonzero value is structural data, not cryptographic proof.
    pub signature_digest: Digest32,
    pub sequence: u64,
    pub expires_at_ms: u64,
}

/// Trusted host context kept outside the untrusted envelope.
///
/// `issuer_id`, `key_epoch`, current time and revocation state must come from
/// the authenticated host boundary. Constructing this value does not itself
/// perform authentication.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedReplayContext {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub now_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerificationReceipt {
    pub message_id: StableId,
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub subject_id: StableId,
    pub sequence: u64,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    ZeroSequence,
    Revoked,
    Expired,
    ScopeMismatch,
    PayloadMismatch,
    Replay,
    CapacityExceeded,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ReplayKey {
    issuer_id: StableId,
    key_epoch: Generation,
    subject_id: StableId,
    scope_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayWindow {
    highest_sequence: BTreeMap<ReplayKey, u64>,
    maximum_replay_keys: usize,
}

impl ReplayWindow {
    #[must_use]
    pub fn new(maximum_replay_keys: usize) -> Self {
        Self {
            highest_sequence: BTreeMap::new(),
            maximum_replay_keys: maximum_replay_keys.min(MAX_REPLAY_KEYS),
        }
    }

    pub fn verify(
        &mut self,
        context: TrustedReplayContext,
        envelope: PreverifiedAuthEnvelope,
        expected_scope: Digest32,
        expected_payload: Digest32,
    ) -> Result<VerificationReceipt, Error> {
        for (name, digest) in [
            ("scope", envelope.scope_digest),
            ("payload", envelope.payload_digest),
            ("signature", envelope.signature_digest),
        ] {
            if digest.is_zero() {
                return Err(Error::EmptyDigest(name));
            }
        }
        if envelope.sequence == 0 {
            return Err(Error::ZeroSequence);
        }
        if context.revoked {
            return Err(Error::Revoked);
        }
        if context.now_ms >= envelope.expires_at_ms {
            return Err(Error::Expired);
        }
        if envelope.scope_digest != expected_scope {
            return Err(Error::ScopeMismatch);
        }
        if envelope.payload_digest != expected_payload {
            return Err(Error::PayloadMismatch);
        }

        let replay_key = ReplayKey {
            issuer_id: context.issuer_id.clone(),
            key_epoch: context.key_epoch,
            subject_id: envelope.subject_id.clone(),
            scope_digest: envelope.scope_digest,
        };
        if self
            .highest_sequence
            .get(&replay_key)
            .is_some_and(|sequence| *sequence >= envelope.sequence)
        {
            return Err(Error::Replay);
        }
        if !self.highest_sequence.contains_key(&replay_key)
            && self.highest_sequence.len() >= self.maximum_replay_keys
        {
            return Err(Error::CapacityExceeded);
        }
        self.highest_sequence
            .insert(replay_key, envelope.sequence);

        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.authbus.preverified-replay.v1\0");
        push_id(&mut bytes, &context.issuer_id);
        bytes.extend_from_slice(&context.key_epoch.get().to_be_bytes());
        push_id(&mut bytes, &envelope.message_id);
        push_id(&mut bytes, &envelope.subject_id);
        bytes.extend_from_slice(envelope.scope_digest.as_array());
        bytes.extend_from_slice(envelope.payload_digest.as_array());
        bytes.extend_from_slice(envelope.signature_digest.as_array());
        bytes.extend_from_slice(&envelope.sequence.to_be_bytes());
        bytes.extend_from_slice(&envelope.expires_at_ms.to_be_bytes());

        Ok(VerificationReceipt {
            message_id: envelope.message_id,
            issuer_id: context.issuer_id,
            key_epoch: context.key_epoch,
            subject_id: envelope.subject_id,
            sequence: envelope.sequence,
            envelope_digest: Digest32::of_bytes(&bytes),
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
