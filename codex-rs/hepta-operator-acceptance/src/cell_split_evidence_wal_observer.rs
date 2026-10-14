//! Verification-only join of the original Evidence WAL and an independently
//! administered, separately signed high-water store.
//!
//! The local readback MUST come from the original Evidence-owned group-commit
//! writer (not a caller-built digest), and the remote observer MUST obtain its
//! current domain from its own durable/custodied state. Neither this module
//! nor its result issues Final-use, starts a CellSplit, or signs anything.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const CELL_SPLIT_EVIDENCE_WAL_OBSERVER_SCHEMA_V1: &str =
    "hepta.learning.cell-split.evidence-wal-observer.v1";
const SIGNING_DOMAIN: &[u8] = b"hepta.learning.cell-split.evidence-wal-observer.v1\0";

/// Exact projection of MetricsOriginalLocalFrontierV1. A production adapter
/// must fetch these four fields from DurablePhaseMetricSinkV1's original
/// local_original_frontier(), which fsyncs and rereads its original WAL.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEvidenceWalLocalFrontierV1 {
    pub sequence: u64,
    pub committed_rows: u64,
    pub head_digest: String,
    pub wal_bytes: u64,
}

/// No expected revision, head or candidate proof may be supplied to this
/// local interface. No default or fallback implementation grants readiness.
pub trait CellSplitEvidenceWalOriginalOwnerReadV1 {
    type Error: std::fmt::Display;

    fn read_original_durable_frontier(
        &mut self,
        journal_domain_id: &str,
    ) -> Result<CellSplitEvidenceWalLocalFrontierV1, Self::Error>;
}

/// Independently owned and challenged high-water mark. A signed *historical*
/// record or self-signed local JSON is insufficient: the remote implementation
/// must read its separate monotonic custody by domain at query time.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellSplitEvidenceWalObserverProofV1 {
    pub schema: String,
    pub journal_domain_id: String,
    pub authority_epoch: u64,
    pub challenge_nonce: String,
    pub sequence: u64,
    pub committed_rows: u64,
    pub head_digest: String,
    pub wal_bytes: u64,
    pub signature_bytes: Vec<u8>,
}

/// The remote port receives ONLY an externally pinned domain and fresh random
/// challenge. Passing the candidate's desired sequence/head would let an old
/// restored registry generate a self-confirming signed response.
pub trait CellSplitEvidenceWalIndependentObserverV1 {
    type Error: std::fmt::Display;

    fn read_current(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitEvidenceWalObserverProofV1, Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitEvidenceWalWitnessedReadbackV1 {
    pub local: CellSplitEvidenceWalLocalFrontierV1,
    pub observer_proof: CellSplitEvidenceWalObserverProofV1,
    /// Auditable hash of the independently signed, domain-separated payload.
    /// This digest is *not* authority or an alternative to its signature.
    pub witnessed_payload_digest: Digest32,
}

#[derive(Debug, Error)]
pub enum CellSplitEvidenceWalObserverErrorV1 {
    #[error("Evidence WAL observer proof is invalid or not current")]
    Invalid,
    #[error("Evidence WAL observer signature is untrusted")]
    Untrusted,
    #[error("original Evidence WAL and independent custody frontier disagree")]
    Stale,
    #[error("original Evidence WAL owner unavailable: {0}")]
    Owner(String),
    #[error("independent Evidence WAL observer unavailable: {0}")]
    Observer(String),
}

/// Only test/external independent custody may sign these canonical bytes.
/// Clearing the signature field avoids signing a mutable self-referential
/// envelope; the v1 domain prefix prevents cross-protocol signature reuse.
pub fn cell_split_evidence_wal_observer_signing_payload_v1(
    proof: &CellSplitEvidenceWalObserverProofV1,
) -> Result<Vec<u8>, CellSplitEvidenceWalObserverErrorV1> {
    let mut unsigned = proof.clone();
    unsigned.signature_bytes.clear();
    let mut bytes = SIGNING_DOMAIN.to_vec();
    bytes.extend_from_slice(
        &serde_json::to_vec(&unsigned).map_err(|_| CellSplitEvidenceWalObserverErrorV1::Invalid)?,
    );
    Ok(bytes)
}

fn canonical_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        && value.bytes().any(|byte| byte != b'0')
}

fn valid_local(frontier: &CellSplitEvidenceWalLocalFrontierV1) -> bool {
    frontier.sequence != 0
        && frontier.committed_rows >= frontier.sequence
        && frontier.wal_bytes != 0
        && canonical_digest(&frontier.head_digest)
}

/// A successful result is read-only qualified evidence, never a production
/// activation grant. The deployment must independently pin the observer key,
/// ensure its owner differs from the Evidence writer and original effect
/// signers, and enforce actual rollback-resistant external custody.
///
/// Two *original* local reads bracket the independently challenged signature.
/// A replacement, truncation, raced write, unavailable custody or stale
/// remote high-water fails closed. This verifier cannot itself establish
/// genuine organizational separation or remote disk anti-rollback.
pub fn verify_cell_split_evidence_wal_observer_v1<
    L: CellSplitEvidenceWalOriginalOwnerReadV1,
    O: CellSplitEvidenceWalIndependentObserverV1,
>(
    journal_domain_id: &str,
    original: &mut L,
    observer: &mut O,
    pinned_observer_key: &VerifyingKey,
) -> Result<CellSplitEvidenceWalWitnessedReadbackV1, CellSplitEvidenceWalObserverErrorV1> {
    if journal_domain_id.is_empty()
        || journal_domain_id.len() > 256
        || StableId::new(journal_domain_id.to_owned()).is_err()
        || pinned_observer_key.is_weak()
    {
        return Err(CellSplitEvidenceWalObserverErrorV1::Invalid);
    }
    let before = original
        .read_original_durable_frontier(journal_domain_id)
        .map_err(|error| CellSplitEvidenceWalObserverErrorV1::Owner(error.to_string()))?;
    if !valid_local(&before) {
        return Err(CellSplitEvidenceWalObserverErrorV1::Invalid);
    }
    let challenge_nonce = rand::random::<[u8; 32]>()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let proof = observer
        .read_current(journal_domain_id, &challenge_nonce)
        .map_err(|error| CellSplitEvidenceWalObserverErrorV1::Observer(error.to_string()))?;
    if proof.schema != CELL_SPLIT_EVIDENCE_WAL_OBSERVER_SCHEMA_V1
        || proof.journal_domain_id != journal_domain_id
        || proof.authority_epoch == 0
        || proof.challenge_nonce != challenge_nonce
        || !canonical_digest(&proof.head_digest)
        || proof.sequence == 0
        || proof.committed_rows < proof.sequence
        || proof.wal_bytes == 0
        || proof.signature_bytes.len() != 64
    {
        return Err(CellSplitEvidenceWalObserverErrorV1::Invalid);
    }
    let payload = cell_split_evidence_wal_observer_signing_payload_v1(&proof)?;
    let signature = Signature::from_slice(&proof.signature_bytes)
        .map_err(|_| CellSplitEvidenceWalObserverErrorV1::Invalid)?;
    pinned_observer_key
        .verify_strict(&payload, &signature)
        .map_err(|_| CellSplitEvidenceWalObserverErrorV1::Untrusted)?;
    let after = original
        .read_original_durable_frontier(journal_domain_id)
        .map_err(|error| CellSplitEvidenceWalObserverErrorV1::Owner(error.to_string()))?;
    if !valid_local(&after)
        || before != after
        || proof.sequence != after.sequence
        || proof.committed_rows != after.committed_rows
        || proof.head_digest != after.head_digest
        || proof.wal_bytes != after.wal_bytes
    {
        return Err(CellSplitEvidenceWalObserverErrorV1::Stale);
    }
    Ok(CellSplitEvidenceWalWitnessedReadbackV1 {
        local: after,
        observer_proof: proof,
        witnessed_payload_digest: Digest32::of_bytes(&payload),
    })
}

#[cfg(test)]
#[path = "cell_split_evidence_wal_observer_tests.rs"]
mod tests;
