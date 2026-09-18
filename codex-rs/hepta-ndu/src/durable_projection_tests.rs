use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;

use codex_hepta_types::Digest32;

use super::NduDurableProjectionError;
use super::NduDurableProjectionJournalV1;
use super::NduProjectionRecoveryV1;
use crate::NduProjectionKindV1;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "hepta-ndu-{name}-{}.journal",
        std::process::id()
    ))
}

fn fresh_file(name: &str) -> (PathBuf, File) {
    let path = path(name);
    let _ = fs::remove_file(&path);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(&path)
        .unwrap_or_else(|error| panic!("create {}: {error}", path.display()));
    (path, file)
}

fn existing_file(path: &PathBuf) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("open {}: {error}", path.display()))
}

#[test]
fn durable_projection_syncs_then_recovers_selected_state() {
    let (path, file) = fresh_file("roundtrip");
    let binding = digest("binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");

    let mut store = NduDurableProjectionJournalV1::create(file, binding, 32)
        .expect("create durable projection store");
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
    let anchor = store
        .current_anchor()
        .expect("healthy store")
        .expect("nonempty anchor");
    drop(store);

    let recovered = NduDurableProjectionJournalV1::recover(
        existing_file(&path),
        binding,
        32,
        NduProjectionRecoveryV1::Acknowledged(anchor),
    )
    .expect("recover durable projection store");
    assert_eq!(
        recovered
            .selected_projection_digest(objective, subject)
            .expect("healthy store"),
        Some(projection)
    );
    assert_eq!(
        recovered.current_anchor().expect("healthy store"),
        Some(anchor)
    );
    drop(recovered);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn incomplete_unacknowledged_tail_is_truncated_after_anchor_validation() {
    let (path, file) = fresh_file("tail");
    let binding = digest("binding");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut store = NduDurableProjectionJournalV1::create(file, binding, 16)
        .expect("create durable projection store");
    store
        .append_projection(
            NduProjectionKindV1::Utility,
            digest("projection-id"),
            objective,
            subject,
            projection,
        )
        .expect("append projection");
    let anchor = store
        .current_anchor()
        .expect("healthy store")
        .expect("anchor");
    drop(store);

    {
        let mut file = existing_file(&path);
        file.seek(SeekFrom::End(0)).expect("seek tail");
        file.write_all(&[1, 2, 3]).expect("write partial tail");
        file.sync_all().expect("sync partial tail");
    }
    let before = fs::metadata(&path).expect("metadata").len();
    let recovered = NduDurableProjectionJournalV1::recover(
        existing_file(&path),
        binding,
        16,
        NduProjectionRecoveryV1::Acknowledged(anchor),
    )
    .expect("recover and truncate partial tail");
    drop(recovered);
    let after = fs::metadata(&path).expect("metadata").len();
    assert_eq!(before - after, 3);
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn external_anchor_detects_wholesale_self_consistent_rewrite() {
    let (path, file) = fresh_file("anchor");
    let binding = digest("binding");
    let objective = digest("objective");
    let subject = digest("subject");

    let mut first = NduDurableProjectionJournalV1::create(file, binding, 16)
        .expect("create first store");
    first
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("first-id"),
            objective,
            subject,
            digest("first-payload"),
        )
        .expect("append first");
    let anchor = first
        .current_anchor()
        .expect("healthy first store")
        .expect("first anchor");
    drop(first);

    {
        let file = existing_file(&path);
        file.set_len(0).expect("truncate for simulated hostile rewrite");
    }
    let mut rewritten = NduDurableProjectionJournalV1::create(
        existing_file(&path),
        binding,
        16,
    )
    .expect("create rewritten store");
    rewritten
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("second-id"),
            objective,
            subject,
            digest("second-payload"),
        )
        .expect("append rewritten");
    drop(rewritten);

    assert_eq!(
        NduDurableProjectionJournalV1::recover(
            existing_file(&path),
            binding,
            16,
            NduProjectionRecoveryV1::Acknowledged(anchor),
        )
        .expect_err("external anchor must detect rewrite"),
        NduDurableProjectionError::AnchorMismatch
    );
    fs::remove_file(path).expect("cleanup");
}

#[test]
fn acknowledged_history_cannot_disappear() {
    let (path, file) = fresh_file("missing");
    let binding = digest("binding");
    let mut store = NduDurableProjectionJournalV1::create(file, binding, 16)
        .expect("create store");
    store
        .append_projection(
            NduProjectionKindV1::Preference,
            digest("id"),
            digest("objective"),
            digest("subject"),
            digest("payload"),
        )
        .expect("append");
    let anchor = store
        .current_anchor()
        .expect("healthy")
        .expect("anchor");
    drop(store);

    let mut file = existing_file(&path);
    file.set_len(72).expect("remove acknowledged frame");
    file.seek(SeekFrom::Start(72)).expect("seek");
    file.sync_all().expect("sync truncation");
    drop(file);

    assert_eq!(
        NduDurableProjectionJournalV1::recover(
            existing_file(&path),
            binding,
            16,
            NduProjectionRecoveryV1::Acknowledged(anchor),
        )
        .expect_err("acknowledged history cannot vanish"),
        NduDurableProjectionError::AcknowledgedHistoryMissing
    );
    fs::remove_file(path).expect("cleanup");
}
