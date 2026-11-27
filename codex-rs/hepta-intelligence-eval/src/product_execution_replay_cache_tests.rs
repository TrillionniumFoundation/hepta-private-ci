use super::super::physical::Replay;
use super::super::replay_cache::MAX_VERIFIED_REPLAY_IMAGE_BYTES;
use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;

fn cached(store: &LockedFileProductEvaluationExecutionStoreV1) -> io::Result<Arc<Replay>> {
    store
        .verified_replay
        .as_ref()
        .map(|verified| Arc::clone(&verified.replayed))
        .ok_or_else(|| io::Error::other("the bounded original image was not memoized"))
}

fn image(store: &mut LockedFileProductEvaluationExecutionStoreV1) -> io::Result<Vec<u8>> {
    let cursor = store.file.stream_position()?;
    store.file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    store.file.read_to_end(&mut bytes)?;
    store.file.seek(SeekFrom::Start(cursor))?;
    Ok(bytes)
}

fn overwrite(
    store: &mut LockedFileProductEvaluationExecutionStoreV1,
    bytes: &[u8],
) -> io::Result<()> {
    store.file.seek(SeekFrom::Start(0))?;
    store.file.write_all(bytes)?;
    store.file.set_len(bytes.len() as u64)?;
    store.file.sync_all()
}

#[test]
fn verified_replay_is_reused_only_until_an_original_append() -> Result<(), Box<dyn StdError>> {
    let file = TempJournal::new();
    let mut store = file.create();
    let operation = key("completed");
    store.claim(&operation)?;
    store.complete(&operation, b"original")?;
    let anchor = store.anchor();
    assert_eq!(store.read_current_anchor()?, anchor);
    let first = cached(&store)?;
    let original = image(&mut store)?;
    for cursor in [0, 7, original.len() as u64 + 9] {
        store.file.seek(SeekFrom::Start(cursor))?;
        assert_eq!(store.read_current_anchor()?, anchor);
        assert_eq!(store.file.stream_position()?, cursor);
        assert!(Arc::ptr_eq(&first, &cached(&store)?));
        assert_eq!(
            store.readback(&operation)?,
            State::Completed(b"original".to_vec())
        );
        assert!(Arc::ptr_eq(&first, &cached(&store)?));
        assert_eq!(image(&mut store)?, original);
    }
    let next = key("next");
    store.claim(&next)?;
    assert!(store.verified_replay.is_none());
    assert_eq!(store.readback(&next)?, State::Pending);
    assert!(!Arc::ptr_eq(&first, &cached(&store)?));
    store.complete(&next, b"second original")?;
    assert!(store.verified_replay.is_none());
    assert_eq!(store.read_current_anchor()?, store.anchor());
    assert_eq!(
        store.readback(&operation)?,
        State::Completed(b"original".to_vec())
    );
    assert_eq!(
        store.readback(&next)?,
        State::Completed(b"second original".to_vec())
    );
    Ok(())
}

#[test]
fn warmed_replay_still_reads_same_length_corruption_and_stays_poisoned()
-> Result<(), Box<dyn StdError>> {
    let file = TempJournal::new();
    let mut store = file.create();
    let operation = key("completed");
    store.claim(&operation)?;
    store.complete(&operation, b"original")?;
    store.read_current_anchor()?;
    let _retained_parse = cached(&store)?;
    let original = image(&mut store)?;
    let mut corrupted = original.clone();
    let last = corrupted.len() - 1;
    corrupted[last] ^= 1;
    overwrite(&mut store, &corrupted)?;
    store.file.seek(SeekFrom::Start(13))?;
    assert_eq!(store.read_current_anchor(), Err(FileError::Corrupt));
    assert_eq!(store.file.stream_position()?, 13);
    assert_eq!(image(&mut store)?, corrupted);
    overwrite(&mut store, &original)?;
    assert_eq!(store.read_current_anchor(), Err(FileError::Indeterminate));
    assert_eq!(store.readback(&operation), Err(StoreError::Indeterminate));
    assert_eq!(
        store.claim(&key("forbidden")),
        Err(StoreError::Indeterminate)
    );
    Ok(())
}

#[test]
fn warmed_replay_rejects_a_valid_rehashed_same_length_replacement() -> Result<(), Box<dyn StdError>>
{
    let original_file = TempJournal::new();
    let replacement_file = TempJournal::new();
    let mut original = original_file.create();
    let mut replacement = replacement_file.create();
    let operation = key("completed");
    for store in [&mut original, &mut replacement] {
        store.claim(&operation)?;
    }
    original.complete(&operation, b"accepted")?;
    replacement.complete(&operation, b"rejected")?;
    original.read_current_anchor()?;
    let _retained_parse = cached(&original)?;
    let before = image(&mut original)?;
    let changed = image(&mut replacement)?;
    assert_eq!(before.len(), changed.len());
    overwrite(&mut original, &changed)?;
    assert_eq!(original.read_current_anchor(), Err(FileError::Rollback));
    overwrite(&mut original, &before)?;
    assert_eq!(
        original.readback(&operation),
        Err(StoreError::Indeterminate)
    );
    Ok(())
}

#[test]
fn warmed_replay_does_not_bypass_retained_binding_anchor_digest_or_record_checks()
-> Result<(), Box<dyn StdError>> {
    for field in ["binding", "anchor", "digest", "record"] {
        let file = TempJournal::new();
        let mut store = file.create();
        let operation = key("completed");
        store.claim(&operation)?;
        store.complete(&operation, b"original")?;
        store.read_current_anchor()?;
        let _retained_parse = cached(&store)?;
        let original = image(&mut store)?;
        match field {
            "binding" => store.binding = digest("different binding"),
            "anchor" => store.anchor.sequence += 1,
            "digest" => store.image_digest = digest("different image"),
            "record" => {
                store.records.insert(
                    operation.plan_id.clone(),
                    (
                        operation.binding_digest,
                        State::Completed(b"tampered".to_vec()),
                    ),
                );
            }
            _ => unreachable!("fixed fixture field"),
        }
        assert!(store.read_current_anchor().is_err(), "accepted {field}");
        assert_eq!(store.readback(&operation), Err(StoreError::Indeterminate));
        assert_eq!(image(&mut store)?, original);
    }
    Ok(())
}

#[test]
fn warmed_replay_cannot_hide_original_descriptor_read_failure() -> Result<(), Box<dyn StdError>> {
    let file = TempJournal::new();
    let mut store = file.create();
    store.read_current_anchor()?;
    let _retained_parse = cached(&store)?;
    // Inject only the descriptor failure inside this private fixture. Keep the
    // actual original locked descriptor alive and restore it after the failure.
    let unreadable = OpenOptions::new().write(true).open(&file.0)?;
    let original = std::mem::replace(&mut store.file, HeldFile(unreadable));
    assert!(matches!(store.read_current_anchor(), Err(FileError::Io(_))));
    store.file = original;
    assert_eq!(store.read_current_anchor(), Err(FileError::Indeterminate));
    assert_eq!(
        store.claim(&key("forbidden")),
        Err(StoreError::Indeterminate)
    );
    Ok(())
}

#[test]
fn large_valid_images_keep_complete_replay_without_retaining_a_large_memo()
-> Result<(), Box<dyn StdError>> {
    let file = TempJournal::new();
    let mut store = file.create();
    let payload = vec![b'x'; MAX_PRODUCT_EVALUATION_EXECUTION_BYTES_V1];
    for index in 0..=MAX_VERIFIED_REPLAY_IMAGE_BYTES / payload.len() {
        let operation = key(&format!("large-{index}"));
        store.claim(&operation)?;
        store.complete(&operation, &payload)?;
    }
    let original = image(&mut store)?;
    assert!(original.len() > MAX_VERIFIED_REPLAY_IMAGE_BYTES);
    let anchor = store.anchor();
    for _ in 0..2 {
        assert_eq!(store.read_current_anchor()?, anchor);
        assert!(store.verified_replay.is_none());
        assert_eq!(
            store.readback(&key("large-0"))?,
            State::Completed(payload.clone())
        );
        assert!(store.verified_replay.is_none());
        assert_eq!(image(&mut store)?, original);
    }
    Ok(())
}
