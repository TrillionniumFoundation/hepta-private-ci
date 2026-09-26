#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def p(rel: str) -> Path:
    return ROOT / rel


def read(rel: str) -> str:
    return p(rel).read_text(encoding="utf-8")


def write(rel: str, value: str) -> None:
    target = p(rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def insert_struct_field_literals(value: str, struct_name: str, before_field: str, field_line: str) -> str:
    marker = f"{struct_name} {{"
    cursor = 0
    changed = 0
    while True:
        start = value.find(marker, cursor)
        if start < 0:
            break
        brace = value.find("{", start)
        depth = 0
        end = None
        for index in range(brace, len(value)):
            char = value[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            raise RuntimeError(f"unterminated {struct_name} literal")
        block = value[brace:end]
        field_name = field_line.split(":", 1)[0]
        if field_name not in block:
            match = re.search(rf"(?m)^(\s*){re.escape(before_field)}", block)
            if match is None:
                raise RuntimeError(f"{struct_name} literal has no {before_field}")
            insertion = f"{match.group(1)}{field_line}\n"
            absolute = brace + match.start()
            value = value[:absolute] + insertion + value[absolute:]
            end += len(insertion)
            changed += 1
        cursor = end + 1
    if changed == 0:
        raise RuntimeError(f"no {struct_name} literals updated")
    return value


# Feature-gate V1 and the new cross-host wire contract.
cargo_rel = "codex-rs/hepta-memory-federation/Cargo.toml"
cargo = read(cargo_rel)
if "[features]" in cargo:
    raise RuntimeError("memory-federation Cargo.toml already has features")
cargo = cargo.replace(
    "[dependencies]\n",
    """[features]
default = []
legacy-v1 = []
cross-host-wire-v1 = ["dep:ed25519-dalek", "dep:rand"]

[dependencies]
""",
    1,
)
cargo = cargo.replace(
    "codex-hepta-types = { workspace = true }\n",
    """codex-hepta-types = { workspace = true }
ed25519-dalek = { workspace = true, optional = true }
rand = { workspace = true, optional = true }
""",
    1,
)
write(cargo_rel, cargo)

lib_rel = "codex-rs/hepta-memory-federation/src/lib.rs"
lib = read(lib_rel)
legacy_start = lib.index("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct FederatedReadRequest")
legacy_end = lib.index("#[cfg(test)]\n#[path = \"lib_tests.rs\"]")
legacy_block = lib[legacy_start:legacy_end].rstrip() + "\n"
legacy_source = """//! Compatibility-only V1 observation surface.
//!
//! This module is excluded from the default feature set. New product callers
//! must use the generation-bound V2 checked engine.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

""" + legacy_block
write("codex-rs/hepta-memory-federation/src/legacy_v1.rs", legacy_source)
for line in [
    "use std::error::Error as StdError;\n",
    "use std::fmt;\n",
    "use codex_hepta_types::AuthorityPosture;\n",
    "use codex_hepta_types::Digest32;\n",
    "use codex_hepta_types::StableId;\n",
]:
    lib = lib.replace(line, "", 1)
lib = lib[:legacy_start] + """#[cfg(feature = "legacy-v1")]
mod legacy_v1;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::Error;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::FederatedReadLease;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::FederatedReadReceipt;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::FederatedReadRequest;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::FederatedStatus;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::RemoteObservation;
#[cfg(feature = "legacy-v1")]
pub use legacy_v1::observe;

#[cfg(feature = "cross-host-wire-v1")]
mod wire;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::AuthenticatedFrontierV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationCancellationAckWireV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationCancellationWireV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireCredentialV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireEnvelopeV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireError;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireMessageKindV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireSignerV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::FederationWireVerifierV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::VerifiedFederationWireMessageV1;
#[cfg(feature = "cross-host-wire-v1")]
pub use wire::WIRE_SCHEMA_VERSION_V1;

""" + lib[legacy_end:]
lib = lib.replace(
    '#[cfg(test)]\n#[path = "lib_tests.rs"]\nmod tests;',
    '#[cfg(all(test, feature = "legacy-v1"))]\n#[path = "lib_tests.rs"]\nmod tests;',
    1,
)
lib = lib.replace(
    "mod v2;\n",
    'mod v2;\n\n#[cfg(all(test, feature = "cross-host-wire-v1"))]\n#[path = "wire_tests.rs"]\nmod wire_tests;\n',
    1,
)
write(lib_rel, lib)

wire_source = r'''//! Versioned authenticated cross-host wire contract.
//!
//! This module supplies canonical application-layer signing, peer credential
//! binding, replay rejection, monotonic authenticated frontiers and
//! cancellation acknowledgements. It deliberately does not open sockets,
//! enroll peers, manufacture trust roots or activate a cross-host product path.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;
use rand::TryRngCore;
use rand::rngs::OsRng;

pub const WIRE_SCHEMA_VERSION_V1: u32 = 1;
pub const MAX_WIRE_LIFETIME_MS_V1: u64 = 5 * 60 * 1_000;
pub const MAX_REPLAY_ENTRIES_V1: usize = 4_096;

const WIRE_DOMAIN: &[u8] = b"hepta.memory-federation.cross-host-wire.v1";
const FRONTIER_DOMAIN: &[u8] = b"hepta.memory-federation.authenticated-frontier.v1";
const CANCELLATION_DOMAIN: &[u8] = b"hepta.memory-federation.cancel-wire.v1";
const CANCELLATION_ACK_DOMAIN: &[u8] = b"hepta.memory-federation.cancel-ack-wire.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationWireMessageKindV1 {
    Query,
    Response,
    Cancellation,
    CancellationAck,
}

impl FederationWireMessageKindV1 {
    const fn code(self) -> u8 {
        match self {
            Self::Query => 0,
            Self::Response => 1,
            Self::Cancellation => 2,
            Self::CancellationAck => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationWireCredentialV1 {
    pub peer_id: StableId,
    pub credential_id: StableId,
    pub generation: u64,
    pub valid_from_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub verifying_key: [u8; 32],
    pub revoked: bool,
}

impl FederationWireCredentialV1 {
    pub fn validate(&self) -> Result<(), FederationWireError> {
        if self.generation == 0 {
            return Err(FederationWireError::InvalidCredential("zero generation"));
        }
        if self.valid_from_unix_ms >= self.valid_until_unix_ms {
            return Err(FederationWireError::InvalidCredential("invalid validity window"));
        }
        let key = VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| FederationWireError::InvalidCredential("malformed public key"))?;
        if key.is_weak() {
            return Err(FederationWireError::InvalidCredential("weak public key"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedFrontierV1 {
    pub owner_peer_id: StableId,
    pub owner_epoch: u64,
    pub sequence: u64,
    pub cut_digest: Digest32,
    pub predecessor_digest: Option<Digest32>,
    pub observed_unix_ms: u64,
}

impl AuthenticatedFrontierV1 {
    pub fn validate(&self) -> Result<(), FederationWireError> {
        if self.owner_epoch == 0 || self.sequence == 0 || self.observed_unix_ms == 0 {
            return Err(FederationWireError::InvalidFrontier);
        }
        if self.cut_digest.is_zero()
            || self.predecessor_digest.is_some_and(|digest| digest.is_zero())
        {
            return Err(FederationWireError::InvalidFrontier);
        }
        Ok(())
    }

    #[must_use]
    pub fn binding_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FRONTIER_DOMAIN);
        push_id(&mut bytes, &self.owner_peer_id);
        push_u64(&mut bytes, self.owner_epoch);
        push_u64(&mut bytes, self.sequence);
        push_digest(&mut bytes, self.cut_digest);
        push_optional_digest(&mut bytes, self.predecessor_digest);
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationWireEnvelopeV1 {
    pub schema_version: u32,
    pub kind: FederationWireMessageKindV1,
    pub sender_peer_id: StableId,
    pub recipient_peer_id: StableId,
    pub credential_id: StableId,
    pub credential_generation: u64,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub nonce: [u8; 32],
    pub body_digest: Digest32,
    pub frontier: Option<AuthenticatedFrontierV1>,
    pub signature: [u8; 64],
}

impl FederationWireEnvelopeV1 {
    fn validate_shape(&self) -> Result<(), FederationWireError> {
        if self.schema_version != WIRE_SCHEMA_VERSION_V1 {
            return Err(FederationWireError::UnsupportedSchema);
        }
        if self.credential_generation == 0
            || self.issued_unix_ms >= self.expires_unix_ms
            || self.expires_unix_ms.saturating_sub(self.issued_unix_ms) > MAX_WIRE_LIFETIME_MS_V1
            || self.body_digest.is_zero()
            || self.nonce == [0; 32]
        {
            return Err(FederationWireError::InvalidEnvelope);
        }
        if let Some(frontier) = &self.frontier {
            frontier.validate()?;
        }
        Ok(())
    }

    fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(WIRE_DOMAIN);
        push_u64(&mut bytes, u64::from(self.schema_version));
        bytes.push(self.kind.code());
        push_id(&mut bytes, &self.sender_peer_id);
        push_id(&mut bytes, &self.recipient_peer_id);
        push_id(&mut bytes, &self.credential_id);
        push_u64(&mut bytes, self.credential_generation);
        push_u64(&mut bytes, self.issued_unix_ms);
        push_u64(&mut bytes, self.expires_unix_ms);
        bytes.extend_from_slice(&self.nonce);
        push_digest(&mut bytes, self.body_digest);
        match &self.frontier {
            Some(frontier) => {
                bytes.push(1);
                push_digest(&mut bytes, frontier.binding_digest());
            }
            None => bytes.push(0),
        }
        bytes
    }

    #[must_use]
    pub fn envelope_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.signing_bytes())
    }
}

#[derive(Clone)]
pub struct FederationWireSignerV1 {
    peer_id: StableId,
    credential_id: StableId,
    generation: u64,
    valid_from_unix_ms: u64,
    valid_until_unix_ms: u64,
    signing_key: SigningKey,
}

impl FederationWireSignerV1 {
    pub fn new(
        peer_id: StableId,
        credential_id: StableId,
        generation: u64,
        valid_from_unix_ms: u64,
        valid_until_unix_ms: u64,
        signing_key: SigningKey,
    ) -> Result<Self, FederationWireError> {
        let credential = FederationWireCredentialV1 {
            peer_id: peer_id.clone(),
            credential_id: credential_id.clone(),
            generation,
            valid_from_unix_ms,
            valid_until_unix_ms,
            verifying_key: signing_key.verifying_key().to_bytes(),
            revoked: false,
        };
        credential.validate()?;
        Ok(Self {
            peer_id,
            credential_id,
            generation,
            valid_from_unix_ms,
            valid_until_unix_ms,
            signing_key,
        })
    }

    #[must_use]
    pub fn credential(&self) -> FederationWireCredentialV1 {
        FederationWireCredentialV1 {
            peer_id: self.peer_id.clone(),
            credential_id: self.credential_id.clone(),
            generation: self.generation,
            valid_from_unix_ms: self.valid_from_unix_ms,
            valid_until_unix_ms: self.valid_until_unix_ms,
            verifying_key: self.signing_key.verifying_key().to_bytes(),
            revoked: false,
        }
    }

    pub fn sign(
        &self,
        kind: FederationWireMessageKindV1,
        recipient_peer_id: StableId,
        body_digest: Digest32,
        frontier: Option<AuthenticatedFrontierV1>,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
    ) -> Result<FederationWireEnvelopeV1, FederationWireError> {
        let mut nonce = [0_u8; 32];
        OsRng
            .try_fill_bytes(&mut nonce)
            .map_err(|_| FederationWireError::RandomnessUnavailable)?;
        self.sign_with_nonce(
            kind,
            recipient_peer_id,
            body_digest,
            frontier,
            issued_unix_ms,
            expires_unix_ms,
            nonce,
        )
    }

    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn sign_with_nonce(
        &self,
        kind: FederationWireMessageKindV1,
        recipient_peer_id: StableId,
        body_digest: Digest32,
        frontier: Option<AuthenticatedFrontierV1>,
        issued_unix_ms: u64,
        expires_unix_ms: u64,
        nonce: [u8; 32],
    ) -> Result<FederationWireEnvelopeV1, FederationWireError> {
        if issued_unix_ms < self.valid_from_unix_ms || expires_unix_ms > self.valid_until_unix_ms {
            return Err(FederationWireError::CredentialWindow);
        }
        let mut envelope = FederationWireEnvelopeV1 {
            schema_version: WIRE_SCHEMA_VERSION_V1,
            kind,
            sender_peer_id: self.peer_id.clone(),
            recipient_peer_id,
            credential_id: self.credential_id.clone(),
            credential_generation: self.generation,
            issued_unix_ms,
            expires_unix_ms,
            nonce,
            body_digest,
            frontier,
            signature: [0; 64],
        };
        envelope.validate_shape()?;
        envelope.signature = self.signing_key.sign(&envelope.signing_bytes()).to_bytes();
        Ok(envelope)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedFederationWireMessageV1 {
    pub kind: FederationWireMessageKindV1,
    pub sender_peer_id: StableId,
    pub recipient_peer_id: StableId,
    pub body_digest: Digest32,
    pub envelope_digest: Digest32,
    pub frontier: Option<AuthenticatedFrontierV1>,
}

pub struct FederationWireVerifierV1 {
    expected_sender_peer_id: StableId,
    local_peer_id: StableId,
    credential: FederationWireCredentialV1,
    replay: BTreeMap<[u8; 32], u64>,
    last_frontier: Option<(u64, u64, Digest32)>,
}

impl FederationWireVerifierV1 {
    pub fn new(
        expected_sender_peer_id: StableId,
        local_peer_id: StableId,
        credential: FederationWireCredentialV1,
    ) -> Result<Self, FederationWireError> {
        credential.validate()?;
        if credential.peer_id != expected_sender_peer_id {
            return Err(FederationWireError::PeerIdentityMismatch);
        }
        Ok(Self {
            expected_sender_peer_id,
            local_peer_id,
            credential,
            replay: BTreeMap::new(),
            last_frontier: None,
        })
    }

    pub fn verify(
        &mut self,
        envelope: &FederationWireEnvelopeV1,
        expected_kind: FederationWireMessageKindV1,
        expected_body_digest: Digest32,
        now_unix_ms: u64,
    ) -> Result<VerifiedFederationWireMessageV1, FederationWireError> {
        envelope.validate_shape()?;
        self.credential.validate()?;
        if self.credential.revoked {
            return Err(FederationWireError::CredentialRevoked);
        }
        if envelope.kind != expected_kind
            || envelope.sender_peer_id != self.expected_sender_peer_id
            || envelope.recipient_peer_id != self.local_peer_id
            || envelope.credential_id != self.credential.credential_id
            || envelope.credential_generation != self.credential.generation
        {
            return Err(FederationWireError::PeerIdentityMismatch);
        }
        if now_unix_ms < self.credential.valid_from_unix_ms
            || now_unix_ms >= self.credential.valid_until_unix_ms
            || envelope.issued_unix_ms < self.credential.valid_from_unix_ms
            || envelope.expires_unix_ms > self.credential.valid_until_unix_ms
            || now_unix_ms < envelope.issued_unix_ms
            || now_unix_ms >= envelope.expires_unix_ms
        {
            return Err(FederationWireError::CredentialWindow);
        }
        if expected_body_digest.is_zero() || envelope.body_digest != expected_body_digest {
            return Err(FederationWireError::BodyDigestMismatch);
        }
        let verifying_key = VerifyingKey::from_bytes(&self.credential.verifying_key)
            .map_err(|_| FederationWireError::InvalidCredential("malformed public key"))?;
        verifying_key
            .verify_strict(
                &envelope.signing_bytes(),
                &Signature::from_bytes(&envelope.signature),
            )
            .map_err(|_| FederationWireError::InvalidSignature)?;

        self.replay.retain(|_, expires| *expires > now_unix_ms);
        if self.replay.contains_key(&envelope.nonce) {
            return Err(FederationWireError::Replay);
        }
        if self.replay.len() >= MAX_REPLAY_ENTRIES_V1 {
            return Err(FederationWireError::ReplayCacheFull);
        }

        if let Some(frontier) = &envelope.frontier {
            if frontier.owner_peer_id != envelope.sender_peer_id
                || frontier.owner_epoch != envelope.credential_generation
                || frontier.observed_unix_ms > envelope.issued_unix_ms
            {
                return Err(FederationWireError::InvalidFrontier);
            }
            if let Some((epoch, sequence, digest)) = self.last_frontier {
                if frontier.owner_epoch < epoch
                    || (frontier.owner_epoch == epoch && frontier.sequence <= sequence)
                    || (frontier.owner_epoch == epoch
                        && frontier.predecessor_digest != Some(digest))
                {
                    return Err(FederationWireError::FrontierRollback);
                }
            } else if frontier.predecessor_digest.is_some() {
                return Err(FederationWireError::FrontierRollback);
            }
        }

        self.replay.insert(envelope.nonce, envelope.expires_unix_ms);
        if let Some(frontier) = &envelope.frontier {
            self.last_frontier = Some((
                frontier.owner_epoch,
                frontier.sequence,
                frontier.binding_digest(),
            ));
        }
        Ok(VerifiedFederationWireMessageV1 {
            kind: envelope.kind,
            sender_peer_id: envelope.sender_peer_id.clone(),
            recipient_peer_id: envelope.recipient_peer_id.clone(),
            body_digest: envelope.body_digest,
            envelope_digest: envelope.envelope_digest(),
            frontier: envelope.frontier.clone(),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancellationWireV1 {
    pub query_binding_digest: Digest32,
    pub cancellation_digest: Digest32,
    pub requested_unix_ms: u64,
}

impl FederationCancellationWireV1 {
    pub fn new(
        query_binding_digest: Digest32,
        requested_unix_ms: u64,
    ) -> Result<Self, FederationWireError> {
        if query_binding_digest.is_zero() || requested_unix_ms == 0 {
            return Err(FederationWireError::InvalidCancellation);
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANCELLATION_DOMAIN);
        push_digest(&mut bytes, query_binding_digest);
        push_u64(&mut bytes, requested_unix_ms);
        Ok(Self {
            query_binding_digest,
            cancellation_digest: Digest32::of_bytes(&bytes),
            requested_unix_ms,
        })
    }

    #[must_use]
    pub fn body_digest(&self) -> Digest32 {
        self.cancellation_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationCancellationAckWireV1 {
    pub cancellation_digest: Digest32,
    pub observed_unix_ms: u64,
    pub transport_stopped: bool,
    pub ack_digest: Digest32,
}

impl FederationCancellationAckWireV1 {
    pub fn new(
        cancellation_digest: Digest32,
        observed_unix_ms: u64,
        transport_stopped: bool,
    ) -> Result<Self, FederationWireError> {
        if cancellation_digest.is_zero() || observed_unix_ms == 0 {
            return Err(FederationWireError::InvalidCancellation);
        }
        let mut bytes = Vec::new();
        bytes.extend_from_slice(CANCELLATION_ACK_DOMAIN);
        push_digest(&mut bytes, cancellation_digest);
        push_u64(&mut bytes, observed_unix_ms);
        bytes.push(u8::from(transport_stopped));
        Ok(Self {
            cancellation_digest,
            observed_unix_ms,
            transport_stopped,
            ack_digest: Digest32::of_bytes(&bytes),
        })
    }

    #[must_use]
    pub fn body_digest(&self) -> Digest32 {
        self.ack_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationWireError {
    UnsupportedSchema,
    InvalidCredential(&'static str),
    CredentialRevoked,
    CredentialWindow,
    PeerIdentityMismatch,
    InvalidEnvelope,
    BodyDigestMismatch,
    InvalidSignature,
    RandomnessUnavailable,
    Replay,
    ReplayCacheFull,
    InvalidFrontier,
    FrontierRollback,
    InvalidCancellation,
}

impl fmt::Display for FederationWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationWireError {}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_digest(bytes, value);
        }
        None => bytes.push(0),
    }
}
'''
write("codex-rs/hepta-memory-federation/src/wire.rs", wire_source)

wire_tests = r'''use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::AuthenticatedFrontierV1;
use crate::FederationCancellationAckWireV1;
use crate::FederationCancellationWireV1;
use crate::FederationWireError;
use crate::FederationWireMessageKindV1;
use crate::FederationWireSignerV1;
use crate::FederationWireVerifierV1;

fn id(value: &str) -> StableId {
    StableId::new(value.to_string()).expect("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn signer(seed: u8) -> FederationWireSignerV1 {
    FederationWireSignerV1::new(
        id("peer:owner"),
        id("credential:owner:7"),
        7,
        100,
        10_000,
        SigningKey::from_bytes(&[seed; 32]),
    )
    .expect("signer")
}

#[test]
fn signed_envelope_binds_identity_body_and_rejects_replay() {
    let signer = signer(11);
    let mut verifier = FederationWireVerifierV1::new(
        id("peer:owner"),
        id("peer:consumer"),
        signer.credential(),
    )
    .expect("verifier");
    let envelope = signer
        .sign_with_nonce(
            FederationWireMessageKindV1::Query,
            id("peer:consumer"),
            digest("query"),
            None,
            200,
            300,
            [3; 32],
        )
        .expect("envelope");
    verifier
        .verify(
            &envelope,
            FederationWireMessageKindV1::Query,
            digest("query"),
            250,
        )
        .expect("verified");
    assert_eq!(
        verifier.verify(
            &envelope,
            FederationWireMessageKindV1::Query,
            digest("query"),
            250,
        ),
        Err(FederationWireError::Replay)
    );
}

#[test]
fn identity_digest_and_revocation_fail_closed() {
    let signer = signer(12);
    let envelope = signer
        .sign_with_nonce(
            FederationWireMessageKindV1::Response,
            id("peer:consumer"),
            digest("response"),
            None,
            200,
            300,
            [4; 32],
        )
        .expect("envelope");
    let mut wrong_recipient = FederationWireVerifierV1::new(
        id("peer:owner"),
        id("peer:other"),
        signer.credential(),
    )
    .expect("verifier");
    assert_eq!(
        wrong_recipient.verify(
            &envelope,
            FederationWireMessageKindV1::Response,
            digest("response"),
            250,
        ),
        Err(FederationWireError::PeerIdentityMismatch)
    );

    let mut revoked = signer.credential();
    revoked.revoked = true;
    let mut verifier = FederationWireVerifierV1::new(
        id("peer:owner"),
        id("peer:consumer"),
        revoked,
    )
    .expect("verifier");
    assert_eq!(
        verifier.verify(
            &envelope,
            FederationWireMessageKindV1::Response,
            digest("response"),
            250,
        ),
        Err(FederationWireError::CredentialRevoked)
    );
}

#[test]
fn authenticated_frontier_is_monotonic_and_predecessor_bound() {
    let signer = signer(13);
    let mut verifier = FederationWireVerifierV1::new(
        id("peer:owner"),
        id("peer:consumer"),
        signer.credential(),
    )
    .expect("verifier");
    let first = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer:owner"),
        owner_epoch: 7,
        sequence: 1,
        cut_digest: digest("cut:1"),
        predecessor_digest: None,
        observed_unix_ms: 190,
    };
    let first_digest = first.binding_digest();
    let first_envelope = signer
        .sign_with_nonce(
            FederationWireMessageKindV1::Response,
            id("peer:consumer"),
            digest("response:1"),
            Some(first),
            200,
            300,
            [5; 32],
        )
        .expect("envelope");
    verifier
        .verify(
            &first_envelope,
            FederationWireMessageKindV1::Response,
            digest("response:1"),
            250,
        )
        .expect("first frontier");

    let rollback = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer:owner"),
        owner_epoch: 7,
        sequence: 2,
        cut_digest: digest("cut:2"),
        predecessor_digest: Some(digest("wrong")),
        observed_unix_ms: 260,
    };
    let rollback_envelope = signer
        .sign_with_nonce(
            FederationWireMessageKindV1::Response,
            id("peer:consumer"),
            digest("response:2"),
            Some(rollback),
            270,
            350,
            [6; 32],
        )
        .expect("envelope");
    assert_eq!(
        verifier.verify(
            &rollback_envelope,
            FederationWireMessageKindV1::Response,
            digest("response:2"),
            300,
        ),
        Err(FederationWireError::FrontierRollback)
    );

    let next = AuthenticatedFrontierV1 {
        owner_peer_id: id("peer:owner"),
        owner_epoch: 7,
        sequence: 2,
        cut_digest: digest("cut:2"),
        predecessor_digest: Some(first_digest),
        observed_unix_ms: 260,
    };
    let next_envelope = signer
        .sign_with_nonce(
            FederationWireMessageKindV1::Response,
            id("peer:consumer"),
            digest("response:2"),
            Some(next),
            270,
            350,
            [7; 32],
        )
        .expect("envelope");
    verifier
        .verify(
            &next_envelope,
            FederationWireMessageKindV1::Response,
            digest("response:2"),
            300,
        )
        .expect("next frontier");
}

#[test]
fn cancellation_ack_is_digest_bound_and_independently_signed() {
    let cancellation =
        FederationCancellationWireV1::new(digest("query-binding"), 200).expect("cancel");
    let ack = FederationCancellationAckWireV1::new(cancellation.body_digest(), 210, true)
        .expect("ack");
    assert!(ack.transport_stopped);

    let owner = signer(14);
    let consumer = FederationWireSignerV1::new(
        id("peer:consumer"),
        id("credential:consumer:9"),
        9,
        100,
        10_000,
        SigningKey::from_bytes(&[15; 32]),
    )
    .expect("consumer signer");
    let cancel_envelope = consumer
        .sign_with_nonce(
            FederationWireMessageKindV1::Cancellation,
            id("peer:owner"),
            cancellation.body_digest(),
            None,
            200,
            300,
            [8; 32],
        )
        .expect("cancel envelope");
    let mut owner_verifier = FederationWireVerifierV1::new(
        id("peer:consumer"),
        id("peer:owner"),
        consumer.credential(),
    )
    .expect("owner verifier");
    owner_verifier
        .verify(
            &cancel_envelope,
            FederationWireMessageKindV1::Cancellation,
            cancellation.body_digest(),
            205,
        )
        .expect("cancel verified");

    let ack_envelope = owner
        .sign_with_nonce(
            FederationWireMessageKindV1::CancellationAck,
            id("peer:consumer"),
            ack.body_digest(),
            None,
            210,
            310,
            [9; 32],
        )
        .expect("ack envelope");
    let mut consumer_verifier = FederationWireVerifierV1::new(
        id("peer:owner"),
        id("peer:consumer"),
        owner.credential(),
    )
    .expect("consumer verifier");
    consumer_verifier
        .verify(
            &ack_envelope,
            FederationWireMessageKindV1::CancellationAck,
            ack.body_digest(),
            220,
        )
        .expect("ack verified");
}
'''
write("codex-rs/hepta-memory-federation/src/wire_tests.rs", wire_tests)

# Canonical V2 binds source-side omissions into response and result coverage.
v2_rel = "codex-rs/hepta-memory-federation/src/v2.rs"
v2 = read(v2_rel)
v2 = v2.replace(
    "    pub items: Vec<FederatedEvidenceItemV2>,\n    pub completeness: FederatedCompletenessV2,\n",
    "    pub items: Vec<FederatedEvidenceItemV2>,\n    pub omitted_items: u32,\n    pub completeness: FederatedCompletenessV2,\n",
    1,
)
v2 = v2.replace(
    """        if matches!(self.completeness, FederatedCompletenessV2::Empty) && !self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete) && self.items.is_empty() {
            return Err(FederationV2Error::InvalidCompleteness);
        }
""",
    """        if matches!(self.completeness, FederatedCompletenessV2::Empty)
            && (!self.items.is_empty() || self.omitted_items != 0)
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if matches!(self.completeness, FederatedCompletenessV2::Complete)
            && (self.items.is_empty() || self.omitted_items != 0)
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
        if self.omitted_items != 0
            && !matches!(self.completeness, FederatedCompletenessV2::Partial)
        {
            return Err(FederationV2Error::InvalidCompleteness);
        }
""",
    1,
)
v2 = v2.replace(
    "        push_items(&mut bytes, &self.items);\n        bytes.push(completeness_code(self.completeness));\n",
    "        push_items(&mut bytes, &self.items);\n        push_u64(&mut bytes, u64::from(self.omitted_items));\n        bytes.push(completeness_code(self.completeness));\n",
    1,
)
v2 = v2.replace(
    """            let remote_item_count = response.items.len();
            let mut items = if stale_generation || revoked {
""",
    """            let remote_item_count = response.items.len();
            let remote_omitted_items =
                usize::try_from(response.omitted_items).unwrap_or(usize::MAX);
            let mut items = if stale_generation || revoked {
""",
    1,
)
v2 = v2.replace(
    """            let truncated_items = if stale_generation || revoked {
                0
            } else {
                remote_item_count.saturating_sub(items.len())
            };
""",
    """            let truncated_items = if stale_generation || revoked {
                0
            } else {
                remote_omitted_items
                    .saturating_add(remote_item_count.saturating_sub(items.len()))
            };
""",
    1,
)
write(v2_rel, v2)

v2_tests_rel = "codex-rs/hepta-memory-federation/src/v2_tests.rs"
v2_tests = insert_struct_field_literals(
    read(v2_tests_rel),
    "RemoteFederatedResponseV2",
    "completeness:",
    "omitted_items: 0,",
)
write(v2_tests_rel, v2_tests)

print("stage 1 applied")
