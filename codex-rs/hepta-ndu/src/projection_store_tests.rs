#![cfg(unix)]

use std::fmt::Debug;

use codex_hepta_types::Digest32;

use super::NduProjectionFileStoreV1;
use super::NduProjectionStoreError;
use crate::NduProjectionKindV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn durable_store_reopens_selected_projection_after_synced_publication() {
    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("ndu.projections");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    {
        let mut store = must(NduProjectionFileStoreV1::open(&path));
        must(store.append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-identity"),
            objective,
            subject,
            projection,
        ));
        must(store.select_projection(digest("selection-identity"), objective, subject, projection));
    }

    let reopened = must(NduProjectionFileStoreV1::open(&path));
    assert_eq!(
        reopened.selected_projection_digest(objective, subject),
        Some(projection)
    );
    assert_eq!(reopened.entries().len(), 2);
}

#[test]
fn durable_store_has_one_os_backed_writer() {
    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("ndu.projections");
    let first = must(NduProjectionFileStoreV1::open(&path));
    assert_eq!(
        NduProjectionFileStoreV1::open(&path).expect_err("second writer must fail"),
        NduProjectionStoreError::WriterBusy
    );
    drop(first);
    must(NduProjectionFileStoreV1::open(&path));
}

#[test]
fn durable_store_preserves_scoped_revocation_after_reopen() {
    let root = tempfile::tempdir().expect("temporary directory");
    let path = root.path().join("ndu.projections");
    let objective_a = digest("objective-a");
    let objective_b = digest("objective-b");
    let subject_a = digest("subject-a");
    let subject_b = digest("subject-b");
    let projection = digest("same-payload");

    {
        let mut store = must(NduProjectionFileStoreV1::open(&path));
        must(store.append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-a"),
            objective_a,
            subject_a,
            projection,
        ));
        must(store.append_projection(
            NduProjectionKindV1::Preference,
            digest("projection-b"),
            objective_b,
            subject_b,
            projection,
        ));
        must(store.select_projection(digest("selection-a"), objective_a, subject_a, projection));
        must(store.select_projection(digest("selection-b"), objective_b, subject_b, projection));
        must(store.revoke_projection(digest("revocation-a"), objective_a, subject_a, projection));
    }

    let reopened = must(NduProjectionFileStoreV1::open(&path));
    assert_eq!(
        reopened.selected_projection_digest(objective_a, subject_a),
        None
    );
    assert_eq!(
        reopened.selected_projection_digest(objective_b, subject_b),
        Some(projection)
    );
}

#[test]
fn symlink_destination_fails_closed() {
    use std::os::unix::fs::symlink;

    let root = tempfile::tempdir().expect("temporary directory");
    let real = root.path().join("real");
    std::fs::write(&real, b"not-a-journal").expect("write target");
    let path = root.path().join("ndu.projections");
    symlink(&real, &path).expect("create symlink");

    assert_eq!(
        NduProjectionFileStoreV1::open(&path).expect_err("symlink must fail"),
        NduProjectionStoreError::Symlink
    );
}
