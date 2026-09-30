//! Explicitly feature-gated structural replay compatibility surface.
//!
//! This module never authenticates a signature, persists replay state, reserves
//! quota or grants effect authority. New production callers must use
//! `SignedMessage::authenticate` followed by the Evidence-owned durable replay
//! and outbox path.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::Error;
use crate::VerificationReceipt;
use crate::push_id;

const MAX_REPLAY_KEYS: usize = 16_384;

#[deprecated(
    since = "0.1.0",
    note = "structural compatibility only; use SignedMessage plus durable Evidence replay"
)]
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

#[deprecated(
    since = "0.1.0",
    note = "structural compatibility only; use a sealed durable issuer registration"
)]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TrustedReplayContext {
    pub issuer_id: StableId,
    pub key_epoch: Generation,
    pub now_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct ReplayKey {
    issuer_id: StableId,
    key_epoch: Generation,
    subject_id: StableId,
    scope_digest: Digest32,
}

#[deprecated(
    since = "0.1.0",
    note = "in-memory structural replay only; use HeptaEvidenceStore durable replay"
)]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplayWindow {
    highest_sequence: BTreeMap<ReplayKey, u64>,
    maximum_replay_keys: usize,
}

#[allow(deprecated)]
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
            crate::operations::record_replay_rejection();
            return Err(Error::Replay);
        }
        if !self.highest_sequence.contains_key(&replay_key)
            && self.highest_sequence.len() >= self.maximum_replay_keys
        {
            return Err(Error::CapacityExceeded);
        }
        self.highest_sequence.insert(replay_key, envelope.sequence);

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
