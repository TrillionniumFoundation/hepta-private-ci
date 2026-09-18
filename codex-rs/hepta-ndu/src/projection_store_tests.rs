use std::fs;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::NduProjectionStoreError;
use super::NduProjectionStoreV1;
use super::STORE_FILENAME;
use crate::NduProjectionKindV1;

static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(1);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn fixture_path(label: &str) -> std::path::PathBuf {
    let sequence = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "hepta-ndu-{label}-{}-{sequence}",
        std::process::id()
    ))
}

fn cleanup(path: &std::path::Path) {
    match fs::remove_dir_all(path) {
        Ok(()) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => panic!("fixture cleanup failed: {error}"),
    }
}

#[test]
fn durable_store_reopens_exact_selection_and_checkpoint() {
    let root = fixture_path("reopen");
    cleanup(&root);
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let checkpoint;
    {
        let mut store = NduProjectionStoreV1::open(&root).expect("open store");
        store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("projection-id"),
                objective,
                subject,
                projection,
            )
            .expect("append projection");
        store
            .select_projection(digest("selection-id"), objective, subject, projection)
            .expect("select projection");
        checkpoint = store.checkpoint();
    }

    let reopened = NduProjectionStoreV1::open(&root).expect("reopen store");
    assert_eq!(reopened.checkpoint(), checkpoint);
    assert_eq!(
        reopened.selected_projection_digest(objective, subject),
        Some(projection)
    );
    drop(reopened);
    cleanup(&root);
}

#[test]
fn writer_lock_fails_closed_for_a_second_open() {
    let root = fixture_path("lock");
    cleanup(&root);
    let first = NduProjectionStoreV1::open(&root).expect("first writer");
    assert_eq!(
        NduProjectionStoreV1::open(&root).expect_err("second writer must reject"),
        NduProjectionStoreError::WriterBusy
    );
    drop(first);
    cleanup(&root);
}

#[test]
fn failed_persistence_does_not_advance_in_memory_state() {
    let root = fixture_path("rollback");
    cleanup(&root);
    let objective = digest("objective");
    let subject = digest("subject");
    let mut store = NduProjectionStoreV1::open(&root).expect("open store");
    let predecessor = store.checkpoint();

    let store_path = root.join(STORE_FILENAME);
    fs::remove_file(&store_path).expect("remove store");
    fs::create_dir(&store_path).expect("replace store path with directory");

    assert!(store
        .append_projection(
            NduProjectionKindV1::Utility,
            digest("projection-id"),
            objective,
            subject,
            digest("projection"),
        )
        .is_err());
    assert_eq!(store.checkpoint(), predecessor);

    drop(store);
    cleanup(&root);
}

#[test]
fn backup_and_restore_create_a_verified_new_store() {
    let root = fixture_path("backup-source");
    let restore_root = fixture_path("backup-restore");
    let backup_parent = fixture_path("backup-parent");
    cleanup(&root);
    cleanup(&restore_root);
    cleanup(&backup_parent);
    fs::create_dir(&backup_parent).expect("backup parent");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&backup_parent, fs::Permissions::from_mode(0o700))
            .expect("private backup parent");
    }
    let backup_path = backup_parent.join("projection.backup");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let checkpoint;

    {
        let mut store = NduProjectionStoreV1::open(&root).expect("open store");
        store
            .append_projection(
                NduProjectionKindV1::Utility,
                digest("projection-id"),
                objective,
                subject,
                projection,
            )
            .expect("append projection");
        store
            .select_projection(digest("selection-id"), objective, subject, projection)
            .expect("select projection");
        checkpoint = store
            .backup_create_new(&backup_path)
            .expect("durable backup");
    }

    let restored =
        NduProjectionStoreV1::restore_create_new(&backup_path, &restore_root).expect("restore");
    assert_eq!(restored.checkpoint(), checkpoint);
    assert_eq!(
        restored.selected_projection_digest(objective, subject),
        Some(projection)
    );
    drop(restored);

    cleanup(&root);
    cleanup(&restore_root);
    cleanup(&backup_parent);
}

#[test]
fn tampered_store_rejects_on_reopen() {
    let root = fixture_path("tamper");
    cleanup(&root);
    {
        let mut store = NduProjectionStoreV1::open(&root).expect("open store");
        store
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("projection-id"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
            )
            .expect("append projection");
    }

    let path = root.join(STORE_FILENAME);
    let mut bytes = fs::read(&path).expect("read store");
    let index = bytes.len() / 2;
    bytes[index] ^= 1;
    fs::write(&path, bytes).expect("tamper store");

    assert_eq!(
        NduProjectionStoreV1::open(&root).expect_err("tamper must reject"),
        NduProjectionStoreError::CorruptStore
    );
    cleanup(&root);
}
