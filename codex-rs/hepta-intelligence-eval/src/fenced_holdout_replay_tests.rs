use super::super::replay::replay_event_owned;
use super::super::replay::transition_payload;
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn owned_replay_preserves_reverse_prefixes_and_reuses_fence_allocation() {
    let binding = digest("binding");
    let mut native = FinalHoldoutJournalV1::new();
    let mut reference = FinalHoldoutJournalV1::new();
    let initial = FinalHoldoutCasRecordV1::new(
        binding,
        HoldoutWriterFenceV1 {
            owner_id: id("owned-replay-owner"),
            generation: 1,
            lease_digest: digest("owned-replay-lease"),
        },
        reference.snapshot(),
    )
    .unwrap_or_else(|error| panic!("initial reference: {error:?}"));
    let payload = transition_payload(/*current*/ None, &initial)
        .unwrap_or_else(|error| panic!("initial payload: {error:?}"));
    let mut current = replay_event_owned(binding, /*current*/ None, &mut native, &payload)
        .unwrap_or_else(|error| panic!("initial replay: {error:?}"));
    assert_eq!(current, initial);

    for name in ["z-plan", "m-plan", "a-plan"] {
        reference
            .consume(reference.head_digest(), &plan(name))
            .unwrap_or_else(|error| panic!("strict reference prefix: {error:?}"));
        let expected =
            FinalHoldoutCasRecordV1::new(binding, current.fence.clone(), reference.snapshot())
                .unwrap_or_else(|error| panic!("reference plan state: {error:?}"));
        let payload = transition_payload(Some(&current), &expected)
            .unwrap_or_else(|error| panic!("plan payload: {error:?}"));
        current = replay_event_owned(binding, Some(current), &mut native, &payload)
            .unwrap_or_else(|error| panic!("owned plan replay: {error:?}"));
        assert_eq!(current, expected);
        let strict = FinalHoldoutJournalV1::from_snapshot(current.journal.clone())
            .unwrap_or_else(|error| panic!("strict public snapshot replay: {error:?}"));
        assert_eq!(native.snapshot(), strict.snapshot());

        // These are real nonempty snapshots; a fence must move the allocation
        // rather than deep-cloning its complete canonical history.
        let allocation = current.journal.records.as_ptr();
        let capacity = current.journal.records.capacity();
        let mut fence = current.fence.clone();
        fence.generation += 1;
        let expected = FinalHoldoutCasRecordV1::new(binding, fence, reference.snapshot())
            .unwrap_or_else(|error| panic!("reference fence state: {error:?}"));
        let payload = transition_payload(Some(&current), &expected)
            .unwrap_or_else(|error| panic!("fence payload: {error:?}"));
        current = replay_event_owned(binding, Some(current), &mut native, &payload)
            .unwrap_or_else(|error| panic!("owned fence replay: {error:?}"));
        assert_eq!(current, expected);
        assert_eq!(current.journal.records.as_ptr(), allocation);
        assert_eq!(current.journal.records.capacity(), capacity);
    }
}

#[test]
fn reverse_ordered_cold_recovery_retains_interleaved_prefix_and_exact_retry() {
    let temp = TempFile::new();
    let binding = digest("binding");
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), binding)
        .unwrap_or_else(|error| panic!("create reverse-order store: {error:?}"));
    let mut writer = owner(store, /*minimum*/ None);
    writer
        .consume(&plan("z-plan"))
        .unwrap_or_else(|error| panic!("first reverse plan: {error:?}"));
    let prefix = writer.anchor();
    let backup =
        fs::read(&temp.path).unwrap_or_else(|error| panic!("retained prefix bytes: {error:?}"));
    for name in ["m-plan", "a-plan"] {
        let minimum = writer.anchor();
        writer = owner(writer.into_store(), Some(minimum));
        writer
            .consume(&plan(name))
            .unwrap_or_else(|error| panic!("later reverse plan: {error:?}"));
    }
    let final_anchor = writer.anchor();
    let mut store = writer.into_store();
    let expected = store
        .load(binding)
        .unwrap_or_else(|error| panic!("canonical live state: {error:?}"))
        .unwrap_or_else(|| panic!("live state is present"));
    drop(store);
    let original =
        fs::read(&temp.path).unwrap_or_else(|error| panic!("complete original bytes: {error:?}"));
    let mut recovered =
        LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), binding, Some(prefix))
            .unwrap_or_else(|error| panic!("recover witnessed interleaved prefix: {error:?}"));
    assert_eq!(recovered.load(binding), Ok(Some(expected.clone())));
    let mut retry = FencedFinalHoldoutOwnerV1::recover(recovered, binding, expected.fence.clone())
        .unwrap_or_else(|error| panic!("resume same canonical fence: {error:?}"));
    let receipt = retry
        .consume(&plan("a-plan"))
        .unwrap_or_else(|error| panic!("exact retry after cold recovery: {error:?}"));
    assert_eq!(
        receipt.disposition,
        crate::HoldoutUseDispositionV1::IdempotentReplay
    );
    assert_eq!(retry.anchor(), final_anchor);
    assert_eq!(fs::read(&temp.path).ok(), Some(original.clone()));
    drop(retry);

    fs::write(&temp.path, &backup)
        .unwrap_or_else(|error| panic!("restore valid older prefix: {error:?}"));
    assert_eq!(
        LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), binding, Some(final_anchor)).err(),
        Some(LockedFileCasErrorV1::Rollback)
    );
    assert_eq!(fs::read(&temp.path).ok(), Some(backup));
    fs::write(&temp.path, &original)
        .unwrap_or_else(|error| panic!("restore exact complete history: {error:?}"));
    let mut restored =
        LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), binding, Some(final_anchor))
            .unwrap_or_else(|error| panic!("recover restored complete history: {error:?}"));
    assert_eq!(restored.load(binding), Ok(Some(expected)));
}

#[test]
fn duplicate_and_rehashed_fork_frames_cannot_escape_failed_cold_recovery() {
    let temp = TempFile::new();
    let binding = digest("binding");
    let store = LockedFileFinalHoldoutCasStoreV1::create(temp.create(), binding)
        .unwrap_or_else(|error| panic!("create fault store: {error:?}"));
    let mut writer = owner(store, /*minimum*/ None);
    writer
        .consume(&plan("z-plan"))
        .unwrap_or_else(|error| panic!("original plan: {error:?}"));
    let minimum = writer.anchor();
    let mut store = writer.into_store();
    let expected = store
        .load(binding)
        .unwrap_or_else(|error| panic!("expected state: {error:?}"));
    drop(store);
    let original =
        fs::read(&temp.path).unwrap_or_else(|error| panic!("original wire bytes: {error:?}"));
    let fence_len = u32::from_be_bytes(
        original[HEADER..HEADER + 4]
            .try_into()
            .unwrap_or_else(|error| panic!("fence length: {error:?}")),
    ) as usize;
    let plan_start = HEADER + 4 + fence_len + 32;
    let mut duplicate = original.clone();
    duplicate.extend_from_slice(&original[plan_start..]);
    let mut payload = vec![EVENT_PLAN];
    payload.extend_from_slice(
        &encode_holdout_plan(&plan("y-plan"))
            .unwrap_or_else(|error| panic!("valid alternate plan: {error:?}")),
    );
    let mut fork = original[..plan_start].to_vec();
    fork.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    fork.extend_from_slice(&payload);
    fork.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    assert_eq!(fork.len(), original.len());

    for (bytes, error) in [
        (duplicate, LockedFileCasErrorV1::Corrupt),
        (fork, LockedFileCasErrorV1::Rollback),
    ] {
        fs::write(&temp.path, &bytes)
            .unwrap_or_else(|error| panic!("install complete fault history: {error:?}"));
        assert_eq!(
            LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), binding, Some(minimum)).err(),
            Some(error)
        );
        assert_eq!(fs::read(&temp.path).ok(), Some(bytes));
        fs::write(&temp.path, &original)
            .unwrap_or_else(|error| panic!("restore canonical history after failure: {error:?}"));
        let mut restored =
            LockedFileFinalHoldoutCasStoreV1::recover(temp.open(), binding, Some(minimum))
                .unwrap_or_else(|error| panic!("recover restored canonical history: {error:?}"));
        assert_eq!(restored.load(binding), Ok(expected.clone()));
        assert_eq!(
            Some(restored.journal.snapshot()),
            expected.as_ref().map(|record| record.journal.clone())
        );
    }
}
