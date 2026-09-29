//! Closed-world executable qualification for the AuthBus verifier.
//!
//! The runner constructs and executes the negative matrix against the real
//! AuthBus APIs. Callers cannot self-attest that a case rejected or provide an
//! arbitrary evidence digest.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_authbus::Error as AuthBusError;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PreverifiedAuthEnvelope;
use codex_hepta_authbus::ReplayWindow;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_authbus::TrustedReplayContext;
use codex_hepta_authbus::VerificationReceipt;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const REQUIRED_CASES: usize = 4;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NegativeCase {
    Expired,
    Revoked,
    Replay,
    PayloadDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CaseEvidence {
    pub case: NegativeCase,
    pub case_id: StableId,
    pub observed_error: &'static str,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationReceipt {
    pub cases: Vec<CaseEvidence>,
    pub positive_envelope_digest: Digest32,
    pub qualification_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    UnexpectedAcceptance(NegativeCase),
    UnexpectedError {
        case: NegativeCase,
        observed: String,
    },
    PositivePathFailed(String),
    PositiveReceiptGrantedAuthority,
    DuplicateCase,
    MissingRequiredCase,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Execute the exact closed-world negative matrix against AuthBus.
pub fn qualify() -> Result<QualificationReceipt, Error> {
    let signing_key = SigningKey::from_bytes(&[91; 32]);
    let issuer_id = id("issuer:qualification");
    let subject_id = id("subject:qualification");
    let message_id = id("message:qualification");
    let key_epoch = Generation::new(7).expect("non-zero qualification generation");
    let scope = Digest32::of_bytes(b"qualification-scope");
    let payload = Digest32::of_bytes(b"qualification-payload");
    let claims = SignedMessageClaims {
        issuer_id: issuer_id.clone(),
        key_epoch,
        message_id,
        subject_id: subject_id.clone(),
        scope_digest: scope,
        payload_digest: payload,
        sequence: 11,
        expires_at_ms: 10_000,
    };
    let message = SignedMessage {
        signature: signing_key.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
    let active = IssuerRegistration {
        issuer_id: issuer_id.clone(),
        key_epoch,
        verifying_key: signing_key.verifying_key(),
        revoked: false,
    };

    let positive = message
        .authenticate(&active, scope, payload, 9_000)
        .map_err(|error| Error::PositivePathFailed(format!("{error:?}")))?;
    let positive_digest = bind_positive_receipt(positive.receipt())?;

    let mut cases = vec![
        execute_authenticate_case(
            NegativeCase::Expired,
            &message,
            &active,
            scope,
            payload,
            10_000,
            AuthBusError::Expired,
        )?,
        execute_authenticate_case(
            NegativeCase::PayloadDrift,
            &message,
            &active,
            scope,
            Digest32::of_bytes(b"drifted-payload"),
            9_000,
            AuthBusError::PayloadMismatch,
        )?,
    ];

    let revoked = IssuerRegistration {
        issuer_id: issuer_id.clone(),
        key_epoch,
        verifying_key: signing_key.verifying_key(),
        revoked: true,
    };
    cases.push(execute_authenticate_case(
        NegativeCase::Revoked,
        &message,
        &revoked,
        scope,
        payload,
        9_000,
        AuthBusError::Revoked,
    )?);
    cases.push(execute_replay_case(
        &message,
        &issuer_id,
        &subject_id,
        key_epoch,
        scope,
        payload,
    )?);

    cases.sort_by_key(|case| case.case);
    validate_matrix(&cases)?;

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.authbus.executable-qualification.v2\0");
    bytes.extend_from_slice(positive_digest.as_array());
    for case in &cases {
        bytes.push(case_code(case.case));
        push_id(&mut bytes, &case.case_id);
        push_bytes(&mut bytes, case.observed_error.as_bytes());
        bytes.extend_from_slice(case.evidence_digest.as_array());
    }
    Ok(QualificationReceipt {
        cases,
        positive_envelope_digest: positive_digest,
        qualification_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn bind_positive_receipt(receipt: &VerificationReceipt) -> Result<Digest32, Error> {
    if receipt.authority.grants_any() {
        return Err(Error::PositiveReceiptGrantedAuthority);
    }
    Ok(receipt.envelope_digest)
}

fn execute_authenticate_case(
    case: NegativeCase,
    message: &SignedMessage,
    issuer: &IssuerRegistration,
    expected_scope: Digest32,
    expected_payload: Digest32,
    now_ms: u64,
    expected: AuthBusError,
) -> Result<CaseEvidence, Error> {
    let observed = message.authenticate(
        issuer,
        expected_scope,
        expected_payload,
        now_ms,
    );
    match observed {
        Ok(_) => Err(Error::UnexpectedAcceptance(case)),
        Err(error) if error == expected => Ok(case_evidence(case, error_name(&error))),
        Err(error) => Err(Error::UnexpectedError {
            case,
            observed: format!("{error:?}"),
        }),
    }
}

fn execute_replay_case(
    message: &SignedMessage,
    issuer_id: &StableId,
    subject_id: &StableId,
    key_epoch: Generation,
    scope: Digest32,
    payload: Digest32,
) -> Result<CaseEvidence, Error> {
    let signature_digest = Digest32::of_bytes(&message.signature);
    let context = TrustedReplayContext {
        issuer_id: issuer_id.clone(),
        key_epoch,
        now_ms: 9_000,
        revoked: false,
    };
    let envelope = PreverifiedAuthEnvelope {
        message_id: message.claims.message_id.clone(),
        subject_id: subject_id.clone(),
        scope_digest: scope,
        payload_digest: payload,
        signature_digest,
        sequence: message.claims.sequence,
        expires_at_ms: message.claims.expires_at_ms,
    };
    let mut replay = ReplayWindow::new(1);
    replay
        .verify(
            context.clone(),
            envelope.clone(),
            scope,
            payload,
        )
        .map_err(|error| Error::UnexpectedError {
            case: NegativeCase::Replay,
            observed: format!("first replay admission failed: {error:?}"),
        })?;
    match replay.verify(context, envelope, scope, payload) {
        Err(AuthBusError::Replay) => {
            Ok(case_evidence(NegativeCase::Replay, error_name(&AuthBusError::Replay)))
        }
        Ok(_) => Err(Error::UnexpectedAcceptance(NegativeCase::Replay)),
        Err(error) => Err(Error::UnexpectedError {
            case: NegativeCase::Replay,
            observed: format!("{error:?}"),
        }),
    }
}

fn case_evidence(case: NegativeCase, observed_error: &'static str) -> CaseEvidence {
    let case_id = id(match case {
        NegativeCase::Expired => "case:expired",
        NegativeCase::Revoked => "case:revoked",
        NegativeCase::Replay => "case:replay",
        NegativeCase::PayloadDrift => "case:payload-drift",
    });
    let mut bytes = b"hepta.authbus.negative-case.v2\0".to_vec();
    bytes.push(case_code(case));
    push_id(&mut bytes, &case_id);
    push_bytes(&mut bytes, observed_error.as_bytes());
    CaseEvidence {
        case,
        case_id,
        observed_error,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

fn validate_matrix(cases: &[CaseEvidence]) -> Result<(), Error> {
    let required = BTreeSet::from([
        NegativeCase::Expired,
        NegativeCase::Revoked,
        NegativeCase::Replay,
        NegativeCase::PayloadDrift,
    ]);
    let seen = cases.iter().map(|case| case.case).collect::<BTreeSet<_>>();
    if seen.len() != cases.len() {
        return Err(Error::DuplicateCase);
    }
    if cases.len() != REQUIRED_CASES || seen != required {
        return Err(Error::MissingRequiredCase);
    }
    Ok(())
}

fn error_name(error: &AuthBusError) -> &'static str {
    match error {
        AuthBusError::Expired => "expired",
        AuthBusError::Revoked => "revoked",
        AuthBusError::Replay => "replay",
        AuthBusError::PayloadMismatch => "payload_mismatch",
        _ => "unexpected",
    }
}

fn case_code(value: NegativeCase) -> u8 {
    match value {
        NegativeCase::Expired => 0,
        NegativeCase::Revoked => 1,
        NegativeCase::Replay => 2,
        NegativeCase::PayloadDrift => 3,
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("static qualification identifier must be valid")
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_bytes(bytes, value.as_str().as_bytes());
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
