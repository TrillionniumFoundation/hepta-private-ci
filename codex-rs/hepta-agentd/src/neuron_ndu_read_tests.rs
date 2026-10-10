use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::Mutex;

#[derive(Debug)]
struct ProtectedClock(u64);

impl AuthorityClock for ProtectedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0)
    }
}

#[derive(Debug)]
struct ControlFrontier(Mutex<NduSnapshotRefV1>);

impl NduReadFrontierPortV1 for ControlFrontier {
    fn latest(&self, scope: &StableId) -> Result<NduSnapshotRefV1, NduReadVerificationErrorV1> {
        let snapshot = self.0.lock()
            .map_err(|_| NduReadVerificationErrorV1::FrontierUnavailable)?;
        if &snapshot.scope_id != scope {
            return Err(NduReadVerificationErrorV1::FrontierUnavailable);
        }
        Ok(snapshot.clone())
    }
}

fn snapshot() -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        scope_id: StableId::new("subject").unwrap(),
        owner_id: StableId::new("ndu-owner").unwrap(),
        generation: Generation::new(3).unwrap(),
        route_fence: 7,
        revocation_epoch: 9,
        policy_digest: Digest32::of_bytes(b"policy"),
        snapshot_digest: Digest32::of_bytes(b"snapshot"),
        projection_head_digest: Digest32::of_bytes(b"head"),
    }
}

fn signed_read(key: &SigningKey, snapshot: NduSnapshotRefV1) -> SignedNduSnapshotReadV1 {
    let mut read = SignedNduSnapshotReadV1 {
        snapshot,
        read_id: StableId::new("read-one").unwrap(),
        read_receipt_digest: Digest32::of_bytes(b"owner-durable-read"),
        issued_at_unix_ms: 900,
        expires_at_unix_ms: 1100,
        signature: [0; 64],
    };
    read.signature = key.sign(&read.signing_bytes().unwrap()).to_bytes();
    read
}

#[test]
fn independent_signature_time_and_live_frontier_must_all_agree() {
    let key = SigningKey::from_bytes(&[39; 32]);
    let frontier = Arc::new(ControlFrontier(Mutex::new(snapshot())));
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(ProtectedClock(1000)),
        frontier.clone(),
    ).unwrap();
    let original = signed_read(&key, snapshot());
    let admitted = verifier.verify(&original).unwrap();
    assert!(!admitted.is_zero());

    let mut tampered = original.clone();
    tampered.read_receipt_digest = Digest32::of_bytes(b"swapped");
    assert_eq!(verifier.verify(&tampered), Err(NduReadVerificationErrorV1::Signature));

    let another = SigningKey::from_bytes(&[40; 32]);
    tampered = signed_read(&another, snapshot());
    assert_eq!(verifier.verify(&tampered), Err(NduReadVerificationErrorV1::Signature));

    let mut stale = snapshot();
    stale.route_fence += 1;
    *frontier.0.lock().unwrap() = stale;
    assert_eq!(verifier.verify(&original), Err(NduReadVerificationErrorV1::StaleFrontier));
}

#[test]
fn read_expiration_and_unknown_owner_are_fail_closed() {
    let key = SigningKey::from_bytes(&[41; 32]);
    let frontier = Arc::new(ControlFrontier(Mutex::new(snapshot())));
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(ProtectedClock(1500)),
        frontier,
    ).unwrap();
    let read = signed_read(&key, snapshot());
    assert_eq!(verifier.verify(&read), Err(NduReadVerificationErrorV1::Expired));
    let mut wrong = snapshot();
    wrong.owner_id = StableId::new("intruder").unwrap();
    assert_eq!(
        verifier.verify(&signed_read(&key, wrong)),
        Err(NduReadVerificationErrorV1::UntrustedOwner),
    );
}
