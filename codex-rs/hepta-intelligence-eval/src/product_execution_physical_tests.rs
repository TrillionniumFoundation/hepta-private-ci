use pretty_assertions::assert_eq;

use super::*;

fn image(store: &mut LockedFileProductEvaluationExecutionStoreV1) -> io::Result<Vec<u8>> {
    store.file.seek(SeekFrom::Start(0))?;
    let mut bytes = Vec::new();
    store.file.read_to_end(&mut bytes)?;
    Ok(bytes)
}

fn overwrite(
    store: &mut LockedFileProductEvaluationExecutionStoreV1,
    bytes: &[u8],
) -> io::Result<()> {
    store.file.seek(SeekFrom::Start(0))?;
    store.file.write_all(bytes)?;
    store.file.sync_all()
}

#[test]
fn execution_current_completed_corruption_then_restore_refuses_same_handle()
-> Result<(), Box<dyn StdError>> {
    let journal = TempJournal::new();
    let mut store = journal.create();
    let operation = key("actual-completion");
    assert_eq!(
        store.claim(&operation)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    store.complete(&operation, b"original signed completion bytes")?;
    assert_eq!(
        store.readback(&operation)?,
        State::Completed(b"original signed completion bytes".to_vec())
    );
    let minimum = store.anchor();
    let original = image(&mut store)?;
    let mut corrupt = original.clone();
    corrupt[HEADER + 8] ^= 1;
    overwrite(&mut store, &corrupt)?;
    assert_eq!(store.readback(&operation), Err(StoreError::Indeterminate));
    overwrite(&mut store, &original)?;
    assert_eq!(store.readback(&operation), Err(StoreError::Indeterminate));
    assert_eq!(image(&mut store)?, original);
    drop(store);
    // The external minimum permits a new owner of the restored valid bytes.
    // This deliberately does not assert a persistent cross-process refusal.
    let mut reopened = journal.recover(minimum)?;
    assert_eq!(
        reopened.readback(&operation)?,
        State::Completed(b"original signed completion bytes".to_vec())
    );
    Ok(())
}

#[test]
fn execution_current_pending_corruption_then_restore_refuses_same_handle()
-> Result<(), Box<dyn StdError>> {
    let journal = TempJournal::new();
    let mut store = journal.create();
    let operation = key("actual-pending");
    assert_eq!(
        store.claim(&operation)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    assert_eq!(store.readback(&operation)?, State::Pending);
    let original = image(&mut store)?;
    let mut corrupt = original.clone();
    corrupt[HEADER + 6] ^= 1;
    overwrite(&mut store, &corrupt)?;
    assert_eq!(store.readback(&operation), Err(StoreError::Indeterminate));
    overwrite(&mut store, &original)?;
    assert_eq!(store.claim(&operation), Err(StoreError::Indeterminate));
    assert_eq!(
        store.complete(&operation, b"forbidden completion"),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(image(&mut store)?, original);
    Ok(())
}

#[test]
fn execution_current_idempotent_completion_checks_physical_original()
-> Result<(), Box<dyn StdError>> {
    let journal = TempJournal::new();
    let mut store = journal.create();
    let operation = key("actual-idempotent");
    assert_eq!(
        store.claim(&operation)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    store.complete(&operation, b"original signed completion")?;
    store.complete(&operation, b"original signed completion")?;
    let original = image(&mut store)?;
    let mut corrupt = original.clone();
    corrupt[0] ^= 1;
    overwrite(&mut store, &corrupt)?;
    assert_eq!(
        store.complete(&operation, b"original signed completion"),
        Err(StoreError::Indeterminate)
    );
    overwrite(&mut store, &original)?;
    assert_eq!(
        store.complete(&operation, b"original signed completion"),
        Err(StoreError::Indeterminate)
    );
    assert_eq!(image(&mut store)?, original);
    Ok(())
}

#[test]
fn execution_current_new_claim_cannot_append_after_same_length_corruption()
-> Result<(), Box<dyn StdError>> {
    let journal = TempJournal::new();
    let mut store = journal.create();
    let operation = key("original-pending");
    assert_eq!(
        store.claim(&operation)?,
        ProductEvaluationExecutionClaimV1::Claimed
    );
    assert_eq!(store.readback(&operation)?, State::Pending);
    let original = image(&mut store)?;
    let mut corrupt = original.clone();
    corrupt[HEADER - 1] ^= 1;
    overwrite(&mut store, &corrupt)?;
    let next = key("not-yet-claimed");
    assert_eq!(store.claim(&next), Err(StoreError::Indeterminate));
    assert_eq!(image(&mut store)?, corrupt);
    overwrite(&mut store, &original)?;
    assert_eq!(store.claim(&next), Err(StoreError::Indeterminate));
    assert_eq!(image(&mut store)?, original);
    Ok(())
}
