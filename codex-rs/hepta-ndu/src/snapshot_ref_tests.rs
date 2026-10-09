use super::*;

fn d(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

fn example(bytes: &[u8]) -> NduSnapshotRefV1 {
    NduSnapshotRefV1 {
        subject_id: StableId::new("subject:1").expect("id"),
        objective_digest: d("objective"),
        owner_generation: Generation::new(2).expect("generation"),
        authority_epoch: 4,
        fence_digest: d("fence"),
        revocation_frontier_digest: d("revocation"),
        policy_digest: d("policy"),
        snapshot_digest: Digest32::of_bytes(bytes),
        cas_locator: "cas:ndu:payload".to_string(),
        payload_bytes: bytes.len() as u64,
    }
}

#[test]
fn snapshot_reference_binds_context_and_bytes() {
    let bytes = b"frozen-ndu-snapshot";
    let snapshot = example(bytes);
    assert_eq!(snapshot.verify_payload(bytes), Ok(()));
    assert_eq!(
        snapshot.verify_payload(b"frozen-ndu-snapshoT"),
        Err(NduSnapshotRefErrorV1::PayloadMismatch)
    );
    let digest = snapshot.binding_digest().expect("binding");
    let mut stale = snapshot.clone();
    stale.authority_epoch += 1;
    assert_ne!(stale.binding_digest().expect("binding"), digest);
    stale = snapshot.clone();
    stale.fence_digest = d("new-fence");
    assert_ne!(stale.binding_digest().expect("binding"), digest);
    stale = snapshot.clone();
    stale.cas_locator = "cas:other".to_string();
    assert_ne!(stale.binding_digest().expect("binding"), digest);
}

#[test]
fn snapshot_ref_never_acts_as_a_cas_authority() {
    let mut snapshot = example(b"payload");
    snapshot.cas_locator = "../../foreign-store".to_string();
    // Opaque identifiers are not filesystem paths: the resolver and CAS
    // owner are responsible for storage admission and access control.
    assert!(snapshot.validate().is_ok());
    snapshot.cas_locator = String::new();
    assert_eq!(snapshot.validate(), Err(NduSnapshotRefErrorV1::InvalidLocator));
    snapshot.cas_locator = "cas:ok".to_string();
    snapshot.payload_bytes = 0;
    assert_eq!(snapshot.validate(), Err(NduSnapshotRefErrorV1::InvalidSize));
}
