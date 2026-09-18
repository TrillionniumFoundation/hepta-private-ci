//! Self-describing dataset-freeze receipt layered over the stable V2 snapshot.
//!
//! `DatasetSnapshotV2` is retained for source compatibility. This envelope keeps
//! every semantic field in the V2 digest preimage so a downstream consumer can
//! independently recompute the dataset identity instead of trusting an opaque
//! digest supplied by the producer.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AuthenticatedPrincipalV1;
use crate::CausalV2Error;
use crate::DatasetFreezeRequestV1;
use crate::DatasetSnapshotV2;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::freeze_dataset;

const MAX_DATASET_RECORDS: usize = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetSnapshotReceiptV3 {
    pub snapshot: DatasetSnapshotV2,
    pub producer: AuthenticatedPrincipalV1,
    pub correction_cut_digest: Digest32,
    pub revocation_cut_digest: Digest32,
    pub inclusion_policy_digest: Digest32,
}

pub fn freeze_dataset_receipt_v3(
    request: DatasetFreezeRequestV1,
    now: u64,
) -> Result<DatasetSnapshotReceiptV3, DatasetReceiptError> {
    let producer = request.producer.clone();
    let correction_cut_digest = request.correction_cut_digest;
    let revocation_cut_digest = request.revocation_cut_digest;
    let inclusion_policy_digest = request.inclusion_policy_digest;
    let snapshot = freeze_dataset(request, now)?;
    let receipt = DatasetSnapshotReceiptV3 {
        snapshot,
        producer,
        correction_cut_digest,
        revocation_cut_digest,
        inclusion_policy_digest,
    };
    verify_dataset_snapshot_receipt_v3(&receipt, now)?;
    Ok(receipt)
}

/// Production-oriented freeze path. The caller supplies policy/cut metadata, but
/// cannot choose the ledger head or source-record membership. Membership is
/// derived from the authoritative snapshot after replaying all ledger invariants
/// and applying revocation lineage. Revocation control records are not training
/// source rows and are therefore excluded from the derived source set.
pub fn freeze_dataset_receipt_from_ledger_v3(
    mut request: DatasetFreezeRequestV1,
    ledger_snapshot: &LedgerSnapshot,
    now: u64,
) -> Result<DatasetSnapshotReceiptV3, DatasetReceiptError> {
    request.ledger_head_digest = ledger_snapshot.head_digest;
    request.source_record_digests =
        derive_active_source_digests(ledger_snapshot, request.eligible_frontier)?;
    freeze_dataset_receipt_v3(request, now)
}

pub fn verify_dataset_snapshot_receipt_v3(
    receipt: &DatasetSnapshotReceiptV3,
    now: u64,
) -> Result<(), DatasetReceiptError> {
    receipt.producer.validate(now)?;
    if receipt.snapshot.authority != AuthorityPosture::DENY_ALL {
        return Err(DatasetReceiptError::AuthorityGrant);
    }
    for (label, digest) in [
        ("ledger head", receipt.snapshot.ledger_head_digest),
        ("objective", receipt.snapshot.objective_digest),
        ("correction cut", receipt.correction_cut_digest),
        ("revocation cut", receipt.revocation_cut_digest),
        ("inclusion policy", receipt.inclusion_policy_digest),
    ] {
        require_digest(digest, label)?;
    }
    if receipt.snapshot.eligible_frontier == 0 || receipt.snapshot.outcome_watermark == 0 {
        return Err(DatasetReceiptError::InvalidFrontier);
    }
    if receipt.snapshot.source_record_digests.is_empty()
        || receipt.snapshot.source_record_digests.len() > MAX_DATASET_RECORDS
    {
        return Err(DatasetReceiptError::RecordLimit);
    }
    if receipt
        .snapshot
        .source_record_digests
        .iter()
        .any(|digest| digest.is_zero())
    {
        return Err(DatasetReceiptError::EmptyDigest("dataset source record"));
    }
    if receipt
        .snapshot
        .source_record_digests
        .windows(2)
        .any(|adjacent| adjacent[0] >= adjacent[1])
    {
        return Err(DatasetReceiptError::NonCanonicalRecords);
    }

    let expected = digest_receipt(receipt)?;
    if expected != receipt.snapshot.dataset_digest {
        return Err(DatasetReceiptError::DigestMismatch);
    }
    Ok(())
}

/// Bind an already-issued receipt back to the authoritative ledger snapshot and
/// reject omission, insertion, stale-head or revoked-row resurrection.
pub fn verify_dataset_snapshot_receipt_against_ledger_v3(
    receipt: &DatasetSnapshotReceiptV3,
    ledger_snapshot: &LedgerSnapshot,
    now: u64,
) -> Result<(), DatasetReceiptError> {
    verify_dataset_snapshot_receipt_v3(receipt, now)?;
    if receipt.snapshot.ledger_head_digest != ledger_snapshot.head_digest {
        return Err(DatasetReceiptError::LedgerHeadMismatch);
    }
    let expected =
        derive_active_source_digests(ledger_snapshot, receipt.snapshot.eligible_frontier)?;
    if receipt.snapshot.source_record_digests != expected {
        return Err(DatasetReceiptError::LedgerSourceSetMismatch);
    }
    Ok(())
}

fn derive_active_source_digests(
    snapshot: &LedgerSnapshot,
    eligible_frontier: u64,
) -> Result<Vec<Digest32>, DatasetReceiptError> {
    if eligible_frontier == 0 {
        return Err(DatasetReceiptError::InvalidFrontier);
    }
    let head_sequence = snapshot
        .records()
        .last()
        .map_or(0, |record| record.sequence.get());
    if eligible_frontier > head_sequence {
        return Err(DatasetReceiptError::InvalidFrontier);
    }
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let mut digests = ledger
        .active_records()
        .into_iter()
        .filter(|record| record.sequence.get() <= eligible_frontier)
        .filter(|record| !matches!(record.event, LedgerEvent::Revocation(_)))
        .map(|record| record.event_digest)
        .collect::<Vec<_>>();
    digests.sort_unstable();
    digests.dedup();
    if digests.is_empty() {
        return Err(DatasetReceiptError::RecordLimit);
    }
    if digests.len() > MAX_DATASET_RECORDS {
        return Err(DatasetReceiptError::RecordLimit);
    }
    Ok(digests)
}

fn digest_receipt(receipt: &DatasetSnapshotReceiptV3) -> Result<Digest32, DatasetReceiptError> {
    let snapshot = &receipt.snapshot;
    let mut bytes = b"hepta.learning-ledger.dataset-snapshot.v2".to_vec();
    push_id(&mut bytes, &snapshot.snapshot_id)?;
    push_principal(&mut bytes, &receipt.producer)?;
    bytes.extend_from_slice(snapshot.ledger_head_digest.as_array());
    bytes.extend_from_slice(snapshot.objective_digest.as_array());
    bytes.extend_from_slice(&snapshot.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&snapshot.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(receipt.correction_cut_digest.as_array());
    bytes.extend_from_slice(receipt.revocation_cut_digest.as_array());
    bytes.extend_from_slice(receipt.inclusion_policy_digest.as_array());
    bytes.extend_from_slice(
        &u64::try_from(snapshot.source_record_digests.len())
            .map_err(|_| DatasetReceiptError::Arithmetic)?
            .to_be_bytes(),
    );
    for digest in &snapshot.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&snapshot.pending_outcomes.to_be_bytes());
    bytes.extend_from_slice(&snapshot.censored_outcomes.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_principal(
    bytes: &mut Vec<u8>,
    principal: &AuthenticatedPrincipalV1,
) -> Result<(), DatasetReceiptError> {
    push_id(bytes, &principal.principal_id)?;
    bytes.extend_from_slice(principal.credential_chain_digest.as_array());
    bytes.extend_from_slice(principal.signing_key_digest.as_array());
    bytes.extend_from_slice(principal.scope_digest.as_array());
    bytes.extend_from_slice(&principal.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&principal.authenticated_at.to_be_bytes());
    bytes.extend_from_slice(&principal.expires_at.to_be_bytes());
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), DatasetReceiptError> {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(
        &u32::try_from(raw.len())
            .map_err(|_| DatasetReceiptError::Arithmetic)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(raw);
    Ok(())
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), DatasetReceiptError> {
    if digest.is_zero() {
        return Err(DatasetReceiptError::EmptyDigest(label));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DatasetReceiptError {
    Causal(CausalV2Error),
    Ledger(LedgerError),
    EmptyDigest(&'static str),
    AuthorityGrant,
    InvalidFrontier,
    RecordLimit,
    NonCanonicalRecords,
    DigestMismatch,
    LedgerHeadMismatch,
    LedgerSourceSetMismatch,
    Arithmetic,
}

impl fmt::Display for DatasetReceiptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DatasetReceiptError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Causal(error) => Some(error),
            Self::Ledger(error) => Some(error),
            Self::EmptyDigest(_)
            | Self::AuthorityGrant
            | Self::InvalidFrontier
            | Self::RecordLimit
            | Self::NonCanonicalRecords
            | Self::DigestMismatch
            | Self::LedgerHeadMismatch
            | Self::LedgerSourceSetMismatch
            | Self::Arithmetic => None,
        }
    }
}

impl From<CausalV2Error> for DatasetReceiptError {
    fn from(value: CausalV2Error) -> Self {
        Self::Causal(value)
    }
}

impl From<LedgerError> for DatasetReceiptError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CandidateSetCompleteness;
    use crate::EpisodeDecision;
    use crate::LedgerEvent;
    use crate::Revocation;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn actor() -> AuthenticatedPrincipalV1 {
        AuthenticatedPrincipalV1 {
            principal_id: id("dataset-owner"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            scope_digest: digest("scope"),
            authority_epoch: 9,
            authenticated_at: 10,
            expires_at: 100,
        }
    }

    fn request() -> DatasetFreezeRequestV1 {
        DatasetFreezeRequestV1 {
            snapshot_id: id("snapshot-v3"),
            producer: actor(),
            ledger_head_digest: digest("ledger-head"),
            objective_digest: digest("objective"),
            eligible_frontier: 7,
            outcome_watermark: 50,
            correction_cut_digest: digest("correction-cut"),
            revocation_cut_digest: digest("revocation-cut"),
            inclusion_policy_digest: digest("policy"),
            source_record_digests: vec![digest("record-b"), digest("record-a")],
            pending_outcomes: 1,
            censored_outcomes: 2,
        }
    }

    fn decision(record: &str, episode: &str) -> LedgerEvent {
        LedgerEvent::Decision(EpisodeDecision {
            record_id: id(record),
            episode_id: id(episode),
            objective_digest: digest("objective"),
            policy_id: id("policy"),
            candidate_ids: vec![id("choice"), id("abstain")],
            selected_candidate_id: id("choice"),
            selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("support"),
        })
    }

    #[test]
    fn ledger_05_dataset_receipt_is_self_verifying() {
        let receipt = freeze_dataset_receipt_v3(request(), 60).expect("valid receipt");
        verify_dataset_snapshot_receipt_v3(&receipt, 60).expect("receipt verifies");
        assert_eq!(receipt.snapshot.pending_outcomes, 1);
        assert_eq!(receipt.snapshot.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn ledger_05_dataset_receipt_rejects_semantic_field_drift() {
        let mut receipt = freeze_dataset_receipt_v3(request(), 60).expect("valid receipt");
        receipt.correction_cut_digest = digest("changed-cut");
        assert_eq!(
            verify_dataset_snapshot_receipt_v3(&receipt, 60),
            Err(DatasetReceiptError::DigestMismatch)
        );
    }

    #[test]
    fn ledger_06_dataset_membership_is_derived_from_active_ledger() {
        let mut ledger = LearningLedger::new();
        ledger
            .append(decision("decision-a", "episode-a"))
            .expect("decision a");
        ledger
            .append(decision("decision-b", "episode-b"))
            .expect("decision b");
        ledger
            .append(LedgerEvent::Revocation(Revocation {
                record_id: id("revoke-a"),
                target_record_id: id("decision-a"),
                authority_id: id("privacy-owner"),
                reason_digest: digest("reason"),
            }))
            .expect("revoke");
        let snapshot = ledger.snapshot();
        let mut freeze = request();
        freeze.eligible_frontier = 3;
        freeze.source_record_digests = vec![digest("caller-cannot-select-this")];
        let receipt = freeze_dataset_receipt_from_ledger_v3(freeze, &snapshot, 60)
            .expect("ledger-derived freeze");
        verify_dataset_snapshot_receipt_against_ledger_v3(&receipt, &snapshot, 60)
            .expect("ledger-bound receipt");
        assert_eq!(receipt.snapshot.source_record_digests.len(), 1);
        assert_eq!(receipt.snapshot.ledger_head_digest, snapshot.head_digest);

        let mut tampered = receipt.clone();
        tampered
            .snapshot
            .source_record_digests
            .push(digest("injected"));
        tampered.snapshot.source_record_digests.sort_unstable();
        assert!(
            verify_dataset_snapshot_receipt_against_ledger_v3(&tampered, &snapshot, 60).is_err()
        );
    }

    #[test]
    fn fixed_q32_dependency_remains_linked_for_dataset_receipts() {
        assert_eq!(FixedQ32::ZERO.raw(), 0);
    }
}
