//! Frozen evaluator identity across the existing protected checkpoint owner.
//! FileCas is the original fsync fixture; it grants no production authority.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationDispositionV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;

use super::support::Decision;
use super::support::FileCas;
use super::support::OWNER;
use super::support::owner;
use super::support::snapshots;

#[test]
fn changed_frozen_profile_cannot_restore_or_replace_the_original_checkpoint() -> anyhow::Result<()>
{
    let snapshots = snapshots(Decision::Update)?;
    let initial = &snapshots[0];
    let trained = &snapshots[3];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(&path, &vacant)?);
    let current = owner(store.clone(), initial);
    let mut previous = Digest32::ZERO;
    for snapshot in &snapshots[..=3] {
        current.checkpoint(previous, snapshot)?;
        previous = snapshot.head_digest;
    }
    let retained_bytes = std::fs::read(&path)?;
    let retained_commits = store.commits.load(Ordering::SeqCst);
    let mut changed = trained.clone();
    changed.request.evaluation_profile = Digest32::of_bytes(b"different-frozen-evaluation");
    assert!(LearningIterationCoordinatorV1::from_snapshot(changed.clone()).is_err());
    assert_eq!(current.restore(&changed.request), Err(Error::WrongScope));
    assert_eq!(
        current.checkpoint(trained.head_digest, &changed),
        Err(Error::WrongScope)
    );
    let replacement =
        LearningIterationCoordinatorV1::new(changed.request.clone(), initial.owners.clone())?;
    assert_ne!(replacement.snapshot().head_digest, initial.head_digest);
    let second_store = Arc::new(FileCas::reopen(&path)?);
    let changed_owner = owner(second_store.clone(), replacement.snapshot());
    assert_eq!(
        changed_owner.restore(&changed.request),
        Err(Error::WrongScope)
    );
    assert_eq!(second_store.commits.load(Ordering::SeqCst), 0);
    assert_eq!(store.commits.load(Ordering::SeqCst), retained_commits);
    assert_eq!(std::fs::read(&path)?, retained_bytes);
    assert_eq!(current.restore(&initial.request)?, Some(trained.clone()));
    Ok(())
}

#[test]
fn previous_or_missing_profile_bytes_are_refused_in_both_outer_schemas() -> anyhow::Result<()> {
    let snapshots = snapshots(Decision::Update)?;
    let initial = &snapshots[0];
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    for index in [0, 3] {
        let snapshot = &snapshots[index];
        let mut legacy_tag = codec::encode(snapshot)?;
        assert_eq!(&legacy_tag[..8], b"HEPLCP02");
        legacy_tag[..8].copy_from_slice(b"HEPLCP01");
        assert_eq!(codec::decode(&legacy_tag), Err(Error::InvalidRecord));
        // Even the new tag cannot supply an omitted profile by inference.
        let mut missing_profile = codec::encode(snapshot)?;
        let request = &snapshot.request;
        let profile_offset = 8 + 64 + [
            &request.operation_id, &request.principal_id, &request.agent_id,
            &request.cell_id, &request.source_run_id,
        ].iter().map(|id| 1 + id.as_str().len()).sum::<usize>();
        missing_profile.drain(profile_offset..profile_offset + 32);
        for wire in [legacy_tag, missing_profile] {
            let error = codec::decode(&wire).expect_err("missing original profile");
            for scope in [None, Some(scope.clone())] {
                let record = LearningIterationCheckpointRecordV1 {
                    schema: if scope.is_some() { 2 } else { 1 },
                    binding: scope.as_ref().map_or(initial.head_digest, FrozenLearningScopeV2::binding).to_string(),
                    predecessor: snapshot.receipts.last().map_or(Digest32::ZERO, |receipt| receipt.predecessor).to_string(),
                    snapshot: Some(STANDARD_NO_PAD.encode(&wire)),
                };
                let directory = tempfile::tempdir()?;
                let path = directory.path().join("missing-original-profile");
                let store = Arc::new(FileCas::create(&path, &record)?);
                let retained_bytes = std::fs::read(&path)?;
                let current = LearningIterationCheckpointOwnerV1 {
                    owner_id: OWNER.into(),
                    store: Store::Test(store.clone()),
                    initial: initial.clone(),
                    scope,
                };
                assert_eq!(current.restore(&initial.request), Err(error.clone()));
                assert_eq!(current.checkpoint(snapshot.head_digest, &snapshots[index + 1]), Err(error.clone()));
                assert_eq!(store.commits.load(Ordering::SeqCst), 0);
                assert_eq!(std::fs::read(&path)?, retained_bytes);
            }
        }
    }
    Ok(())
}

#[test]
fn both_no_update_paths_keep_the_frozen_profile_and_full_parent_after_cold_reopen()
-> anyhow::Result<()> {
    for decision in [Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
        let snapshots = snapshots(decision)?;
        let initial = &snapshots[0];
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original-frontier");
        let vacant = LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?;
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        let current = owner(store.clone(), initial);
        let mut previous = Digest32::ZERO;
        for snapshot in &snapshots {
            current.checkpoint(previous, snapshot)?;
            previous = snapshot.head_digest;
        }
        let retained_bytes = std::fs::read(&path)?;
        drop(current);
        drop(store);
        let reopened_store = Arc::new(FileCas::reopen(&path)?);
        let reopened = owner(reopened_store.clone(), initial);
        let restored = reopened.restore(&initial.request)?.unwrap();
        assert_eq!(&restored, snapshots.last().unwrap());
        assert_eq!(
            restored.request.evaluation_profile,
            initial.request.evaluation_profile
        );
        let completed = LearningIterationCoordinatorV1::from_snapshot(restored.clone())?;
        assert_eq!(completed.next_stage(), None);
        assert_eq!(
            completed.disposition(),
            LearningIterationDispositionV1::UsedByNextTask
        );
        assert_eq!(
            completed.next_task_bundle(),
            Some(&initial.request.selected_bundle)
        );
        let wire = codec::encode(&restored)?;
        assert_eq!(&wire[..8], b"HEPLCP02");
        assert_eq!(codec::decode(&wire)?, restored);
        assert_eq!(reopened_store.commits.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read(&path)?, retained_bytes);
    }
    Ok(())
}
