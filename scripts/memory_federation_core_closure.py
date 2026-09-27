#!/usr/bin/env python3
"""Apply the memory.federation canonical-contract closure.

This script is intentionally repository-local and deterministic.  The bootstrap
workflow applies it in a clean checkout, formats the result, commits source,
and only then generates self-reference-safe current-state metadata.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one replacement, found {text.count(old)}")
    return text.replace(old, new, 1)


def reset_from_main(paths: list[str]) -> None:
    run("git", "checkout", "origin/main", "--", *paths)


def patch_state_generator() -> None:
    path = "scripts/hepta-memory-federation-state.py"
    text = read(path)
    old = '    row.update(\n        {\n            "schema": "hepta.module-implementation-map.v3",'
    new = (
        '    mapped_operations = operations()\n'
        '    for operation in mapped_operations:\n'
        '        operation["sourceBlob"] = object_for(operation["sourcePath"], source["commit"])\n'
        '    row.update(\n'
        '        {\n'
        '            "schema": "hepta.module-implementation-map.v3",'
    )
    text = replace_once(text, old, new, "state generator source blobs")
    text = replace_once(text, '            "operations": operations(),', '            "operations": mapped_operations,', "state generator operation list")
    write(path, text)


def patch_cargo() -> None:
    path = "codex-rs/hepta-memory-federation/Cargo.toml"
    text = read(path)
    text = replace_once(
        text,
        "[lints]\nworkspace = true\n\n[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }",
        "[features]\ndefault = []\nlegacy-v1 = []\n\n[lints]\nworkspace = true\n\n[dependencies]\ncodex-hepta-types = { path = \"../hepta-types\" }\ned25519-dalek = { workspace = true }",
        "canonical Cargo features",
    )
    write(path, text)


def patch_lib_and_legacy() -> None:
    path = "codex-rs/hepta-memory-federation/src/lib.rs"
    text = read(path)
    legacy_start = text.index("#[derive(Clone, Debug, Eq, PartialEq)]\npub struct FederatedReadRequest")
    tests_start = text.index("#[cfg(test)]\n#[path = \"lib_tests.rs\"]", legacy_start)
    legacy_body = text[legacy_start:tests_start].rstrip()
    legacy_prelude = """//! Feature-gated compatibility surface for the original federation receipt.\n\nuse std::error::Error as StdError;\nuse std::fmt;\n\nuse codex_hepta_types::AuthorityPosture;\nuse codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n\n"""
    names = [
        "FederatedReadRequest",
        "FederatedReadLease",
        "RemoteObservation",
        "FederatedStatus",
        "FederatedReadReceipt",
        "Error",
    ]
    for name in names:
        legacy_body = legacy_body.replace(
            f"pub struct {name}",
            f"#[deprecated(note = \"use the generation-bound V2 federation contract\")]\npub struct {name}",
        ).replace(
            f"pub enum {name}",
            f"#[deprecated(note = \"use the generation-bound V2 federation contract\")]\npub enum {name}",
        )
    legacy_body = legacy_body.replace(
        "pub fn observe(",
        "#[deprecated(note = \"use execute_once_outcome or execute_once\")]\n#[allow(deprecated)]\npub fn observe(",
    )
    write("codex-rs/hepta-memory-federation/src/legacy.rs", legacy_prelude + legacy_body)

    head = text[:legacy_start]
    head = head.replace("use std::error::Error as StdError;\nuse std::fmt;\n\n", "")
    head = head.replace(
        "use codex_hepta_types::AuthorityPosture;\nuse codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;\n\n",
        "",
    )
    head = head.replace("mod v2;", "mod v2;\nmod wire;\n\n#[cfg(feature = \"legacy-v1\")]\nmod legacy;")
    head = head.replace(
        "pub use v2::FederatedFailureCoverageV2;",
        "pub use v2::FederatedFailureCoverageV2;\npub use v2::FederationAttemptDispositionV2;\npub use v2::FederationAttemptFailureV2;\npub use v2::FederationAttemptOutcomeV2;\npub use v2::FederationAttemptPhaseV2;",
    )
    head = head.replace(
        "pub use v2::execute_once;",
        "pub use v2::execute_once;\npub use v2::execute_once_outcome;",
    )
    head += """

pub use wire::FEDERATION_WIRE_PROTOCOL_V1;
pub use wire::FederationPeerCredentialV1;
pub use wire::FederationReplayWindowV1;
pub use wire::FederationWireError;
pub use wire::FederationWireRequestV1;
pub use wire::FederationWireResponseV1;
pub use wire::FederationWireVersionRangeV1;
pub use wire::MAX_FEDERATION_REPLAY_NONCES_V1;
pub use wire::negotiate_wire_protocol_v1;
pub use wire::sign_wire_request_v1;
pub use wire::sign_wire_response_v1;
pub use wire::verify_wire_request_v1;
pub use wire::verify_wire_response_v1;

#[cfg(feature = "legacy-v1")]
#[allow(deprecated)]
pub use legacy::{
    Error, FederatedReadLease, FederatedReadReceipt, FederatedReadRequest, FederatedStatus,
    RemoteObservation, observe,
};

#[cfg(all(test, feature = "legacy-v1"))]
#[allow(deprecated)]
#[path = "lib_tests.rs"]
mod tests;
"""
    write(path, head)

    tests = read("codex-rs/hepta-memory-federation/src/lib_tests.rs")
    if not tests.startswith("#![allow(deprecated)]"):
        tests = "#![allow(deprecated)]\n\n" + tests
    write("codex-rs/hepta-memory-federation/src/lib_tests.rs", tests)


def patch_v2_outcome() -> None:
    path = "codex-rs/hepta-memory-federation/src/v2.rs"
    text = read(path)
    marker = "pub async fn execute_once<T, A, C>(\n"
    if text.count(marker) != 1:
        raise SystemExit("V2 execute_once marker drift")
    outcome = r'''
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationAttemptPhaseV2 {
    Admission,
    PreflightAuthority,
    Transport,
    PostIoAuthority,
    Integrity,
    Finalization,
    Control,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FederationAttemptDispositionV2 {
    Complete,
    Partial,
    Empty,
    Indeterminate,
    Failed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationAttemptFailureV2 {
    pub phase: FederationAttemptPhaseV2,
    pub error: FederationV2Error,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationAttemptOutcomeV2 {
    pub disposition: FederationAttemptDispositionV2,
    pub result: Option<FederatedResultV2>,
    pub failure: Option<FederationAttemptFailureV2>,
}

impl FederationAttemptOutcomeV2 {
    #[must_use]
    pub fn from_result(result: FederatedResultV2) -> Self {
        let disposition = match result.completeness {
            FederatedCompletenessV2::Complete => FederationAttemptDispositionV2::Complete,
            FederatedCompletenessV2::Partial => FederationAttemptDispositionV2::Partial,
            FederatedCompletenessV2::Empty => FederationAttemptDispositionV2::Empty,
            FederatedCompletenessV2::Indeterminate => {
                FederationAttemptDispositionV2::Indeterminate
            }
        };
        Self {
            disposition,
            result: Some(result),
            failure: None,
        }
    }

    #[must_use]
    pub fn failed(error: FederationV2Error) -> Self {
        Self {
            disposition: FederationAttemptDispositionV2::Failed,
            result: None,
            failure: Some(FederationAttemptFailureV2 {
                phase: federation_failure_phase(&error),
                error,
            }),
        }
    }

    pub fn validate(&self) -> Result<(), FederationV2Error> {
        match (&self.result, &self.failure, self.disposition) {
            (Some(result), None, FederationAttemptDispositionV2::Complete)
                if result.completeness == FederatedCompletenessV2::Complete => result.validate(),
            (Some(result), None, FederationAttemptDispositionV2::Partial)
                if result.completeness == FederatedCompletenessV2::Partial => result.validate(),
            (Some(result), None, FederationAttemptDispositionV2::Empty)
                if result.completeness == FederatedCompletenessV2::Empty => result.validate(),
            (Some(result), None, FederationAttemptDispositionV2::Indeterminate)
                if result.completeness == FederatedCompletenessV2::Indeterminate => result.validate(),
            (None, Some(_), FederationAttemptDispositionV2::Failed) => Ok(()),
            _ => Err(FederationV2Error::InvalidAttemptOutcome),
        }
    }
}

/// Executes one checked attempt while projecting every expected runtime failure
/// into a typed outcome. Structural programmer errors still remain represented
/// by their original `FederationV2Error`, but product orchestrators no longer
/// need two unrelated success/failure channels.
pub async fn execute_once_outcome<T, A, C>(
    transport: &T,
    authority: &A,
    control: &C,
    now_unix_ms: u64,
    query: FederatedQueryV2,
    lease: &FederatedLeaseV2,
) -> FederationAttemptOutcomeV2
where
    T: FederationTransportV2 + ?Sized,
    A: FederationAuthorityV2 + ?Sized,
    C: FederationAttemptControlV2 + ?Sized,
{
    let outcome = match execute_once(transport, authority, control, now_unix_ms, query, lease).await {
        Ok(result) => FederationAttemptOutcomeV2::from_result(result),
        Err(error) => FederationAttemptOutcomeV2::failed(error),
    };
    debug_assert!(outcome.validate().is_ok());
    outcome
}

fn federation_failure_phase(error: &FederationV2Error) -> FederationAttemptPhaseV2 {
    match error {
        FederationV2Error::AttemptCancelled | FederationV2Error::DeadlineExpired => {
            FederationAttemptPhaseV2::Control
        }
        FederationV2Error::AuthorityObservationRegressed
        | FederationV2Error::AuthorityExpired
        | FederationV2Error::LeaseAuthorityHorizonExceeded
        | FederationV2Error::AuthorityNotCurrent(_)
        | FederationV2Error::AuthorityGranted
        | FederationV2Error::AuthorityRevalidationFailed => {
            FederationAttemptPhaseV2::PreflightAuthority
        }
        FederationV2Error::TransportRejected => FederationAttemptPhaseV2::Transport,
        FederationV2Error::MissingTerminalObservation
        | FederationV2Error::ResponseExpired
        | FederationV2Error::ResultLimitExceeded
        | FederationV2Error::DuplicateResultIdentity
        | FederationV2Error::InvalidCompleteness
        | FederationV2Error::InvalidCoverage
        | FederationV2Error::StaleEvidenceExposed
        | FederationV2Error::DigestMismatch(_)
        | FederationV2Error::IdentityMismatch(_)
        | FederationV2Error::EmptyDigest(_) => FederationAttemptPhaseV2::Integrity,
        FederationV2Error::InvalidAttemptOutcome => FederationAttemptPhaseV2::Finalization,
        FederationV2Error::ZeroValue(_)
        | FederationV2Error::InvalidMaximumResults
        | FederationV2Error::LeaseExpired
        | FederationV2Error::LeaseRevoked
        | FederationV2Error::LeaseEpochMismatch => FederationAttemptPhaseV2::Admission,
    }
}

'''
    text = text.replace(marker, outcome + marker, 1)
    text = replace_once(
        text,
        "    TransportRejected,\n}",
        "    TransportRejected,\n    InvalidAttemptOutcome,\n}",
        "V2 outcome error",
    )
    write(path, text)

    tests_path = "codex-rs/hepta-memory-federation/src/v2_tests.rs"
    tests = read(tests_path)
    insert = r'''

#[test]
fn unified_attempt_outcome_preserves_indeterminate_and_failure_phase() {
    let query = query();
    let timed_out = FixtureTransport {
        result: Ok(FederationTransportResultV2::NonTerminal(
            FederationTransportOutcomeV2::TimedOut,
        )),
    };
    let authority = current_authority();
    let control = FixtureControl::Pending;
    let outcome = block_on(execute_once_outcome(
        &timed_out,
        &authority,
        &control,
        10,
        query.clone(),
        &lease(&query),
    ));
    assert_eq!(
        outcome.disposition,
        FederationAttemptDispositionV2::Indeterminate
    );
    assert!(outcome.result.is_some());
    assert!(outcome.failure.is_none());
    outcome.validate().expect("valid indeterminate outcome");

    let revoked = FixtureAuthority {
        state: FederationAuthorityStateV2::Revoked,
        observed_unix_ms: 20,
        authority_expires_unix_ms: 90,
    };
    let failed = block_on(execute_once_outcome(
        &PanicTransport,
        &revoked,
        &control,
        10,
        query.clone(),
        &lease(&query),
    ));
    assert_eq!(failed.disposition, FederationAttemptDispositionV2::Failed);
    assert_eq!(
        failed.failure.as_ref().map(|failure| failure.phase),
        Some(FederationAttemptPhaseV2::PreflightAuthority)
    );
    assert!(failed.result.is_none());
    failed.validate().expect("valid failed outcome");
}
'''
    marker = "\nstruct ThreadWaker(thread::Thread);"
    tests = replace_once(tests, marker, insert + marker, "V2 unified outcome test")
    write(tests_path, tests)


def wire_source() -> str:
    return r'''//! Authenticated, versioned cross-host federation envelope contract.
//!
//! This module defines source-level protocol semantics only. It does not open a
//! socket, enroll a peer, own credentials, or claim physical two-host
//! qualification. A selected host supplies transport and durable replay state.

use std::collections::VecDeque;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use ed25519_dalek::VerifyingKey;

pub const FEDERATION_WIRE_PROTOCOL_V1: u16 = 1;
pub const MAX_FEDERATION_REPLAY_NONCES_V1: usize = 4096;
const REQUEST_DOMAIN: &[u8] = b"hepta.memory-federation.wire-request.v1";
const RESPONSE_DOMAIN: &[u8] = b"hepta.memory-federation.wire-response.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FederationWireVersionRangeV1 {
    pub minimum: u16,
    pub maximum: u16,
}

impl FederationWireVersionRangeV1 {
    pub fn validate(self) -> Result<(), FederationWireError> {
        if self.minimum == 0 || self.maximum < self.minimum {
            return Err(FederationWireError::InvalidVersionRange);
        }
        Ok(())
    }
}

pub fn negotiate_wire_protocol_v1(
    local: FederationWireVersionRangeV1,
    remote: FederationWireVersionRangeV1,
) -> Result<u16, FederationWireError> {
    local.validate()?;
    remote.validate()?;
    let selected = local.maximum.min(remote.maximum);
    if selected < local.minimum.max(remote.minimum) || selected != FEDERATION_WIRE_PROTOCOL_V1 {
        return Err(FederationWireError::NoCommonVersion);
    }
    Ok(selected)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationPeerCredentialV1 {
    pub peer_id: StableId,
    pub key_id: StableId,
    pub verifying_key: [u8; 32],
    pub owner_epoch: u64,
    pub effective_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub revoked: bool,
}

impl FederationPeerCredentialV1 {
    fn validate(&self, now_unix_ms: u64) -> Result<(), FederationWireError> {
        if self.revoked {
            return Err(FederationWireError::CredentialRevoked);
        }
        if self.owner_epoch == 0 {
            return Err(FederationWireError::ZeroValue("owner_epoch"));
        }
        if self.effective_unix_ms >= self.expires_unix_ms
            || now_unix_ms < self.effective_unix_ms
            || now_unix_ms >= self.expires_unix_ms
        {
            return Err(FederationWireError::CredentialExpired);
        }
        VerifyingKey::from_bytes(&self.verifying_key)
            .map_err(|_| FederationWireError::InvalidVerifyingKey)?;
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationWireRequestV1 {
    pub protocol_version: u16,
    pub request_id: StableId,
    pub sender_peer_id: StableId,
    pub receiver_peer_id: StableId,
    pub credential_key_id: StableId,
    pub query_binding_digest: Digest32,
    pub scope_digest: Digest32,
    pub purpose_digest: Digest32,
    pub source_cut_digest: Digest32,
    pub owner_epoch: u64,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub nonce_digest: Digest32,
    pub signature: [u8; 64],
}

impl FederationWireRequestV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(REQUEST_DOMAIN);
        push_u64(&mut bytes, u64::from(self.protocol_version));
        for value in [
            &self.request_id,
            &self.sender_peer_id,
            &self.receiver_peer_id,
            &self.credential_key_id,
        ] {
            push_id(&mut bytes, value);
        }
        for digest in [
            self.query_binding_digest,
            self.scope_digest,
            self.purpose_digest,
            self.source_cut_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.owner_epoch);
        push_u64(&mut bytes, self.issued_unix_ms);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_digest(&mut bytes, self.nonce_digest);
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationWireResponseV1 {
    pub protocol_version: u16,
    pub response_id: StableId,
    pub request_id: StableId,
    pub responder_peer_id: StableId,
    pub receiver_peer_id: StableId,
    pub credential_key_id: StableId,
    pub query_binding_digest: Digest32,
    pub response_digest: Digest32,
    pub source_cut_digest: Digest32,
    pub owner_epoch: u64,
    pub issued_unix_ms: u64,
    pub expires_unix_ms: u64,
    pub nonce_digest: Digest32,
    pub signature: [u8; 64],
}

impl FederationWireResponseV1 {
    #[must_use]
    pub fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(RESPONSE_DOMAIN);
        push_u64(&mut bytes, u64::from(self.protocol_version));
        for value in [
            &self.response_id,
            &self.request_id,
            &self.responder_peer_id,
            &self.receiver_peer_id,
            &self.credential_key_id,
        ] {
            push_id(&mut bytes, value);
        }
        for digest in [
            self.query_binding_digest,
            self.response_digest,
            self.source_cut_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.owner_epoch);
        push_u64(&mut bytes, self.issued_unix_ms);
        push_u64(&mut bytes, self.expires_unix_ms);
        push_digest(&mut bytes, self.nonce_digest);
        bytes
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ReplayEntryV1 {
    peer_id: StableId,
    nonce_digest: Digest32,
    expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FederationReplayWindowV1 {
    capacity: usize,
    entries: VecDeque<ReplayEntryV1>,
}

impl FederationReplayWindowV1 {
    pub fn new(capacity: usize) -> Result<Self, FederationWireError> {
        if capacity == 0 || capacity > MAX_FEDERATION_REPLAY_NONCES_V1 {
            return Err(FederationWireError::InvalidReplayCapacity);
        }
        Ok(Self {
            capacity,
            entries: VecDeque::with_capacity(capacity),
        })
    }

    fn observe(
        &mut self,
        peer_id: &StableId,
        nonce_digest: Digest32,
        expires_unix_ms: u64,
        now_unix_ms: u64,
    ) -> Result<(), FederationWireError> {
        self.entries
            .retain(|entry| now_unix_ms < entry.expires_unix_ms);
        if self.entries.iter().any(|entry| {
            entry.peer_id == *peer_id && entry.nonce_digest == nonce_digest
        }) {
            return Err(FederationWireError::ReplayDetected);
        }
        if self.entries.len() == self.capacity {
            self.entries.pop_front();
        }
        self.entries.push_back(ReplayEntryV1 {
            peer_id: peer_id.clone(),
            nonce_digest,
            expires_unix_ms,
        });
        Ok(())
    }
}

pub fn sign_wire_request_v1(
    mut request: FederationWireRequestV1,
    key: &SigningKey,
) -> Result<FederationWireRequestV1, FederationWireError> {
    validate_unsigned_request(&request)?;
    request.signature = key.sign(&request.signing_bytes()).to_bytes();
    Ok(request)
}

pub fn sign_wire_response_v1(
    mut response: FederationWireResponseV1,
    key: &SigningKey,
) -> Result<FederationWireResponseV1, FederationWireError> {
    validate_unsigned_response(&response)?;
    response.signature = key.sign(&response.signing_bytes()).to_bytes();
    Ok(response)
}

pub fn verify_wire_request_v1(
    now_unix_ms: u64,
    expected_receiver_peer_id: &StableId,
    credential: &FederationPeerCredentialV1,
    replay: &mut FederationReplayWindowV1,
    request: &FederationWireRequestV1,
) -> Result<(), FederationWireError> {
    validate_unsigned_request(request)?;
    credential.validate(now_unix_ms)?;
    if request.protocol_version != FEDERATION_WIRE_PROTOCOL_V1 {
        return Err(FederationWireError::UnsupportedVersion);
    }
    if request.receiver_peer_id != *expected_receiver_peer_id
        || request.sender_peer_id != credential.peer_id
        || request.credential_key_id != credential.key_id
    {
        return Err(FederationWireError::IdentityMismatch);
    }
    if request.owner_epoch != credential.owner_epoch {
        return Err(FederationWireError::OwnerEpochMismatch);
    }
    validate_window(request.issued_unix_ms, request.expires_unix_ms, now_unix_ms)?;
    verify_signature(
        &credential.verifying_key,
        &request.signing_bytes(),
        &request.signature,
    )?;
    replay.observe(
        &request.sender_peer_id,
        request.nonce_digest,
        request.expires_unix_ms.min(credential.expires_unix_ms),
        now_unix_ms,
    )
}

pub fn verify_wire_response_v1(
    now_unix_ms: u64,
    expected_receiver_peer_id: &StableId,
    expected_request: &FederationWireRequestV1,
    credential: &FederationPeerCredentialV1,
    replay: &mut FederationReplayWindowV1,
    response: &FederationWireResponseV1,
) -> Result<(), FederationWireError> {
    validate_unsigned_response(response)?;
    credential.validate(now_unix_ms)?;
    if response.protocol_version != FEDERATION_WIRE_PROTOCOL_V1 {
        return Err(FederationWireError::UnsupportedVersion);
    }
    if response.receiver_peer_id != *expected_receiver_peer_id
        || response.responder_peer_id != credential.peer_id
        || response.credential_key_id != credential.key_id
        || response.request_id != expected_request.request_id
    {
        return Err(FederationWireError::IdentityMismatch);
    }
    if response.owner_epoch != credential.owner_epoch {
        return Err(FederationWireError::OwnerEpochMismatch);
    }
    if response.query_binding_digest != expected_request.query_binding_digest
        || response.source_cut_digest != expected_request.source_cut_digest
    {
        return Err(FederationWireError::BindingMismatch);
    }
    validate_window(response.issued_unix_ms, response.expires_unix_ms, now_unix_ms)?;
    verify_signature(
        &credential.verifying_key,
        &response.signing_bytes(),
        &response.signature,
    )?;
    replay.observe(
        &response.responder_peer_id,
        response.nonce_digest,
        response.expires_unix_ms.min(credential.expires_unix_ms),
        now_unix_ms,
    )
}

fn validate_unsigned_request(request: &FederationWireRequestV1) -> Result<(), FederationWireError> {
    validate_common(
        request.protocol_version,
        request.owner_epoch,
        request.issued_unix_ms,
        request.expires_unix_ms,
        request.nonce_digest,
        request.source_cut_digest,
    )?;
    for digest in [
        request.query_binding_digest,
        request.scope_digest,
        request.purpose_digest,
    ] {
        ensure_digest(digest)?;
    }
    Ok(())
}

fn validate_unsigned_response(
    response: &FederationWireResponseV1,
) -> Result<(), FederationWireError> {
    validate_common(
        response.protocol_version,
        response.owner_epoch,
        response.issued_unix_ms,
        response.expires_unix_ms,
        response.nonce_digest,
        response.source_cut_digest,
    )?;
    ensure_digest(response.query_binding_digest)?;
    ensure_digest(response.response_digest)
}

fn validate_common(
    protocol_version: u16,
    owner_epoch: u64,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    nonce_digest: Digest32,
    source_cut_digest: Digest32,
) -> Result<(), FederationWireError> {
    if protocol_version == 0 {
        return Err(FederationWireError::UnsupportedVersion);
    }
    if owner_epoch == 0 {
        return Err(FederationWireError::ZeroValue("owner_epoch"));
    }
    if issued_unix_ms == 0 || expires_unix_ms <= issued_unix_ms {
        return Err(FederationWireError::InvalidTimeWindow);
    }
    ensure_digest(nonce_digest)?;
    ensure_digest(source_cut_digest)
}

fn validate_window(
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    now_unix_ms: u64,
) -> Result<(), FederationWireError> {
    if now_unix_ms < issued_unix_ms || now_unix_ms >= expires_unix_ms {
        return Err(FederationWireError::EnvelopeExpired);
    }
    Ok(())
}

fn verify_signature(
    verifying_key: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> Result<(), FederationWireError> {
    VerifyingKey::from_bytes(verifying_key)
        .map_err(|_| FederationWireError::InvalidVerifyingKey)?
        .verify_strict(message, &Signature::from_bytes(signature))
        .map_err(|_| FederationWireError::InvalidSignature)
}

fn ensure_digest(digest: Digest32) -> Result<(), FederationWireError> {
    if digest.is_zero() {
        return Err(FederationWireError::EmptyDigest);
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_u64(bytes, u64::try_from(raw.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FederationWireError {
    InvalidVersionRange,
    NoCommonVersion,
    UnsupportedVersion,
    InvalidReplayCapacity,
    ReplayDetected,
    CredentialRevoked,
    CredentialExpired,
    InvalidVerifyingKey,
    InvalidSignature,
    IdentityMismatch,
    OwnerEpochMismatch,
    BindingMismatch,
    InvalidTimeWindow,
    EnvelopeExpired,
    EmptyDigest,
    ZeroValue(&'static str),
}

impl fmt::Display for FederationWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for FederationWireError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_string()).expect("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn credential(key: &SigningKey, peer: &str, epoch: u64) -> FederationPeerCredentialV1 {
        FederationPeerCredentialV1 {
            peer_id: id(peer),
            key_id: id(&format!("key:{peer}")),
            verifying_key: key.verifying_key().to_bytes(),
            owner_epoch: epoch,
            effective_unix_ms: 10,
            expires_unix_ms: 1_000,
            revoked: false,
        }
    }

    fn request(key: &SigningKey) -> FederationWireRequestV1 {
        sign_wire_request_v1(
            FederationWireRequestV1 {
                protocol_version: FEDERATION_WIRE_PROTOCOL_V1,
                request_id: id("request:1"),
                sender_peer_id: id("peer:consumer"),
                receiver_peer_id: id("peer:owner"),
                credential_key_id: id("key:peer:consumer"),
                query_binding_digest: digest("query-binding"),
                scope_digest: digest("scope"),
                purpose_digest: digest("purpose"),
                source_cut_digest: digest("source-cut"),
                owner_epoch: 7,
                issued_unix_ms: 100,
                expires_unix_ms: 200,
                nonce_digest: digest("request-nonce"),
                signature: [0; 64],
            },
            key,
        )
        .expect("signed request")
    }

    #[test]
    fn version_negotiation_is_explicit_and_fail_closed() {
        let range = FederationWireVersionRangeV1 {
            minimum: 1,
            maximum: 1,
        };
        assert_eq!(negotiate_wire_protocol_v1(range, range), Ok(1));
        assert_eq!(
            negotiate_wire_protocol_v1(
                range,
                FederationWireVersionRangeV1 {
                    minimum: 2,
                    maximum: 3,
                },
            ),
            Err(FederationWireError::NoCommonVersion)
        );
    }

    #[test]
    fn authenticated_two_peer_round_trip_binds_cut_epoch_and_replay() {
        let consumer_key = SigningKey::from_bytes(&[7; 32]);
        let owner_key = SigningKey::from_bytes(&[9; 32]);
        let consumer_credential = credential(&consumer_key, "peer:consumer", 7);
        let owner_credential = credential(&owner_key, "peer:owner", 7);
        let request = request(&consumer_key);
        let mut owner_replay = FederationReplayWindowV1::new(8).expect("replay window");
        verify_wire_request_v1(
            120,
            &id("peer:owner"),
            &consumer_credential,
            &mut owner_replay,
            &request,
        )
        .expect("request verified");
        assert_eq!(
            verify_wire_request_v1(
                121,
                &id("peer:owner"),
                &consumer_credential,
                &mut owner_replay,
                &request,
            ),
            Err(FederationWireError::ReplayDetected)
        );

        let response = sign_wire_response_v1(
            FederationWireResponseV1 {
                protocol_version: 1,
                response_id: id("response:1"),
                request_id: request.request_id.clone(),
                responder_peer_id: id("peer:owner"),
                receiver_peer_id: id("peer:consumer"),
                credential_key_id: id("key:peer:owner"),
                query_binding_digest: request.query_binding_digest,
                response_digest: digest("response"),
                source_cut_digest: request.source_cut_digest,
                owner_epoch: 7,
                issued_unix_ms: 121,
                expires_unix_ms: 190,
                nonce_digest: digest("response-nonce"),
                signature: [0; 64],
            },
            &owner_key,
        )
        .expect("signed response");
        let mut consumer_replay = FederationReplayWindowV1::new(8).expect("replay window");
        verify_wire_response_v1(
            130,
            &id("peer:consumer"),
            &request,
            &owner_credential,
            &mut consumer_replay,
            &response,
        )
        .expect("response verified");
    }

    #[test]
    fn tamper_epoch_and_source_cut_fail_closed() {
        let key = SigningKey::from_bytes(&[7; 32]);
        let credential = credential(&key, "peer:consumer", 7);
        let request = request(&key);
        let mut tampered = request.clone();
        tampered.source_cut_digest = digest("other-cut");
        let mut replay = FederationReplayWindowV1::new(8).expect("replay window");
        assert_eq!(
            verify_wire_request_v1(
                120,
                &id("peer:owner"),
                &credential,
                &mut replay,
                &tampered,
            ),
            Err(FederationWireError::InvalidSignature)
        );
        let mut stale_epoch = request;
        stale_epoch.owner_epoch = 8;
        stale_epoch.signature = key.sign(&stale_epoch.signing_bytes()).to_bytes();
        assert_eq!(
            verify_wire_request_v1(
                120,
                &id("peer:owner"),
                &credential,
                &mut replay,
                &stale_epoch,
            ),
            Err(FederationWireError::OwnerEpochMismatch)
        );
    }
}
'''


def write_wire() -> None:
    write("codex-rs/hepta-memory-federation/src/wire.rs", wire_source())


def write_docs() -> None:
    write(
        "codex-rs/hepta-memory-federation/README.md",
        r'''# `codex-hepta-memory-federation`

Read-only, fail-closed federation contracts for cognitive evidence.

The default build exposes the generation-bound V2 single-attempt engine and the
source-level authenticated wire V1 envelope. The original V1 receipt API is
available only with `--features legacy-v1` and is deprecated.

```rust
use codex_hepta_memory_federation::{execute_once_outcome, FederationAttemptOutcomeV2};

// Product hosts provide a transport, live authority observer and cancellation
// control. The engine performs exactly one attempt and never owns a retry queue.
```

Focused verification:

```text
cargo test -p codex-hepta-memory-federation --lib
cargo test -p codex-hepta-memory-federation --lib --features legacy-v1
cargo clippy -p codex-hepta-memory-federation --all-targets -- -D warnings
```

The wire types do not open a network connection or enroll a peer. Physical
multi-host activation requires the external qualification listed in
`docs/modules/memory.federation/OPERATIONS.md`.
''',
    )
    write(
        "docs/modules/memory.federation/README.md",
        r'''# memory.federation documentation map

- `TECHNICAL.md`: normative module implementation and ownership guide.
- `V2_HARDENING.md`: generation-bound checked-engine and product composition.
- `WIRE_PROTOCOL_V1.md`: authenticated cross-host envelope contract.
- `memory-federation-wire-v1.schema.json`: language-neutral field registry.
- `sequence.mmd`: dispatch, authority and final-use sequence.
- `THREAT_MODEL.md`: trust boundaries and negative controls.
- `OPERATIONS.md`: SLO, canary, rollback and incident procedures.
- `CURRENT_STATE.json`: machine-generated source and qualification truth.
- `IMPLEMENTATION_MAP.json`: machine-checked source navigation.
''',
    )
    write(
        "docs/modules/memory.federation/WIRE_PROTOCOL_V1.md",
        r'''# memory.federation authenticated wire protocol V1

## Status

The repository implements the envelope, signature, version-negotiation and
bounded replay semantics. It does **not** claim that a production network
transport, credential distributor or two-real-host deployment has been
qualified.

## Request binding

Every signed request binds protocol version, request/sender/receiver/key
identities, exact V2 query binding, scope, purpose, authenticated owner source
cut, owner epoch, issue/expiry time and a unique nonce digest. The receiver
verifies the currently enrolled peer credential before admitting the nonce into
a bounded replay window.

## Response binding

Every signed response binds the originating request, exact query binding,
canonical V2 response digest, the same authenticated source cut, owner epoch,
time window, receiver identity and a fresh response nonce.

## Credential and rotation rules

Credentials are external authority facts. They carry peer ID, key ID, Ed25519
verifying key, owner epoch, validity interval and revocation state. Rotation must
advance the key identity and, whenever ownership or durable source identity
changes, the owner epoch. A response signed under a stale or revoked credential
is rejected even when its payload digest is internally consistent.

## Replay and overload

Replay state is bounded by `MAX_FEDERATION_REPLAY_NONCES_V1`; production hosts
must durably partition replay state by enrolled peer/key/epoch when crash replay
matters. Full queues evict the oldest unexpired observation only after a valid
signature has been checked. Transport admission must impose an independent
connection/concurrency limit.
''',
    )
    write(
        "docs/modules/memory.federation/THREAT_MODEL.md",
        r'''# memory.federation threat model

## Protected assets

The protected assets are current capability authority, exact query purpose and
scope, owner memory/source cuts, evidence integrity, consumer workspace
isolation, cancellation disposition and coverage truth.

## Trust boundaries

1. Consumer product host to the checked V2 engine.
2. Checked engine to an enrolled transport.
3. Network transport to authenticated peer credential and replay state.
4. Remote evidence to the local attachment compiler.
5. Prepared attachment to the physical provider-dispatch final-use guard.

## Required negative controls

- A caller lease cannot outlive live authority.
- No transport starts before current preflight authority.
- A response is rejected on peer/query/scope/purpose/cut/epoch drift.
- Revocation or generation drift suppresses all evidence.
- Timeout and cancellation never become a valid empty result.
- A failed peer cannot abort or erase independently verified peers.
- Bounded discovery, attempts, diagnostics and replay state prevent queue growth.
- Legacy V1 is disabled by default and cannot enter the product V2 path.
- A response digest is not remote identity; Ed25519 credential verification is
  required at a cross-host boundary.
- Physical-send revalidation rejects expiry crossing and clock regression.

## Residual/external risk

Real credential custody, mTLS/channel binding, host compromise, network
partition behavior, durable replay recovery, target-host overload and operator
response require independent qualification and are not self-certified here.
''',
    )
    write(
        "docs/modules/memory.federation/sequence.mmd",
        r'''sequenceDiagram
    participant C as Consumer/Agentd
    participant A as Live authority
    participant E as V2 checked engine
    participant P as Authenticated peer
    participant M as Memory extension
    participant R as Provider transport

    C->>A: preflight(query binding, lease epoch)
    A-->>C: Current + authority expiry
    C->>E: execute_once_outcome
    E->>P: signed request(version, peer, cut, epoch, nonce)
    P-->>E: signed response(response digest, cut, epoch, nonce)
    E->>A: post-I/O revalidation
    A-->>E: Current / Revoked / StaleGeneration
    E-->>C: typed result or typed failed outcome
    C-->>M: deterministic aggregate + bounded diagnostics
    M->>A: final-use capability/memory batch revalidation
    A-->>M: current bindings or stale/unavailable
    alt all selected bindings remain current
        M->>R: physical provider dispatch
    else drift, expiry, cancellation, or unavailable
        M--xR: no dispatch
    end
''',
    )
    write(
        "docs/modules/memory.federation/OPERATIONS.md",
        r'''# memory.federation operator runbook

## Qualification and SLO inputs

Repository qualification records exact source/tree, crate/product/extension
tests, Agentd/App Server compilation and strict lint. Deployment qualification
must additionally measure p50/p95/p99 discovery and total recall latency,
partial/failed peer ratio, final-use rejection ratio, cancellation latency,
replay rejection, memory/FD growth and SQLite contention at 1/8/16 admitted
peers and 128 owner candidates.

No numeric production SLO is granted by source. A selected host profile must
publish thresholds and alert ownership before activation.

## Canary

1. Enable authenticated federation for a bounded allowlist of consumer/owner
   pairs with no fallback to legacy V1.
2. Compare local-only and federated coverage, latency and provider-dispatch
   rejection without treating missing peers as empty.
3. Exercise grant, revoke, key rotation, owner-epoch change, timeout and turn
   cancellation.
4. Stop the canary on unexplained evidence admission, replay acceptance,
   unbounded resource growth or stale final-use dispatch.

## Rollback

Disable product federation composition and discard ephemeral results. Do not
restore revoked grants, replay old responses, downgrade automatically to legacy
V1 or reinterpret failed coverage as empty. Wire credential/replay stores remain
owned by their selected host and must follow that host's rollback procedure.

## Incident triage

- `discovery_unavailable`: inspect owner store/read-only open and bounded timeout.
- `deadline_or_cancelled`: inspect global horizon, cancellation receipts and
  transport-drop behavior.
- `authority_rejected`: inspect grant generation/revision, owner epoch and
  credential validity.
- `integrity_rejected`: quarantine peer/key, retain signed envelope and compare
  query/response/cut digests.
- `transport_unavailable`: inspect authenticated channel, overload and partition.

Independent security review and two-real-host fault qualification remain required
before promotion or release.
''',
    )
    write(
        "docs/modules/memory.federation/memory-federation-wire-v1.schema.json",
        r'''{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "hepta.memory-federation.wire.v1",
  "title": "Hepta memory federation authenticated wire envelope V1",
  "type": "object",
  "oneOf": [
    { "$ref": "#/$defs/request" },
    { "$ref": "#/$defs/response" }
  ],
  "$defs": {
    "digest32": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "signature64": { "type": "string", "pattern": "^[0-9a-f]{128}$" },
    "common": {
      "type": "object",
      "required": ["protocol_version", "credential_key_id", "owner_epoch", "issued_unix_ms", "expires_unix_ms", "nonce_digest", "signature"],
      "properties": {
        "protocol_version": { "const": 1 },
        "credential_key_id": { "type": "string", "minLength": 1 },
        "owner_epoch": { "type": "integer", "minimum": 1 },
        "issued_unix_ms": { "type": "integer", "minimum": 1 },
        "expires_unix_ms": { "type": "integer", "minimum": 1 },
        "nonce_digest": { "$ref": "#/$defs/digest32" },
        "signature": { "$ref": "#/$defs/signature64" }
      }
    },
    "request": {
      "allOf": [
        { "$ref": "#/$defs/common" },
        {
          "type": "object",
          "required": ["request_id", "sender_peer_id", "receiver_peer_id", "query_binding_digest", "scope_digest", "purpose_digest", "source_cut_digest"],
          "properties": {
            "request_id": { "type": "string", "minLength": 1 },
            "sender_peer_id": { "type": "string", "minLength": 1 },
            "receiver_peer_id": { "type": "string", "minLength": 1 },
            "query_binding_digest": { "$ref": "#/$defs/digest32" },
            "scope_digest": { "$ref": "#/$defs/digest32" },
            "purpose_digest": { "$ref": "#/$defs/digest32" },
            "source_cut_digest": { "$ref": "#/$defs/digest32" }
          }
        }
      ]
    },
    "response": {
      "allOf": [
        { "$ref": "#/$defs/common" },
        {
          "type": "object",
          "required": ["response_id", "request_id", "responder_peer_id", "receiver_peer_id", "query_binding_digest", "response_digest", "source_cut_digest"],
          "properties": {
            "response_id": { "type": "string", "minLength": 1 },
            "request_id": { "type": "string", "minLength": 1 },
            "responder_peer_id": { "type": "string", "minLength": 1 },
            "receiver_peer_id": { "type": "string", "minLength": 1 },
            "query_binding_digest": { "$ref": "#/$defs/digest32" },
            "response_digest": { "$ref": "#/$defs/digest32" },
            "source_cut_digest": { "$ref": "#/$defs/digest32" }
          }
        }
      ]
    }
  }
}
''',
    )

    tech_path = "docs/modules/memory.federation/TECHNICAL.md"
    tech = read(tech_path).rstrip()
    tech += r'''

## 18. Full-closure source overlay

The default canonical crate now excludes the deprecated V1 receipt surface;
compatibility builds must opt into `legacy-v1`. `execute_once_outcome` projects
complete, partial, empty, indeterminate and failed attempts through one typed
product channel while preserving the original `execute_once` API.

Cross-host source protocol V1 is registered by
`memory-federation-wire-v1.schema.json` and implemented in `wire.rs`. It binds
version, peer/key identities, current credential, owner epoch, source cut,
query/response digests, validity windows, signatures and bounded replay state.
This is source implementation, not physical network qualification. Current
machine truth is generated in `CURRENT_STATE.json`; no prose or manually edited
boolean may promote execution, independent acceptance, activation or release.
'''
    write(tech_path, tech)

    hard_path = "docs/modules/memory.federation/V2_HARDENING.md"
    hard = read(hard_path).rstrip()
    hard += r'''

## 10. Unified outcomes, legacy retirement and wire boundary

Product orchestration consumes `FederationAttemptOutcomeV2`, so a checked
runtime failure cannot alternate unpredictably between an opaque Rust error and
a successful-looking empty batch. Legacy V1 is feature-gated and deprecated.
Authenticated wire V1 adds peer credential, source-cut, owner-epoch, version and
replay checks around the canonical V2 query/response digests. The in-process
adapter remains valid, while physical multi-host activation stays gated on
selected-host tests and independent review.
'''
    write(hard_path, hard)


def main() -> None:
    reset_from_main(
        [
            "codex-rs/hepta-memory-federation/Cargo.toml",
            "codex-rs/hepta-memory-federation/src/lib.rs",
            "codex-rs/hepta-memory-federation/src/lib_tests.rs",
            "codex-rs/hepta-memory-federation/src/v2.rs",
            "codex-rs/hepta-memory-federation/src/v2_tests.rs",
            "docs/modules/memory.federation/TECHNICAL.md",
            "docs/modules/memory.federation/V2_HARDENING.md",
        ]
    )
    patch_state_generator()
    patch_cargo()
    patch_lib_and_legacy()
    patch_v2_outcome()
    write_wire()
    write_docs()
    print("memory.federation canonical closure applied")


if __name__ == "__main__":
    main()
