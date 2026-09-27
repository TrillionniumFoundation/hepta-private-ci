use super::*;

#[test]
fn image_length_is_checked_before_serializing_bodies() {
    let mut image = PlannerStoreImageV1::new();
    let body = vec![7; MAX_BODY_BYTES];
    for index in 0_u64..64 {
        image.insert_body(
            PlannerBodyKindV1::Snapshot,
            Digest32::of_bytes(&index.to_be_bytes()),
            None,
            &body,
        ).expect("insert bounded body");
    }
    assert_eq!(image.encoded_len(), Err(PlannerStoreError::StoreTooLarge));
    assert_eq!(image.export_bytes(), Err(PlannerStoreError::StoreTooLarge));
}

#[test]
fn bounded_read_stops_an_unending_reader() {
    struct Endless { bytes_read: usize }
    impl Read for Endless {
        fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
            bytes.fill(0);
            self.bytes_read += bytes.len();
            Ok(bytes.len())
        }
    }
    let mut reader = Endless { bytes_read: 0 };
    assert_eq!(read_bounded_image(&mut reader), Err(PlannerStoreError::StoreTooLarge));
    assert_eq!(reader.bytes_read, MAX_STORE_BYTES + 1);
}

#[test]
fn cyclic_parent_links_are_rejected_even_with_valid_body_hashes() {
    let mut image = PlannerStoreImageV1::new();
    let a = Digest32::of_bytes(b"a");
    let b = Digest32::of_bytes(b"b");
    image.insert_body(PlannerBodyKindV1::Snapshot, a, None, b"a").expect("a");
    image.insert_body(PlannerBodyKindV1::AuthorityRequest, b, Some(a), b"b").expect("b");
    image.bodies.get_mut(&a).expect("a").parent_digest = Some(b);
    assert_eq!(image.validate_parent_links(), Err(PlannerStoreError::CorruptBody));
}

#[cfg(unix)]
#[test]
fn new_store_files_are_private_and_sparse_oversize_is_rejected() {
    use std::os::unix::fs::PermissionsExt;
    let root = tempfile::tempdir().expect("directory");
    let store = PlannerStoreV1::open(root.path()).expect("store");
    for name in [STORE_FILE, LOCK_FILE] {
        let mode = fs::metadata(root.path().join(name)).expect("metadata").permissions().mode();
        assert_eq!(mode & 0o077, 0, "planner state must not be group/world readable");
    }
    drop(store);
    let file = OpenOptions::new().write(true).open(root.path().join(STORE_FILE)).expect("file");
    file.set_len(MAX_STORE_BYTES as u64 + 1).expect("sparse oversize");
    assert!(matches!(PlannerStoreV1::open(root.path()), Err(PlannerStoreError::StoreTooLarge)));
}

#[cfg(unix)]
#[test]
fn compaction_keeps_execution_identity_roots() {
    let root = tempfile::tempdir().expect("directory");
    let mut store = PlannerStoreV1::open(root.path()).expect("store");
    let parent = Digest32::of_bytes(b"parent");
    let request = Digest32::of_bytes(b"request");
    let grant = Digest32::of_bytes(b"grant");
    store.commit(|image| {
        image.insert_body(PlannerBodyKindV1::Decision, parent, None, b"decision")?;
        Ok(())
    }).expect("decision");
    store.record_evidence(PlannerBodyKindV1::AuthorityRequest, request, parent, b"request").expect("intent");
    store.record_evidence(PlannerBodyKindV1::AuthorityGrant, grant, request, b"grant").expect("grant");
    store.compact_evidence(&BTreeSet::new(), Digest32::of_bytes(b"archive-reference")).expect("compact");
    drop(store);
    let reopened = PlannerStoreV1::open(root.path()).expect("reopen");
    assert!(reopened.body(request).expect("request").is_some());
    assert!(reopened.body(grant).expect("grant").is_some());
}
