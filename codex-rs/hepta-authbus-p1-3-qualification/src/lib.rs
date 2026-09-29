//! Executable closed-world negative qualification for the AuthBus verifier.
//! The runner constructs and executes every case against the candidate API;
//! callers cannot supply a boolean rejection claim or an arbitrary case digest.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_authbus::Error as AuthBusError;
use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PreverifiedAuthEnvelope;
use codex_hepta_authbus::ReplayWindow;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_authbus::TrustedReplayContext;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const CASE_COUNT: usize = 4;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NegativeCase {
    Expired,
    Revoked,
    Replay,
    PayloadDrift,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObservedRejection {
    Expired,
    Revoked,
    Replay,
    PayloadMismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationContext {
    pub candidate_source_digest: Digest32,
    pub merge_base_digest: Digest32,
    pub cargo_lock_digest: Digest32,
    pub target_triple: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CaseEvidence {
    pub case: NegativeCase,
    pub observed: ObservedRejection,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationReceipt {
    pub context: QualificationContext,
    pub cases: Vec<CaseEvidence>,
    pub qualification_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    InvalidContext,
    Fixture,
    UnexpectedOutcome {
        case: NegativeCase,
        observed: String,
    },
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn qualify(context: QualificationContext) -> Result<QualificationReceipt, Error> {
    validate_context(&context)?;
    let cases = vec![
        execute_signed_case(NegativeCase::Expired)?,
        execute_signed_case(NegativeCase::Revoked)?,
        execute_replay_case()?,
        execute_signed_case(NegativeCase::PayloadDrift)?,
    ];
    if cases.len() != CASE_COUNT {
        return Err(Error::Fixture);
    }
    let mut bytes = b"hepta.authbus.qualification.v2\0".to_vec();
    bytes.extend_from_slice(context.candidate_source_digest.as_array());
    bytes.extend_from_slice(context.merge_base_digest.as_array());
    bytes.extend_from_slice(context.cargo_lock_digest.as_array());
    push_id(&mut bytes, &context.target_triple);
    for evidence in &cases {
        bytes.push(case_code(evidence.case));
        bytes.push(rejection_code(evidence.observed));
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
    }
    Ok(QualificationReceipt {
        context,
        cases,
        qualification_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_context(context: &QualificationContext) -> Result<(), Error> {
    if context.candidate_source_digest.is_zero()
        || context.merge_base_digest.is_zero()
        || context.cargo_lock_digest.is_zero()
    {
        return Err(Error::InvalidContext);
    }
    Ok(())
}

fn execute_signed_case(case: NegativeCase) -> Result<CaseEvidence, Error> {
    let key = SigningKey::from_bytes(&[case_code(case) + 31; 32]);
    let scope = Digest32::of_bytes(b"qualification-scope");
    let payload = Digest32::of_bytes(b"qualification-payload");
    let claims = SignedMessageClaims {
        issuer_id: id("issuer:qualification")?,
        key_epoch: Generation::new(1).map_err(|_| Error::Fixture)?,
        message_id: id(match case {
            NegativeCase::Expired => "message:expired",
            NegativeCase::Revoked => "message:revoked",
            NegativeCase::PayloadDrift => "message:payload-drift",
            NegativeCase::Replay => return Err(Error::Fixture),
        })?,
        subject_id: id("subject:qualification")?,
        scope_digest: scope,
        payload_digest: payload,
        sequence: 1,
        expires_at_ms: 200,
    };
    let signature = key.sign(&claims.signing_bytes()).to_bytes();
    let message = SignedMessage {
        claims: claims.clone(),
        signature,
    };
    let issuer = IssuerRegistration {
        issuer_id: claims.issuer_id.clone(),
        key_epoch: claims.key_epoch,
        verifying_key: key.verifying_key(),
        revoked: case == NegativeCase::Revoked,
    };
    let expected_payload = if case == NegativeCase::PayloadDrift {
        Digest32::of_bytes(b"drifted-payload")
    } else {
        payload
    };
    let now_ms = if case == NegativeCase::Expired { 200 } else { 100 };
    let observed = match message.authenticate(&issuer, scope, expected_payload, now_ms) {
        Ok(_) => {
            return Err(Error::UnexpectedOutcome {
                case,
                observed: "authenticated".to_owned(),
            });
        }
        Err(error) => error,
    };
    let expected = match case {
        NegativeCase::Expired => AuthBusError::Expired,
        NegativeCase::Revoked => AuthBusError::Revoked,
        NegativeCase::PayloadDrift => AuthBusError::PayloadMismatch,
        NegativeCase::Replay => return Err(Error::Fixture),
    };
    if observed != expected {
        return Err(Error::UnexpectedOutcome {
            case,
            observed: observed.to_string(),
        });
    }
    Ok(case_evidence(case, observed_rejection(&observed)?, &claims.signing_bytes()))
}

fn execute_replay_case() -> Result<CaseEvidence, Error> {
    let issuer_id = id("issuer:qualification-replay")?;
    let key_epoch = Generation::new(1).map_err(|_| Error::Fixture)?;
    let scope = Digest32::of_bytes(b"qualification-replay-scope");
    let payload = Digest32::of_bytes(b"qualification-replay-payload");
    let envelope = PreverifiedAuthEnvelope {
        message_id: id("message:replay")?,
        subject_id: id("subject:qualification")?,
        scope_digest: scope,
        payload_digest: payload,
        signature_digest: Digest32::of_bytes(b"verified-signature"),
        sequence: 7,
        expires_at_ms: 200,
    };
    let context = TrustedReplayContext {
        issuer_id,
        key_epoch,
        now_ms: 100,
        revoked: false,
    };
    let mut replay = ReplayWindow::new(1);
    replay
        .verify(context.clone(), envelope.clone(), scope, payload)
        .map_err(|_| Error::Fixture)?;
    let observed = replay
        .verify(context, envelope.clone(), scope, payload)
        .expect_err("replay qualification case unexpectedly authenticated");
    if observed != AuthBusError::Replay {
        return Err(Error::UnexpectedOutcome {
            case: NegativeCase::Replay,
            observed: observed.to_string(),
        });
    }
    let mut input = Vec::new();
    push_id(&mut input, &envelope.message_id);
    push_id(&mut input, &envelope.subject_id);
    input.extend_from_slice(envelope.scope_digest.as_array());
    input.extend_from_slice(envelope.payload_digest.as_array());
    input.extend_from_slice(&envelope.sequence.to_be_bytes());
    Ok(case_evidence(
        NegativeCase::Replay,
        ObservedRejection::Replay,
        &input,
    ))
}

fn case_evidence(
    case: NegativeCase,
    observed: ObservedRejection,
    input: &[u8],
) -> CaseEvidence {
    let mut bytes = b"hepta.authbus.qualification-case.v2\0".to_vec();
    bytes.push(case_code(case));
    bytes.push(rejection_code(observed));
    bytes.extend_from_slice(&(input.len() as u64).to_be_bytes());
    bytes.extend_from_slice(input);
    CaseEvidence {
        case,
        observed,
        evidence_digest: Digest32::of_bytes(&bytes),
    }
}

fn observed_rejection(error: &AuthBusError) -> Result<ObservedRejection, Error> {
    match error {
        AuthBusError::Expired => Ok(ObservedRejection::Expired),
        AuthBusError::Revoked => Ok(ObservedRejection::Revoked),
        AuthBusError::Replay => Ok(ObservedRejection::Replay),
        AuthBusError::PayloadMismatch => Ok(ObservedRejection::PayloadMismatch),
        _ => Err(Error::Fixture),
    }
}

fn id(value: &str) -> Result<StableId, Error> {
    StableId::new(value).map_err(|_| Error::Fixture)
}

fn case_code(value: NegativeCase) -> u8 {
    match value {
        NegativeCase::Expired => 0,
        NegativeCase::Revoked => 1,
        NegativeCase::Replay => 2,
        NegativeCase::PayloadDrift => 3,
    }
}

fn rejection_code(value: ObservedRejection) -> u8 {
    match value {
        ObservedRejection::Expired => 0,
        ObservedRejection::Revoked => 1,
        ObservedRejection::Replay => 2,
        ObservedRejection::PayloadMismatch => 3,
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
