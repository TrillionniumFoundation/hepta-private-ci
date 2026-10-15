//! Read-only binding of an original Evidence WAL frontier to separately
//! signed, freshly challenged custody. This file has NO grant/execute API.
//!
//! The local frontier must be read from the actual locked Evidence writer,
//! after full bounded WAL chain validation, by the trusted operator process.
//! The independent service MUST read its OWN rollback-resistant high-water
//! store by journal domain only. It must not sign caller-suggested counters.
//! Neither this pure verifier nor a local hash chain alone proves genuinely
//! separate signer/storage custody or permits physical CellSplit.

use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const CELL_SPLIT_EVIDENCE_CUSTODY_SCHEMA_V1: &str =
    "hepta.learning.cell-split.evidence-wal-custody.v1";

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEvidenceLocalFrontierV1 {
    pub journal_domain_id: String,
    pub sequence: u64,
    pub committed_rows: u64,
    pub head_digest: Digest32,
    pub wal_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEvidenceSignedCustodyV1 {
    pub schema: String,
    pub journal_domain_id: String,
    pub authority_epoch: u64,
    pub sequence: u64,
    pub committed_rows: u64,
    pub head_digest: Digest32,
    pub wal_bytes: u64,
    pub challenge_nonce: String,
    pub signature_bytes: Vec<u8>,
}

/// An original independent high-water owner. The read request contains ONLY
/// the deployment-pinned domain and a fresh verifier challenge. Supplying the
/// local sequence/head or an expected high-water to the remote signer would
/// create a self-confirming replay vulnerability.
pub trait CellSplitEvidenceCustodyPortV1 {
    type Error: std::fmt::Display;

    fn read_current_domain(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitEvidenceSignedCustodyV1, Self::Error>;
}

#[derive(Debug, Error)]
pub enum CellSplitEvidenceCustodyErrorV1 {
    #[error("Evidence WAL custody identity, nonce or original frontier invalid")]
    Invalid,
    #[error("Evidence WAL signer does not match separately pinned custody key")]
    Untrusted,
    #[error("independent Evidence custody source unavailable: {0}")]
    Owner(String),
    #[error(transparent)]
    Canonical(#[from] crate::AcceptanceError),
}

/// Audit-only equality verdict. It is NOT an independent runtime receipt,
/// permission to replay CAS/CNS, or positive NDU/Selector Final-use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitEvidenceCustodyComparisonV1 {
    pub journal_domain_id: String,
    pub authority_epoch: u64,
    pub sequence: u64,
    pub committed_rows: u64,
    pub head_digest: Digest32,
    pub wal_bytes: u64,
    pub signed_proof_digest: String,
    pub production_activation_authorized: bool,
}

pub fn cell_split_evidence_custody_signing_payload_v1(
    proof: &CellSplitEvidenceSignedCustodyV1,
) -> Result<Vec<u8>, CellSplitEvidenceCustodyErrorV1> {
    let mut unsigned = proof.clone();
    unsigned.signature_bytes.clear();
    let mut bytes = b"hepta.learning.cell-split.evidence-wal-custody.v1\0".to_vec();
    bytes.extend_from_slice(&crate::durable::canonical_json(&unsigned)?);
    Ok(bytes)
}

fn valid_domain(domain: &str) -> bool {
    !domain.is_empty()
        && domain.len() <= 256
        && domain.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-' | b'.' | b':' | b'/')
        })
}

/// Compare an already verified ORIGINAL local Evidence WAL frontier to fresh
/// independent high-water. The caller does not get to supply a signed proof
/// or choose the challenge nonce. This cannot prove an implementation of the
/// abstract port is independently administered; qualification requires an
/// external signer, custody key and process with distinct protected storage.
pub fn verify_cell_split_evidence_custody_v1<P: CellSplitEvidenceCustodyPortV1>(
    expected_domain: &str,
    local: &CellSplitEvidenceLocalFrontierV1,
    pinned_custody_key: &VerifyingKey,
    custody: &mut P,
) -> Result<CellSplitEvidenceCustodyComparisonV1, CellSplitEvidenceCustodyErrorV1> {
    if !valid_domain(expected_domain)
        || local.journal_domain_id != expected_domain
        || local.sequence == 0
        || local.committed_rows < local.sequence
        || local.head_digest.is_zero()
        || local.wal_bytes == 0
        || pinned_custody_key.is_weak()
    {
        return Err(CellSplitEvidenceCustodyErrorV1::Invalid);
    }
    let challenge_nonce = rand::random::<[u8; 32]>()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let proof = custody
        .read_current_domain(expected_domain, &challenge_nonce)
        .map_err(|error| CellSplitEvidenceCustodyErrorV1::Owner(error.to_string()))?;
    if proof.schema != CELL_SPLIT_EVIDENCE_CUSTODY_SCHEMA_V1
        || proof.journal_domain_id != expected_domain
        || proof.authority_epoch == 0
        || proof.challenge_nonce != challenge_nonce
        || proof.signature_bytes.len() != 64
        || proof.sequence != local.sequence
        || proof.committed_rows != local.committed_rows
        || proof.head_digest != local.head_digest
        || proof.wal_bytes != local.wal_bytes
    {
        return Err(CellSplitEvidenceCustodyErrorV1::Invalid);
    }
    let signature = Signature::from_slice(&proof.signature_bytes)
        .map_err(|_| CellSplitEvidenceCustodyErrorV1::Invalid)?;
    pinned_custody_key
        .verify_strict(
            &cell_split_evidence_custody_signing_payload_v1(&proof)?,
            &signature,
        )
        .map_err(|_| CellSplitEvidenceCustodyErrorV1::Untrusted)?;
    let signed_proof_digest = crate::durable::sha256(&crate::durable::canonical_json(&proof)?);
    Ok(CellSplitEvidenceCustodyComparisonV1 {
        journal_domain_id: expected_domain.to_owned(),
        authority_epoch: proof.authority_epoch,
        sequence: local.sequence,
        committed_rows: local.committed_rows,
        head_digest: local.head_digest,
        wal_bytes: local.wal_bytes,
        signed_proof_digest,
        production_activation_authorized: false,
    })
}

#[cfg(test)]
#[path = "cell_split_evidence_custody_tests.rs"]
mod tests;
