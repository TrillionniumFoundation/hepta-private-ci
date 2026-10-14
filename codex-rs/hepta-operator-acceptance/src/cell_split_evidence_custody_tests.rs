use super::*;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

const DOMAIN: &str = "scope.evidence.metrics";

#[derive(Clone, Copy)]
enum Reply {
    Valid,
    StaleSequence,
    AlteredRows,
    ChangedHead,
    ChangedBytes,
    WrongNonce,
    WrongDomain,
    WrongSigner,
    SignatureCorruptedAfterSigning,
    Unavailable,
}

struct Fixture {
    signer: SigningKey,
    other: SigningKey,
    reply: Reply,
    calls: usize,
}

impl Fixture {
    fn new(reply: Reply) -> Self {
        Self {
            signer: SigningKey::from_bytes(&[61_u8; 32]),
            other: SigningKey::from_bytes(&[62_u8; 32]),
            reply,
            calls: 0,
        }
    }
}

fn local() -> CellSplitEvidenceLocalFrontierV1 {
    CellSplitEvidenceLocalFrontierV1 {
        journal_domain_id: DOMAIN.into(),
        sequence: 7,
        committed_rows: 11,
        head_digest: Digest32::of_bytes(b"original fsynced chain head"),
        wal_bytes: 1024,
    }
}

impl CellSplitEvidenceCustodyPortV1 for Fixture {
    type Error = &'static str;

    fn read_current_domain(
        &mut self,
        journal_domain_id: &str,
        challenge_nonce: &str,
    ) -> Result<CellSplitEvidenceSignedCustodyV1, Self::Error> {
        self.calls += 1;
        assert_eq!(journal_domain_id, DOMAIN, "no proposed local fields in request");
        assert_eq!(challenge_nonce.len(), 64);
        assert!(
            challenge_nonce
                .bytes()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
        );
        if matches!(self.reply, Reply::Unavailable) {
            return Err("independent signer unavailable");
        }
        let mut proof = CellSplitEvidenceSignedCustodyV1 {
            schema: CELL_SPLIT_EVIDENCE_CUSTODY_SCHEMA_V1.to_owned(),
            journal_domain_id: journal_domain_id.to_owned(),
            authority_epoch: 3,
            sequence: 7,
            committed_rows: 11,
            head_digest: Digest32::of_bytes(b"original fsynced chain head"),
            wal_bytes: 1024,
            challenge_nonce: challenge_nonce.to_owned(),
            signature_bytes: Vec::new(),
        };
        match self.reply {
            Reply::StaleSequence => proof.sequence -= 1,
            Reply::AlteredRows => proof.committed_rows += 1,
            Reply::ChangedHead => proof.head_digest = Digest32::of_bytes(b"other WAL head"),
            Reply::ChangedBytes => proof.wal_bytes += 1,
            Reply::WrongNonce => proof.challenge_nonce = "dd".repeat(32),
            Reply::WrongDomain => proof.journal_domain_id = "other.evidence".into(),
            _ => {}
        };
        let key = if matches!(self.reply, Reply::WrongSigner) {
            &self.other
        } else {
            &self.signer
        };
        proof.signature_bytes = key
            .sign(&cell_split_evidence_custody_signing_payload_v1(&proof).unwrap())
            .to_bytes()
            .to_vec();
        if matches!(self.reply, Reply::SignatureCorruptedAfterSigning) {
            proof.signature_bytes[0] ^= 0x80;
        }
        Ok(proof)
    }
}

#[test]
fn fresh_custody_signature_binds_original_local_frontier_without_activation() {
    let mut port = Fixture::new(Reply::Valid);
    let v = verify_cell_split_evidence_custody_v1(
        DOMAIN,
        &local(),
        &port.signer.verifying_key(),
        &mut port,
    )
    .expect("independent signature over the exact current WAL");
    assert_eq!(port.calls, 1);
    assert_eq!(v.sequence, 7);
    assert_eq!(v.committed_rows, 11);
    assert_eq!(v.wal_bytes, 1024);
    assert_eq!(v.authority_epoch, 3);
    assert_eq!(v.head_digest, local().head_digest);
    assert_eq!(v.signed_proof_digest.len(), 64);
    assert!(!v.production_activation_authorized);
}

#[test]
fn independently_signed_old_or_different_wal_frontier_is_not_current() {
    for mode in [
        Reply::StaleSequence,
        Reply::AlteredRows,
        Reply::ChangedHead,
        Reply::ChangedBytes,
    ] {
        let mut port = Fixture::new(mode);
        assert!(matches!(
            verify_cell_split_evidence_custody_v1(
                DOMAIN,
                &local(),
                &port.signer.verifying_key(),
                &mut port,
            ),
            Err(CellSplitEvidenceCustodyErrorV1::Invalid)
        ));
        assert_eq!(port.calls, 1);
    }
}

#[test]
fn challenged_custody_rejects_other_domain_and_nonce_even_when_signed() {
    for mode in [Reply::WrongNonce, Reply::WrongDomain] {
        let mut port = Fixture::new(mode);
        assert!(matches!(
            verify_cell_split_evidence_custody_v1(
                DOMAIN,
                &local(),
                &port.signer.verifying_key(),
                &mut port,
            ),
            Err(CellSplitEvidenceCustodyErrorV1::Invalid)
        ));
    }
}

#[test]
fn signer_must_match_the_distinct_pinned_custody_key() {
    let mut port = Fixture::new(Reply::WrongSigner);
    assert!(matches!(
        verify_cell_split_evidence_custody_v1(
            DOMAIN,
            &local(),
            &port.signer.verifying_key(),
            &mut port,
        ),
        Err(CellSplitEvidenceCustodyErrorV1::Untrusted)
    ));
}

#[test]
fn corrupted_signature_cannot_be_launched_as_external_custody() {
    let mut port = Fixture::new(Reply::SignatureCorruptedAfterSigning);
    assert!(matches!(
        verify_cell_split_evidence_custody_v1(
            DOMAIN,
            &local(),
            &port.signer.verifying_key(),
            &mut port,
        ),
        Err(CellSplitEvidenceCustodyErrorV1::Untrusted)
    ));
}

#[test]
fn absent_external_custody_fails_closed_without_local_fallback() {
    let mut port = Fixture::new(Reply::Unavailable);
    assert!(matches!(
        verify_cell_split_evidence_custody_v1(
            DOMAIN,
            &local(),
            &port.signer.verifying_key(),
            &mut port,
        ),
        Err(CellSplitEvidenceCustodyErrorV1::Owner(_))
    ));
    assert_eq!(port.calls, 1);
}

#[test]
fn no_uncommitted_genesis_or_caller_domain_can_create_positive_custody() {
    for candidate in [
        CellSplitEvidenceLocalFrontierV1 {
            sequence: 0,
            ..local()
        },
        CellSplitEvidenceLocalFrontierV1 {
            committed_rows: 0,
            ..local()
        },
        CellSplitEvidenceLocalFrontierV1 {
            head_digest: Digest32::ZERO,
            ..local()
        },
        CellSplitEvidenceLocalFrontierV1 {
            wal_bytes: 0,
            ..local()
        },
        CellSplitEvidenceLocalFrontierV1 {
            journal_domain_id: "other".into(),
            ..local()
        },
    ] {
        let mut port = Fixture::new(Reply::Valid);
        assert!(matches!(
            verify_cell_split_evidence_custody_v1(
                DOMAIN,
                &candidate,
                &port.signer.verifying_key(),
                &mut port,
            ),
            Err(CellSplitEvidenceCustodyErrorV1::Invalid)
        ));
        assert_eq!(port.calls, 0, "invalid local evidence never queries custody");
    }
}

#[test]
fn malformed_domain_cannot_ask_remote_signer_to_certify_anything() {
    let mut port = Fixture::new(Reply::Valid);
    assert!(matches!(
        verify_cell_split_evidence_custody_v1(
            "../not a domain",
            &local(),
            &port.signer.verifying_key(),
            &mut port,
        ),
        Err(CellSplitEvidenceCustodyErrorV1::Invalid)
    ));
    assert_eq!(port.calls, 0);
}
