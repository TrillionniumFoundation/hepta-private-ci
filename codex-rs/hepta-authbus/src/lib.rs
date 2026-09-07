//! Authenticated, replay-fenced message verification.
//!
//! This crate verifies pre-existing envelopes. It cannot mint grants, widen
//! scope, dispatch effects, select, promote, merge or release.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_SUBJECTS: usize = 16_384;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthEnvelope {
    pub message_id: StableId,
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub payload_digest: Digest32,
    pub signature_digest: Digest32,
    pub sequence: u64,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerificationReceipt {
    pub message_id: StableId,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayWindow {
    highest_sequence: BTreeMap<StableId, u64>,
    maximum_subjects: usize,
}

impl ReplayWindow {
    #[must_use]
    pub fn new(maximum_subjects: usize) -> Self {
        Self {
            highest_sequence: BTreeMap::new(),
            maximum_subjects: maximum_subjects.min(MAX_SUBJECTS),
        }
    }

    pub fn verify(
        &mut self,
        now_ms: u64,
        envelope: AuthEnvelope,
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
        if envelope.revoked {
            return Err(Error::Revoked);
        }
        if now_ms >= envelope.expires_at_ms {
            return Err(Error::Expired);
        }
        if envelope.scope_digest != expected_scope {
            return Err(Error::ScopeMismatch);
        }
        if envelope.payload_digest != expected_payload {
            return Err(Error::PayloadMismatch);
        }
        if self
            .highest_sequence
            .get(&envelope.subject_id)
            .is_some_and(|sequence| *sequence >= envelope.sequence)
        {
            return Err(Error::Replay);
        }
        if !self.highest_sequence.contains_key(&envelope.subject_id)
            && self.highest_sequence.len() >= self.maximum_subjects
        {
            return Err(Error::CapacityExceeded);
        }
        self.highest_sequence
            .insert(envelope.subject_id.clone(), envelope.sequence);

        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.authbus.verification.v1");
        push_id(&mut bytes, &envelope.message_id);
        push_id(&mut bytes, &envelope.subject_id);
        bytes.extend_from_slice(envelope.scope_digest.as_array());
        bytes.extend_from_slice(envelope.payload_digest.as_array());
        bytes.extend_from_slice(envelope.signature_digest.as_array());
        bytes.extend_from_slice(&envelope.sequence.to_be_bytes());
        bytes.extend_from_slice(&envelope.expires_at_ms.to_be_bytes());

        Ok(VerificationReceipt {
            message_id: envelope.message_id,
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
