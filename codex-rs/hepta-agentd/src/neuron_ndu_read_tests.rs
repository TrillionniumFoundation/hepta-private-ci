use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

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
        let snapshot = self
            .0
            .lock()
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
    )
    .unwrap();
    let original = signed_read(&key, snapshot());
    let admitted = verifier.verify(&original).unwrap();
    assert!(!admitted.is_zero());

    let mut tampered = original.clone();
    tampered.read_receipt_digest = Digest32::of_bytes(b"swapped");
    assert_eq!(
        verifier.verify(&tampered),
        Err(NduReadVerificationErrorV1::Signature)
    );

    let another = SigningKey::from_bytes(&[40; 32]);
    tampered = signed_read(&another, snapshot());
    assert_eq!(
        verifier.verify(&tampered),
        Err(NduReadVerificationErrorV1::Signature)
    );

    let mut stale = snapshot();
    stale.route_fence += 1;
    *frontier.0.lock().unwrap() = stale;
    assert_eq!(
        verifier.verify(&original),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
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
    )
    .unwrap();
    let read = signed_read(&key, snapshot());
    assert_eq!(
        verifier.verify(&read),
        Err(NduReadVerificationErrorV1::Expired)
    );
    let mut wrong = snapshot();
    wrong.owner_id = StableId::new("intruder").unwrap();
    assert_eq!(
        verifier.verify(&signed_read(&key, wrong)),
        Err(NduReadVerificationErrorV1::UntrustedOwner),
    );
}

#[derive(Debug)]
struct AdvancingClock(AtomicUsize);

impl AuthorityClock for AdvancingClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        // Construction and preflight are valid. The independent Control
        // read finishes only after the NDU read grant has expired.
        let reading = self.0.fetch_add(1, Ordering::SeqCst);
        Ok(if reading <= 1 { 1000 } else { 1200 })
    }
}

#[test]
fn read_expiring_during_frontier_verification_is_rejected() {
    let key = SigningKey::from_bytes(&[43; 32]);
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(AdvancingClock(AtomicUsize::new(0))),
        Arc::new(ControlFrontier(Mutex::new(snapshot()))),
    )
    .unwrap();
    let original = signed_read(&key, snapshot());
    assert_eq!(
        verifier.verify(&original),
        Err(NduReadVerificationErrorV1::Expired)
    );
}

#[test]
fn read_only_frontier_cannot_publish_even_after_a_valid_signed_read() {
    let key = SigningKey::from_bytes(&[44; 32]);
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(ProtectedClock(1000)),
        Arc::new(ControlFrontier(Mutex::new(snapshot()))),
    )
    .unwrap();
    let read = signed_read(&key, snapshot());
    assert!(verifier.verify(&read).is_ok());
    assert_eq!(
        verifier.compare_and_publish_checkpoint(
            &read,
            Digest32::of_bytes(b"tick"),
            Digest32::ZERO,
            Digest32::of_bytes(b"committed-checkpoint"),
        ),
        Err(NduReadVerificationErrorV1::CheckpointPublicationUnavailable)
    );
}

#[derive(Debug)]
struct PublishingFrontier {
    state: Mutex<(NduSnapshotRefV1, Digest32, usize)>,
}

impl NduReadFrontierPortV1 for PublishingFrontier {
    fn latest(&self, scope: &StableId) -> Result<NduSnapshotRefV1, NduReadVerificationErrorV1> {
        let record = self
            .state
            .lock()
            .map_err(|_| NduReadVerificationErrorV1::FrontierUnavailable)?;
        if &record.0.scope_id != scope {
            return Err(NduReadVerificationErrorV1::StaleFrontier);
        }
        Ok(record.0.clone())
    }

    fn compare_and_publish_checkpoint(
        &self,
        expected: &NduSnapshotRefV1,
        verified_read_digest: Digest32,
        tick_digest: Digest32,
        previous_checkpoint: Digest32,
        next_checkpoint: Digest32,
    ) -> Result<Digest32, NduReadVerificationErrorV1> {
        let mut record = self
            .state
            .lock()
            .map_err(|_| NduReadVerificationErrorV1::FrontierUnavailable)?;
        if record.0 != *expected
            || record.1 != previous_checkpoint
            || verified_read_digest.is_zero()
            || tick_digest.is_zero()
            || next_checkpoint.is_zero()
        {
            return Err(NduReadVerificationErrorV1::StaleFrontier);
        }
        record.1 = next_checkpoint;
        record.2 += 1;
        let mut bytes = b"test.control.atomic-checkpoint-publication.v1".to_vec();
        bytes.extend_from_slice(&record.2.to_be_bytes());
        bytes.extend_from_slice(verified_read_digest.as_array());
        bytes.extend_from_slice(tick_digest.as_array());
        bytes.extend_from_slice(next_checkpoint.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[test]
fn atomic_checkpoint_publication_rejects_cutover_and_duplicate_predecessor() {
    let key = SigningKey::from_bytes(&[45; 32]);
    let frontier = Arc::new(PublishingFrontier {
        state: Mutex::new((snapshot(), Digest32::ZERO, 0)),
    });
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(ProtectedClock(1000)),
        frontier.clone(),
    )
    .unwrap();
    let read = signed_read(&key, snapshot());
    let tick = Digest32::of_bytes(b"tick-one");
    let next = Digest32::of_bytes(b"checkpoint-one");
    let first = verifier
        .compare_and_publish_checkpoint(&read, tick, Digest32::ZERO, next)
        .expect("matching Control snapshot");
    assert!(!first.is_zero());
    assert_eq!(
        verifier.compare_and_publish_checkpoint(&read, tick, Digest32::ZERO, next),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
    let mut newer = snapshot();
    newer.route_fence += 1;
    frontier.state.lock().unwrap().0 = newer;
    assert_eq!(
        verifier.compare_and_publish_checkpoint(
            &read,
            Digest32::of_bytes(b"tick-two"),
            next,
            Digest32::of_bytes(b"checkpoint-two"),
        ),
        Err(NduReadVerificationErrorV1::StaleFrontier)
    );
    assert_eq!(frontier.state.lock().unwrap().2, 1);
}

#[test]
fn read_only_frontier_preflight_denies_without_entering_model_or_claiming_nonce() {
    let key = SigningKey::from_bytes(&[46; 32]);
    let verifier = NduReadVerifierV1::new(
        StableId::new("ndu-owner").unwrap(),
        key.verifying_key().to_bytes(),
        Arc::new(ProtectedClock(1000)),
        Arc::new(ControlFrontier(Mutex::new(snapshot()))),
    )
    .unwrap();
    let read = signed_read(&key, snapshot());
    assert!(verifier.verify(&read).is_ok());
    assert_eq!(
        verifier.check_checkpoint_publisher(&read.snapshot),
        Err(NduReadVerificationErrorV1::CheckpointPublicationUnavailable)
    );
}
