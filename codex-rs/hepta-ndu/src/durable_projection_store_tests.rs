use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;

use super::NduDurableProjectionError;
use super::NduDurableProjectionStoreV1;
use crate::NduProjectionKindV1;

static NEXT_FILE: AtomicU64 = AtomicU64::new(1);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn file() -> (PathBuf, File) {
    let nonce = NEXT_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-ndu-durable-{}-{nonce}.journal",
        std::process::id()
    ));
    let handle = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&path)
        .expect("create isolated durable NDU fixture");
    (path, handle)
}

#[test]
fn durable_store_syncs_and_recovers_selected_projection_against_anchor() {
    let (path, handle) = file();
    let binding = digest("scope-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store =
        NduDurableProjectionStoreV1::create(handle, binding).expect("create durable store");
    let first = store.anchor();
    store
        .append_projection(
            first,
            NduProjectionKindV1::Preference,
            digest("projection-identity"),
            objective,
            subject,
            projection,
        )
        .expect("append projection");
    let second = store.anchor();
    store
        .select_projection(
            second,
            digest("selection-identity"),
            objective,
            subject,
            projection,
        )
        .expect("select projection");
    let acknowledged = store.anchor();
    assert_eq!(
        store
            .selected_projection_digest(objective, subject)
            .expect("selected view"),
        Some(projection)
    );
    drop(store);

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen durable fixture");
    let recovered = NduDurableProjectionStoreV1::recover(handle, binding, acknowledged)
        .expect("recover acknowledged state");
    assert_eq!(recovered.anchor(), acknowledged);
    assert_eq!(
        recovered
            .selected_projection_digest(objective, subject)
            .expect("selected view"),
        Some(projection)
    );
    drop(recovered);
    std::fs::remove_file(path).expect("remove durable fixture");
}

#[test]
fn idempotent_replay_does_not_append_another_durable_record() {
    let (path, handle) = file();
    let binding = digest("scope-binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let identity = digest("projection-identity");

    let mut store =
        NduDurableProjectionStoreV1::create(handle, binding).expect("create durable store");
    let entry = store
        .append_projection(
            store.anchor(),
            NduProjectionKindV1::Utility,
            identity,
            objective,
            subject,
            projection,
        )
        .expect("first append");
    let acknowledged = store.anchor();
    let replay = store
        .append_projection(
            acknowledged,
            NduProjectionKindV1::Utility,
            identity,
            objective,
            subject,
            projection,
        )
        .expect("idempotent replay");
    assert_eq!(entry, replay);
    assert_eq!(store.anchor(), acknowledged);
    drop(store);
    std::fs::remove_file(path).expect("remove durable fixture");
}

#[test]
fn recover_rejects_missing_acknowledged_history() {
    let (path, handle) = file();
    let binding = digest("scope-binding");
    let mut store =
        NduDurableProjectionStoreV1::create(handle, binding).expect("create durable store");
    store
        .append_projection(
            store.anchor(),
            NduProjectionKindV1::Preference,
            digest("projection-identity"),
            digest("objective"),
            digest("subject"),
            digest("projection"),
        )
        .expect("append projection");
    let acknowledged = store.anchor();
    drop(store);

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("open fixture for truncation");
    handle
        .set_len(super::HEADER_BYTES as u64)
        .expect("truncate complete record");
    drop(handle);

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen truncated fixture");
    assert_eq!(
        NduDurableProjectionStoreV1::recover(handle, binding, acknowledged)
            .expect_err("acknowledged history cannot disappear"),
        NduDurableProjectionError::MissingAcknowledgedHistory
    );
    std::fs::remove_file(path).expect("remove durable fixture");
}

#[test]
fn recover_rejects_binding_substitution() {
    let (path, handle) = file();
    let binding = digest("scope-binding");
    let store =
        NduDurableProjectionStoreV1::create(handle, binding).expect("create durable store");
    let anchor = store.anchor();
    drop(store);

    let handle = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .expect("reopen durable fixture");
    assert_eq!(
        NduDurableProjectionStoreV1::recover(handle, digest("other-binding"), anchor)
            .expect_err("store binding cannot drift"),
        NduDurableProjectionError::BindingMismatch
    );
    std::fs::remove_file(path).expect("remove durable fixture");
}

#[test]
fn stale_expected_anchor_cannot_mutate_store() {
    let (path, handle) = file();
    let binding = digest("scope-binding");
    let mut store =
        NduDurableProjectionStoreV1::create(handle, binding).expect("create durable store");
    let stale = store.anchor();
    store
        .append_projection(
            stale,
            NduProjectionKindV1::Preference,
            digest("projection-identity"),
            digest("objective"),
            digest("subject"),
            digest("projection"),
        )
        .expect("append projection");
    assert_eq!(
        store
            .revoke_projection(
                stale,
                digest("revocation-identity"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
            )
            .expect_err("stale CAS anchor must fail"),
        NduDurableProjectionError::Conflict
    );
    drop(store);
    std::fs::remove_file(path).expect("remove durable fixture");
}
