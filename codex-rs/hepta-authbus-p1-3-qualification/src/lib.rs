//! Closed-world negative qualification for the AuthBus verifier.

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

const MAX_CASES: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum NegativeCase {
    Expired,
    Revoked,
    Replay,
    PayloadDrift,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionProvenance {
    pub source_sha: String,
    pub source_tree: String,
    pub executable_digest: Digest32,
    pub command_digest: Digest32,
    pub runner_id: StableId,
    pub started_at_ms: u64,
    pub completed_at_ms: u64,
    pub exit_code: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CaseEvidence {
    pub case: NegativeCase,
    pub case_id: StableId,
    pub rejected: bool,
    pub evidence_digest: Digest32,
    pub execution: ExecutionProvenance,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationReceipt {
    pub case_count: usize,
    pub qualification_digest: Digest32,
    pub source_sha: String,
    pub source_tree: String,
    pub executable_digest: Digest32,
    pub command_digest: Digest32,
    pub runner_id: StableId,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    CaseLimitExceeded,
    DuplicateCase,
    MissingRequiredCase,
    CaseDidNotReject(String),
    EmptyEvidence(String),
    InvalidExecutionProvenance,
    MixedExecutionProvenance,
    ExecutionFailed(i32),
    NativeCaseUnexpected(String),
    PositiveReceiptGrantedAuthority,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn bind_positive_receipt(receipt: &VerificationReceipt) -> Result<Digest32, Error> {
    if receipt.authority.grants_any() {
        return Err(Error::PositiveReceiptGrantedAuthority);
    }
    Ok(receipt.envelope_digest)
}

pub fn qualify(mut cases: Vec<CaseEvidence>) -> Result<QualificationReceipt, Error> {
    if cases.len() > MAX_CASES {
        return Err(Error::CaseLimitExceeded);
    }
    cases.sort_by(|left, right| {
        left.case
            .cmp(&right.case)
            .then_with(|| left.case_id.cmp(&right.case_id))
    });
    let execution = cases
        .first()
        .map(|case| case.execution.clone())
        .ok_or(Error::MissingRequiredCase)?;
    validate_execution(&execution)?;
    if cases.iter().any(|case| case.execution != execution) {
        return Err(Error::MixedExecutionProvenance);
    }

    let required = BTreeSet::from([
        NegativeCase::Expired,
        NegativeCase::Revoked,
        NegativeCase::Replay,
        NegativeCase::PayloadDrift,
    ]);
    let mut seen = BTreeSet::new();
    for evidence in &cases {
        if !seen.insert(evidence.case) {
            return Err(Error::DuplicateCase);
        }
        if !evidence.rejected {
            return Err(Error::CaseDidNotReject(evidence.case_id.to_string()));
        }
        if evidence.evidence_digest.is_zero() {
            return Err(Error::EmptyEvidence(evidence.case_id.to_string()));
        }
    }
    if seen != required {
        return Err(Error::MissingRequiredCase);
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.authbus.qualification.v2\0");
    push_text(&mut bytes, &execution.source_sha);
    push_text(&mut bytes, &execution.source_tree);
    bytes.extend_from_slice(execution.executable_digest.as_array());
    bytes.extend_from_slice(execution.command_digest.as_array());
    push_id(&mut bytes, &execution.runner_id);
    bytes.extend_from_slice(&execution.started_at_ms.to_be_bytes());
    bytes.extend_from_slice(&execution.completed_at_ms.to_be_bytes());
    bytes.extend_from_slice(&execution.exit_code.to_be_bytes());
    for evidence in &cases {
        bytes.push(case_code(evidence.case));
        push_id(&mut bytes, &evidence.case_id);
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
    }
    Ok(QualificationReceipt {
        case_count: cases.len(),
        qualification_digest: Digest32::of_bytes(&bytes),
        source_sha: execution.source_sha,
        source_tree: execution.source_tree,
        executable_digest: execution.executable_digest,
        command_digest: execution.command_digest,
        runner_id: execution.runner_id,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn execute_native_negative_qualification(
    execution: ExecutionProvenance,
) -> Result<QualificationReceipt, Error> {
    validate_execution(&execution)?;
    let key = SigningKey::from_bytes(&[93; 32]);
    let issuer_id = stable("issuer:p1-3-native")?;
    let subject_id = stable("subject:p1-3-native")?;
    let scope = Digest32::of_bytes(b"p1-3-native-scope");
    let payload = Digest32::of_bytes(b"p1-3-native-payload");
    let claims = SignedMessageClaims {
        issuer_id: issuer_id.clone(),
        key_epoch: Generation::new(1).map_err(|_| Error::InvalidExecutionProvenance)?,
        message_id: stable("message:p1-3-native")?,
        subject_id: subject_id.clone(),
        scope_digest: scope,
        payload_digest: payload,
        sequence: 1,
        expires_at_ms: 2_000,
    };
    let signed = SignedMessage {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims: claims.clone(),
    };
    let registration = IssuerRegistration {
        issuer_id: issuer_id.clone(),
        key_epoch: claims.key_epoch,
        verifying_key: key.verifying_key(),
        revoked: false,
    };

    let expired = signed.authenticate(&registration, scope, payload, 2_000);
    require_auth_error(NegativeCase::Expired, expired.err(), AuthBusError::Expired)?;

    let revoked_registration = IssuerRegistration {
        issuer_id: issuer_id.clone(),
        key_epoch: claims.key_epoch,
        verifying_key: key.verifying_key(),
        revoked: true,
    };
    let revoked = signed.authenticate(&revoked_registration, scope, payload, 1_000);
    require_auth_error(NegativeCase::Revoked, revoked.err(), AuthBusError::Revoked)?;

    let drift = signed.authenticate(
        &registration,
        scope,
        Digest32::of_bytes(b"p1-3-native-other-payload"),
        1_000,
    );
    require_auth_error(
        NegativeCase::PayloadDrift,
        drift.err(),
        AuthBusError::PayloadMismatch,
    )?;

    let envelope = PreverifiedAuthEnvelope {
        message_id: claims.message_id.clone(),
        subject_id,
        scope_digest: scope,
        payload_digest: payload,
        signature_digest: Digest32::of_bytes(&signed.signature),
        sequence: 1,
        expires_at_ms: 2_000,
    };
    let context = TrustedReplayContext {
        issuer_id,
        key_epoch: claims.key_epoch,
        now_ms: 1_000,
        revoked: false,
    };
    let mut replay = ReplayWindow::new(1);
    replay
        .verify(
            context.clone(),
            envelope.clone(),
            scope,
            payload,
        )
        .map_err(|error| Error::NativeCaseUnexpected(format!("replay setup: {error:?}")))?;
    let replay_error = replay
        .verify(context, envelope, scope, payload)
        .err();
    require_auth_error(NegativeCase::Replay, replay_error, AuthBusError::Replay)?;

    let cases = [
        (NegativeCase::Expired, "case:expired", AuthBusError::Expired),
        (NegativeCase::Revoked, "case:revoked", AuthBusError::Revoked),
        (NegativeCase::Replay, "case:replay", AuthBusError::Replay),
        (
            NegativeCase::PayloadDrift,
            "case:payload-drift",
            AuthBusError::PayloadMismatch,
        ),
    ]
    .into_iter()
    .map(|(case, id, observed)| {
        Ok(CaseEvidence {
            case,
            case_id: stable(id)?,
            rejected: true,
            evidence_digest: Digest32::of_bytes(format!("{case:?}:{observed:?}").as_bytes()),
            execution: execution.clone(),
        })
    })
    .collect::<Result<Vec<_>, Error>>()?;
    qualify(cases)
}

fn require_auth_error(
    case: NegativeCase,
    observed: Option<AuthBusError>,
    expected: AuthBusError,
) -> Result<(), Error> {
    if observed.as_ref() == Some(&expected) {
        Ok(())
    } else {
        Err(Error::NativeCaseUnexpected(format!(
            "{case:?}: expected {expected:?}, observed {observed:?}"
        )))
    }
}

fn stable(value: &str) -> Result<StableId, Error> {
    StableId::new(value).map_err(|_| Error::InvalidExecutionProvenance)
}

fn validate_execution(execution: &ExecutionProvenance) -> Result<(), Error> {
    let git_id = |value: &str| {
        value.len() == 40
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    };
    if !git_id(&execution.source_sha)
        || !git_id(&execution.source_tree)
        || execution.executable_digest.is_zero()
        || execution.command_digest.is_zero()
        || execution.started_at_ms == 0
        || execution.completed_at_ms < execution.started_at_ms
    {
        return Err(Error::InvalidExecutionProvenance);
    }
    if execution.exit_code != 0 {
        return Err(Error::ExecutionFailed(execution.exit_code));
    }
    Ok(())
}

fn case_code(value: NegativeCase) -> u8 {
    match value {
        NegativeCase::Expired => 0,
        NegativeCase::Revoked => 1,
        NegativeCase::Replay => 2,
        NegativeCase::PayloadDrift => 3,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
