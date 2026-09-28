//! Executable, closed-world qualification primitives for AuthBus.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_authbus::PrivateIssuerRegistryDocument;
use codex_hepta_authbus::VerificationReceipt;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_CASES: usize = 64;

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
pub struct QualificationReceipt {
    pub case_count: usize,
    pub qualification_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum AuthorityCase {
    ForgedKey,
    RevokedKey,
    EpochSubstitution,
    PurposeSubstitution,
    FakeQuarantine,
    OwnerCollision,
    ExpiredReservationSweep,
    ProductSettlement,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityCaseEvidence {
    pub case: AuthorityCase,
    pub case_id: StableId,
    pub rejected_or_verified: bool,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityQualificationReceipt {
    pub case_count: usize,
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

/// Legacy replay-only qualification retained for compatibility. Activation
/// decisions must additionally require `qualify_authority`.
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
    bytes.extend_from_slice(b"hepta.authbus.qualification.v1");
    for evidence in &cases {
        bytes.push(legacy_case_code(evidence.case));
        push_id(&mut bytes, &evidence.case_id);
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
    }
    Ok(QualificationReceipt {
        case_count: cases.len(),
        qualification_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn qualify_authority(
    mut cases: Vec<AuthorityCaseEvidence>,
) -> Result<AuthorityQualificationReceipt, Error> {
    if cases.len() > MAX_CASES {
        return Err(Error::CaseLimitExceeded);
    }
    cases.sort_by(|left, right| {
        left.case
            .cmp(&right.case)
            .then_with(|| left.case_id.cmp(&right.case_id))
    });
    let required = BTreeSet::from([
        AuthorityCase::ForgedKey,
        AuthorityCase::RevokedKey,
        AuthorityCase::EpochSubstitution,
        AuthorityCase::PurposeSubstitution,
        AuthorityCase::FakeQuarantine,
        AuthorityCase::OwnerCollision,
        AuthorityCase::ExpiredReservationSweep,
        AuthorityCase::ProductSettlement,
    ]);
    let mut seen = BTreeSet::new();
    for evidence in &cases {
        if !seen.insert(evidence.case) {
            return Err(Error::DuplicateCase);
        }
        if !evidence.rejected_or_verified {
            return Err(Error::CaseDidNotReject(evidence.case_id.to_string()));
        }
        if evidence.evidence_digest.is_zero() {
            return Err(Error::EmptyEvidence(evidence.case_id.to_string()));
        }
    }
    if seen != required {
        return Err(Error::MissingRequiredCase);
    }
    let mut bytes = b"hepta.authbus.authority-qualification.v2\0".to_vec();
    for evidence in &cases {
        bytes.push(authority_case_code(evidence.case));
        push_id(&mut bytes, &evidence.case_id);
        bytes.extend_from_slice(evidence.evidence_digest.as_array());
    }
    Ok(AuthorityQualificationReceipt {
        case_count: cases.len(),
        qualification_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Test and qualification helper that still exercises the production private-
/// registry loader. It does not bypass opaque registration construction.
pub fn persisted_message_issuer(
    issuer_id: &str,
    key_epoch: u64,
    public_key: [u8; 32],
    revoked: bool,
) -> Result<IssuerRegistration, String> {
    #[cfg(not(unix))]
    {
        let _ = (issuer_id, key_epoch, public_key, revoked);
        return Err("private issuer qualification requires Unix ownership checks".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        let root = tempfile::tempdir().map_err(|error| error.to_string())?;
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))
            .map_err(|error| error.to_string())?;
        let path = root.path().join("issuer-registry.json");
        let key_hex = public_key
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let document = serde_json::json!({
            "schema_version": 1,
            "issuer_id": issuer_id,
            "key_epoch": key_epoch,
            "public_key_hex": key_hex,
            "revoked": revoked,
            "thread_ids": ["qualification"]
        });
        std::fs::write(
            &path,
            serde_json::to_vec(&document).map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .map_err(|error| error.to_string())?;
        let registry = PrivateIssuerRegistryDocument::load(&path, root.path(), 16_384)
            .map_err(|error| error.to_string())?;
        registry
            .message_issuer(
                &StableId::new(issuer_id).map_err(|error| error.to_string())?,
                Generation::new(key_epoch).map_err(|error| error.to_string())?,
            )
            .map_err(|error| error.to_string())
    }
}

fn legacy_case_code(value: NegativeCase) -> u8 {
    match value {
        NegativeCase::Expired => 0,
        NegativeCase::Revoked => 1,
        NegativeCase::Replay => 2,
        NegativeCase::PayloadDrift => 3,
    }
}

fn authority_case_code(value: AuthorityCase) -> u8 {
    match value {
        AuthorityCase::ForgedKey => 0,
        AuthorityCase::RevokedKey => 1,
        AuthorityCase::EpochSubstitution => 2,
        AuthorityCase::PurposeSubstitution => 3,
        AuthorityCase::FakeQuarantine => 4,
        AuthorityCase::OwnerCollision => 5,
        AuthorityCase::ExpiredReservationSweep => 6,
        AuthorityCase::ProductSettlement => 7,
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
