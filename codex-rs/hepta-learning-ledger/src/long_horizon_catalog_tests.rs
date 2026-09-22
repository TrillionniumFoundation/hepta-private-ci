//! Caller regressions for catalog resource bounds and unchanged identity checks.

use pretty_assertions::assert_eq;

use super::catalog_test_support::TestDirectory;

use super::*;

fn catalog() -> (TestDirectory, Digest32, LedgerSegmentLimits) {
    let root = TestDirectory::new().expect("temporary directory");
    let binding = Digest32::of_bytes(b"catalog-boundary-test");
    let limits = LedgerSegmentLimits {
        records: 2,
        bytes: 4096,
    };
    initialize_profile(root.path(), binding, limits).expect("initialize profile");
    (root, binding, limits)
}

#[test]
fn profile_binding_and_size_are_both_required() {
    let (root, binding, limits) = catalog();
    verify_profile(root.path(), binding, limits).expect("valid profile");
    assert!(verify_profile(root.path(), Digest32::of_bytes(b"other"), limits).is_err());
    let path = root.path().join(PROFILE_FILE);
    File::options()
        .write(true)
        .open(&path)
        .expect("open profile")
        .set_len(1_u64 << 30)
        .expect("extend sparse profile");
    assert!(matches!(
        verify_profile(root.path(), binding, limits),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
}

#[test]
fn absent_and_valid_locations_keep_their_existing_semantics() {
    let (root, binding, _) = catalog();
    let id = StableId::new("first").expect("record id");
    assert_eq!(
        read_record_location(root.path(), binding, &id).expect("absent row"),
        None
    );
    let path = record_location_path(&root.path().join(RECORD_LOCATION_DIR), &id);
    let bytes = record_location_bytes(binding, &id, 3).expect("encode location");
    write_immutable(&path, &bytes).expect("persist location");
    assert_eq!(
        read_record_location(root.path(), binding, &id).expect("valid location"),
        Some(3)
    );
    assert!(read_record_location(root.path(), Digest32::of_bytes(b"other"), &id).is_err());
}

#[test]
fn same_length_wrong_record_identity_remains_rejected() {
    let (root, binding, _) = catalog();
    let expected = StableId::new("first").expect("expected id");
    let other = StableId::new("other").expect("other id");
    let path = record_location_path(&root.path().join(RECORD_LOCATION_DIR), &expected);
    let bytes = record_location_bytes(binding, &other, 3).expect("encode wrong id");
    fs::write(path, bytes).expect("store wrong row");
    assert!(matches!(
        read_record_location(root.path(), binding, &expected),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
}

#[test]
fn malformed_location_is_not_reported_as_an_absent_record() {
    let (root, binding, _) = catalog();
    let id = StableId::new("first").expect("record id");
    let path = record_location_path(&root.path().join(RECORD_LOCATION_DIR), &id);
    File::create(&path)
        .expect("create location")
        .set_len(1_u64 << 30)
        .expect("extend sparse location");
    assert!(matches!(
        read_record_location(root.path(), binding, &id),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
}

#[test]
fn archive_range_preserves_binding_and_rejects_oversized_rows() {
    let (root, binding, _) = catalog();
    let range = LongHorizonArchiveRangeV1 {
        segment: 0,
        predecessor: empty_anchor(),
        anchor: LedgerAnchor {
            sequence: 2,
            chain_digest: Digest32::of_bytes(b"head"),
        },
    };
    assert_eq!(
        read_archive_range(root.path(), binding, 0).expect("absent range"),
        None
    );
    let path = archive_range_path(&root.path().join(ARCHIVE_RANGE_DIR), 0);
    let bytes = archive_range_bytes(binding, range).expect("encode range");
    write_immutable(&path, &bytes).expect("persist range");
    assert_eq!(
        read_archive_range(root.path(), binding, 0).expect("valid range"),
        Some(range)
    );
    assert!(read_archive_range(root.path(), Digest32::of_bytes(b"other"), 0).is_err());
    File::options()
        .write(true)
        .open(&path)
        .expect("open range")
        .set_len(1_u64 << 30)
        .expect("extend sparse range");
    assert!(matches!(
        read_archive_range(root.path(), binding, 0),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
}

#[test]
fn immutable_retry_never_replaces_corrupt_or_different_bytes() {
    let (root, _, _) = catalog();
    let path = root.path().join("immutable");
    write_immutable(&path, b"data").expect("initial publication");
    write_immutable(&path, b"data").expect("identical retry");
    assert!(write_immutable(&path, b"else").is_err());
    assert_eq!(fs::read(&path).expect("original bytes"), b"data");
    File::options()
        .write(true)
        .open(&path)
        .expect("open row")
        .set_len(1_u64 << 30)
        .expect("extend sparse row");
    assert!(matches!(
        write_immutable(&path, b"data"),
        Err(LongHorizonLedgerErrorV1::CatalogCorrupt)
    ));
    assert_eq!(
        fs::metadata(&path).expect("retained row").len(),
        1_u64 << 30
    );
    assert!(!path.with_extension("tmp").exists());
}
