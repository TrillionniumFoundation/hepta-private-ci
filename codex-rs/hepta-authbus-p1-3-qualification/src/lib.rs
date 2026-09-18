//! Closed-world negative qualification for the AuthBus verifier.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_authbus::VerificationReceipt;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_CASES: usize = 32;

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
    pub rejected: bool,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionProvenance {
    pub source_sha: String,
    pub source_tree: String,
    pub binary_digest: Digest32,
    pub runner_id: StableId,
    pub command_digest: Digest32,
    pub exit_code: i32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationReceipt {
    pub case_count: usize,
    pub qualification_digest: Digest32,
    pub provenance_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    CaseLimitExceeded,
    DuplicateCase,
    MissingRequiredCase,
    CaseDidNotReject(String),
    EmptyEvidence(String),
    PositiveReceiptGrantedAuthority,
    InvalidExecutionProvenance,
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

pub fn qualify(
    mut cases: Vec<CaseEvidence>,
    provenance: ExecutionProvenance,
) -> Result<QualificationReceipt, Error> {
    let provenance_digest = validate_provenance(&provenance)?;
    if cases.len() > MAX_CASES {
        return Err(Error::CaseLimitExceeded);
    }
    cases.sort_by(|left, right| {
        left.case
            .cmp(&right.case)
            .then_with(|| left.case_id.cmp(&right.case_id))
    });
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
    bytes.extend_from_slice(b"hepta.authbus.qualification.v2");
    bytes.extend_from_slice(provenance_digest.as_array());
    for evidence in &cases {
        bytes.push(case_code(evidence.case));
        push_id(&mut bytes, &evidence.case_id);
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
    }
    Ok(QualificationReceipt {
        case_count: cases.len(),
        qualification_digest: Digest32::of_bytes(&bytes),
        provenance_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}


fn validate_provenance(value: &ExecutionProvenance) -> Result<Digest32, Error> {
    let hex40 = |value: &str| {
        value.len() == 40 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
    };
    if !hex40(&value.source_sha)
        || !hex40(&value.source_tree)
        || value.binary_digest.is_zero()
        || value.command_digest.is_zero()
        || value.exit_code != 0
    {
        return Err(Error::InvalidExecutionProvenance);
    }
    let mut bytes = b"hepta.authbus.execution-provenance.v1\0".to_vec();
    bytes.extend_from_slice(value.source_sha.as_bytes());
    bytes.extend_from_slice(value.source_tree.as_bytes());
    bytes.extend_from_slice(value.binary_digest.as_array());
    push_id(&mut bytes, &value.runner_id);
    bytes.extend_from_slice(value.command_digest.as_array());
    bytes.extend_from_slice(&value.exit_code.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn case_code(value: NegativeCase) -> u8 {
    match value {
        NegativeCase::Expired => 0,
        NegativeCase::Revoked => 1,
        NegativeCase::Replay => 2,
        NegativeCase::PayloadDrift => 3,
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
