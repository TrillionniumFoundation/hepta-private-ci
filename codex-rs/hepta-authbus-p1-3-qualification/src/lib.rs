//! Closed-world negative qualification for the AuthBus verifier.
//!
//! This crate is still an evidence binder, not an independent acceptance
//! authority.  It refuses evidence that is not bound to one exact source
//! candidate, one test binary and explicit execution receipts.

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
pub struct ExecutionProvenance {
    pub source_commit_sha1: String,
    pub source_tree_sha1: String,
    pub binary_digest: Digest32,
    pub command_digest: Digest32,
    pub runner_identity_digest: Digest32,
    pub execution_receipt_digest: Digest32,
    pub started_at_ms: u64,
    pub completed_at_ms: u64,
    pub exit_code: i32,
}

impl ExecutionProvenance {
    fn validate(&self) -> bool {
        lowercase_hex40(&self.source_commit_sha1)
            && lowercase_hex40(&self.source_tree_sha1)
            && !self.binary_digest.is_zero()
            && !self.command_digest.is_zero()
            && !self.runner_identity_digest.is_zero()
            && !self.execution_receipt_digest.is_zero()
            && self.started_at_ms > 0
            && self.completed_at_ms >= self.started_at_ms
            && self.exit_code == 0
    }
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
    pub source_commit_sha1: String,
    pub source_tree_sha1: String,
    pub binary_digest: Digest32,
    pub runner_identity_digest: Digest32,
    pub qualification_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    CaseLimitExceeded,
    DuplicateCase,
    MissingRequiredCase,
    CaseDidNotReject(String),
    EmptyEvidence(String),
    InvalidExecutionProvenance(String),
    CandidateMismatch(String),
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
    let required = BTreeSet::from([
        NegativeCase::Expired,
        NegativeCase::Revoked,
        NegativeCase::Replay,
        NegativeCase::PayloadDrift,
    ]);
    let first = cases.first().ok_or(Error::MissingRequiredCase)?;
    if !first.execution.validate() {
        return Err(Error::InvalidExecutionProvenance(first.case_id.to_string()));
    }
    let source_commit = first.execution.source_commit_sha1.clone();
    let source_tree = first.execution.source_tree_sha1.clone();
    let binary_digest = first.execution.binary_digest;
    let runner_identity_digest = first.execution.runner_identity_digest;

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
        if !evidence.execution.validate() {
            return Err(Error::InvalidExecutionProvenance(
                evidence.case_id.to_string(),
            ));
        }
        if evidence.execution.source_commit_sha1 != source_commit
            || evidence.execution.source_tree_sha1 != source_tree
            || evidence.execution.binary_digest != binary_digest
            || evidence.execution.runner_identity_digest != runner_identity_digest
        {
            return Err(Error::CandidateMismatch(evidence.case_id.to_string()));
        }
    }
    if seen != required {
        return Err(Error::MissingRequiredCase);
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.authbus.qualification.v2\0");
    push_text(&mut bytes, &source_commit);
    push_text(&mut bytes, &source_tree);
    bytes.extend_from_slice(binary_digest.as_array());
    bytes.extend_from_slice(runner_identity_digest.as_array());
    for evidence in &cases {
        bytes.push(case_code(evidence.case));
        push_id(&mut bytes, &evidence.case_id);
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
        bytes.extend_from_slice(evidence.execution.command_digest.as_array());
        bytes.extend_from_slice(evidence.execution.execution_receipt_digest.as_array());
        bytes.extend_from_slice(&evidence.execution.started_at_ms.to_be_bytes());
        bytes.extend_from_slice(&evidence.execution.completed_at_ms.to_be_bytes());
        bytes.extend_from_slice(&evidence.execution.exit_code.to_be_bytes());
    }
    Ok(QualificationReceipt {
        case_count: cases.len(),
        source_commit_sha1: source_commit,
        source_tree_sha1: source_tree,
        binary_digest,
        runner_identity_digest,
        qualification_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn lowercase_hex40(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
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
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
