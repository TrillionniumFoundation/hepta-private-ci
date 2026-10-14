use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

use super::*;

const DOMAIN: &str = "scope.evidence.metrics";

fn trusted_signer() -> SigningKey {
    SigningKey::from_bytes(&[71_u8; 32])
}

fn frontier(sequence: u64) -> CellSplitEvidenceWalLocalFrontierV1 {
    CellSplitEvidenceWalLocalFrontierV1 {
        sequence,
        committed_rows: sequence * 2,
        head_digest: Digest32::of_bytes(format!("original-wal-head-{sequence}").as_bytes())
            .to_string(),
        wal_bytes: sequence * 200,
    }
}

#[derive(Debug)]
struct OriginalFixture {
    current: CellSplitEvidenceWalLocalFrontierV1,
    changed_after_first: Option<CellSplitEvidenceWalLocalFrontierV1>,
    reads: usize,
}

impl OriginalFixture {
    fn new(current: CellSplitEvidenceWalLocalFrontierV1) -> Self {
        Self {
            current,
            changed_after_first: None,
            reads: 0,
        }
    }
}

impl CellSplitEvidenceWalOriginalOwnerReadV1 for OriginalFixture {
    type Error = &'static str;

    fn read_original_durable_frontier(
        &mut self,
        domain: &str,
    ) -> Result<CellSplitEvidenceWalLocalFrontierV1, Self::Error> {
        if domain != DOMAIN {
            return Err("not the original journal domain");
        }
        self.reads += 1;
        Ok(if self.reads > 1 {
            self.changed_after_first
                .clone()
                .unwrap_or_else(|| self.current.clone())
        } else {
            self.current.clone()
        })
    }
}

#[derive(Clone, Copy, Debug)]
enum ObserverFault {
    None,
    Older,
    Newer,
    WrongDomain,
    WrongChallenge,
    WrongSigner,
    MissingCustody,
    InvalidSignature,
}

#[derive(Debug)]
struct IndependentFixture {
    retained: CellSplitEvidenceWalLocalFrontierV1,
    fault: ObserverFault,
    reads: usize,
    seen_domain: Option<String>,
    seen_nonce: Option<String>,
}

impl IndependentFixture {
    fn new(retained: CellSplitEvidenceWalLocalFrontierV1, fault: ObserverFault) -> Self {
        Self {
            retained,
            fault,
            reads: 0,
            seen_domain: None,
            seen_nonce: None,
        }
    }
}

impl CellSplitEvidenceWalIndependentObserverV1 for IndependentFixture {
    type Error = &'static str;

    fn read_current(
        &mut self,
        domain: &str,
        nonce: &str,
    ) -> Result<CellSplitEvidenceWalObserverProofV1, Self::Error> {
        self.reads += 1;
        self.seen_domain = Some(domain.to_owned());
        self.seen_nonce = Some(nonce.to_owned());
        if matches!(self.fault, ObserverFault::MissingCustody) {
            return Err("external custody missing");
        }
        let current = match self.fault {
            ObserverFault::Older => frontier(self.retained.sequence - 1),
            ObserverFault::Newer => frontier(self.retained.sequence + 1),
            _ => self.retained.clone(),
        };
        let mut proof = CellSplitEvidenceWalObserverProofV1 {
            schema: CELL_SPLIT_EVIDENCE_WAL_OBSERVER_SCHEMA_V1.to_owned(),
            journal_domain_id: if matches!(self.fault, ObserverFault::WrongDomain) {
                "foreign.metrics".to_owned()
            } else {
                domain.to_owned()
            },
            authority_epoch: 3,
            challenge_nonce: if matches!(self.fault, ObserverFault::WrongChallenge) {
                "aa".repeat(32)
            } else {
                nonce.to_owned()
            },
            sequence: current.sequence,
            committed_rows: current.committed_rows,
            head_digest: current.head_digest,
            wal_bytes: current.wal_bytes,
            signature_bytes: Vec::new(),
        };
        let signer = if matches!(self.fault, ObserverFault::WrongSigner) {
            SigningKey::from_bytes(&[72_u8; 32])
        } else {
            trusted_signer()
        };
        proof.signature_bytes = signer
            .sign(
                &cell_split_evidence_wal_observer_signing_payload_v1(&proof)
                    .expect("canonical observer payload"),
            )
            .to_bytes()
            .to_vec();
        if matches!(self.fault, ObserverFault::InvalidSignature) {
            proof.signature_bytes[0] ^= 0x01;
        }
        Ok(proof)
    }
}

#[test]
fn signed_highwater_matches_two_original_local_reads_under_fresh_challenge() {
    let durable = frontier(3);
    let mut owner = OriginalFixture::new(durable.clone());
    let mut remote = IndependentFixture::new(durable.clone(), ObserverFault::None);
    let verified = verify_cell_split_evidence_wal_observer_v1(
        DOMAIN,
        &mut owner,
        &mut remote,
        &trusted_signer().verifying_key(),
    )
    .expect("original and independent stores agree");
    assert_eq!(verified.local, durable);
    assert_eq!(verified.observer_proof.sequence, 3);
    assert!(!verified.witnessed_payload_digest.is_zero());
    assert_eq!(owner.reads, 2, "readback must bracket the remote signature");
    assert_eq!(remote.reads, 1);
    assert_eq!(remote.seen_domain.as_deref(), Some(DOMAIN));
    let nonce = remote.seen_nonce.expect("client-generated nonce");
    assert_eq!(nonce.len(), 64);
    assert!(canonical_digest(&nonce));
    assert_eq!(verified.observer_proof.challenge_nonce, nonce);
}

#[test]
fn unsigned_empty_or_uncommitted_local_wal_never_queries_observer() {
    for source in [frontier(0), CellSplitEvidenceWalLocalFrontierV1 {
        sequence: 2,
        committed_rows: 1,
        head_digest: Digest32::of_bytes(b"corrupt").to_string(),
        wal_bytes: 500,
    }] {
        let mut owner = OriginalFixture::new(source);
        let mut remote = IndependentFixture::new(frontier(3), ObserverFault::None);
        assert!(matches!(
            verify_cell_split_evidence_wal_observer_v1(
                DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
            ),
            Err(CellSplitEvidenceWalObserverErrorV1::Invalid)
        ));
        assert_eq!(remote.reads, 0);
    }
}

#[test]
fn signed_older_or_newer_highwater_cannot_certify_original_wal() {
    for fault in [ObserverFault::Older, ObserverFault::Newer] {
        let durable = frontier(3);
        let mut owner = OriginalFixture::new(durable.clone());
        let mut remote = IndependentFixture::new(durable, fault);
        assert!(matches!(
            verify_cell_split_evidence_wal_observer_v1(
                DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
            ),
            Err(CellSplitEvidenceWalObserverErrorV1::Stale)
        ));
    }
}

#[test]
fn signed_foreign_domain_or_replayed_nonce_cannot_self_confirm() {
    for fault in [ObserverFault::WrongDomain, ObserverFault::WrongChallenge] {
        let durable = frontier(3);
        let mut owner = OriginalFixture::new(durable.clone());
        let mut remote = IndependentFixture::new(durable, fault);
        assert!(matches!(
            verify_cell_split_evidence_wal_observer_v1(
                DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
            ),
            Err(CellSplitEvidenceWalObserverErrorV1::Invalid)
        ));
    }
}

#[test]
fn untrusted_signatures_and_missing_independent_custody_fail_closed() {
    for fault in [ObserverFault::WrongSigner, ObserverFault::InvalidSignature] {
        let durable = frontier(3);
        let mut owner = OriginalFixture::new(durable.clone());
        let mut remote = IndependentFixture::new(durable, fault);
        assert!(matches!(
            verify_cell_split_evidence_wal_observer_v1(
                DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
            ),
            Err(CellSplitEvidenceWalObserverErrorV1::Untrusted)
        ));
    }
    let mut owner = OriginalFixture::new(frontier(3));
    let mut remote = IndependentFixture::new(frontier(3), ObserverFault::MissingCustody);
    assert!(matches!(
        verify_cell_split_evidence_wal_observer_v1(
            DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
        ),
        Err(CellSplitEvidenceWalObserverErrorV1::Observer(_))
    ));
}

#[test]
fn original_wal_change_during_independent_signed_query_is_rejected() {
    let initial = frontier(3);
    let mut owner = OriginalFixture::new(initial.clone());
    owner.changed_after_first = Some(frontier(4));
    let mut remote = IndependentFixture::new(initial, ObserverFault::None);
    assert!(matches!(
        verify_cell_split_evidence_wal_observer_v1(
            DOMAIN, &mut owner, &mut remote, &trusted_signer().verifying_key()
        ),
        Err(CellSplitEvidenceWalObserverErrorV1::Stale)
    ));
    assert_eq!(owner.reads, 2);
}

#[test]
fn weak_or_unpinned_observer_identity_never_reaches_original_owner() {
    let mut owner = OriginalFixture::new(frontier(3));
    let mut remote = IndependentFixture::new(frontier(3), ObserverFault::None);
    let invalid_domain = "../untrusted/path";
    assert!(matches!(
        verify_cell_split_evidence_wal_observer_v1(
            invalid_domain, &mut owner, &mut remote, &trusted_signer().verifying_key()
        ),
        Err(CellSplitEvidenceWalObserverErrorV1::Invalid)
    ));
    assert_eq!(owner.reads, 0);
    assert_eq!(remote.reads, 0);
}
