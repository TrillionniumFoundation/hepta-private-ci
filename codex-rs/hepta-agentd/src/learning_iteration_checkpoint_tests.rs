use std::sync::Arc;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;

#[path = "learning_iteration_checkpoint_test_support.rs"]
mod support;
use support::Decision;
use support::FileCas;
use support::OWNER;
use support::owner;
use support::snapshots;

#[test]
fn maximum_legal_snapshots_roundtrip_all_decisions_inside_original_root_bound() -> anyhow::Result<()>
{
    for decision in [
        Decision::Update,
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
    ] {
        let snapshots = snapshots(decision)?;
        for snapshot in &snapshots {
            let bytes = codec::encode(snapshot)?;
            assert_eq!(codec::decode(&bytes)?, *snapshot);
        }
        let last = snapshots.last().unwrap();
        let bytes = codec::encode(last)?;
        let expected_bytes = match decision {
            Decision::EvaluatedNoUpdate => 6420,
            Decision::Update | Decision::ProposedNoUpdate => 6945,
        };
        assert_eq!(bytes.len(), expected_bytes);
        let record = LearningIterationCheckpointRecordV1 {
            schema: 1,
            binding: snapshots[0].head_digest.to_string(),
            predecessor: last.receipts.last().unwrap().predecessor.to_string(),
            snapshot: Some(STANDARD_NO_PAD.encode(bytes)),
        };
        // Same complete envelope fields as HostAuthorityFrontierStore::persist,
        // including the longest legal original owner identifier.
        let outer = serde_json::to_vec(&serde_json::json!({
            "schema": 1, "owner_id": "x".repeat(128), "frontier": record,
        }))?;
        assert!(outer.len() < 16 * 1024);
    }
    Ok(())
}

#[test]
fn malformed_counts_strings_tags_and_truncated_checkpoints_are_rejected() -> anyhow::Result<()> {
    let snapshots = snapshots(Decision::Update)?;
    let initial = codec::encode(&snapshots[0])?;
    let count_offset = initial.len() - 33;
    let mut oversized_count = initial.clone();
    oversized_count[count_offset] = 8;
    assert_eq!(codec::decode(&oversized_count), Err(Error::Capacity));
    let mut oversized_id = initial.clone();
    oversized_id[8] = 129;
    assert_eq!(codec::decode(&oversized_id), Err(Error::Capacity));
    assert_eq!(
        codec::decode(&vec![0; codec::MAX_BYTES + 1]),
        Err(Error::Capacity)
    );
    for end in [0, 8, initial.len() - 1] {
        assert!(codec::decode(&initial[..end]).is_err());
    }
    let mut trailing = initial;
    trailing.push(0);
    assert_eq!(codec::decode(&trailing), Err(Error::InvalidRecord));
    let mut wrong_tag = codec::encode(&snapshots[1])?;
    let receipt = &snapshots[1].receipts[0];
    let observation_offset = count_offset
        + 1
        + 1
        + receipt.operation_id.as_str().len()
        + 32
        + 1
        + receipt.actor_id.as_str().len()
        + 32
        + 8;
    wrong_tag[observation_offset] = 8;
    assert_eq!(codec::decode(&wrong_tag), Err(Error::InvalidRecord));
    let last = wrong_tag.len() - 1;
    wrong_tag[observation_offset] = 0;
    wrong_tag[last] ^= 1;
    assert!(matches!(codec::decode(&wrong_tag), Err(Error::Snapshot(_))));
    Ok(())
}

#[test]
fn each_checkpoint_reopens_and_exact_retry_performs_no_second_cas() -> anyhow::Result<()> {
    for decision in [
        Decision::Update,
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
    ] {
        let snapshots = snapshots(decision)?;
        let initial = &snapshots[0];
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original-frontier");
        let vacant = LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?;
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        assert_eq!(owner(store, initial).restore(&initial.request)?, None);
        for (index, snapshot) in snapshots.iter().enumerate() {
            let store = Arc::new(FileCas::reopen(&path)?);
            let current = owner(store.clone(), initial);
            let expected = if index == 0 {
                Digest32::ZERO
            } else {
                snapshots[index - 1].head_digest
            };
            assert_eq!(
                current.checkpoint(expected, snapshot)?,
                snapshot.head_digest
            );
            let durable_bytes = std::fs::read(&path)?;
            assert_eq!(
                current.checkpoint(expected, snapshot)?,
                snapshot.head_digest
            );
            assert_eq!(store.commits.load(Ordering::SeqCst), 1);
            assert_eq!(std::fs::read(&path)?, durable_bytes);
            drop(current);
            drop(store);
            let reopened = owner(Arc::new(FileCas::reopen(&path)?), initial);
            assert_eq!(reopened.restore(&initial.request)?, Some(snapshot.clone()));
        }
        let completed = owner(Arc::new(FileCas::reopen(&path)?), initial);
        assert_eq!(
            completed.checkpoint(Digest32::ZERO, initial),
            Err(Error::Conflict)
        );
        assert_eq!(
            completed.restore(&initial.request)?,
            snapshots.last().cloned()
        );
    }
    Ok(())
}

#[test]
fn foreign_owner_request_skipped_stage_and_divergent_successor_leave_current_unchanged()
-> anyhow::Result<()> {
    let snapshots = snapshots(Decision::Update)?;
    let initial = &snapshots[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(&path, &vacant)?);
    let current = owner(store.clone(), initial);
    current.checkpoint(Digest32::ZERO, initial)?;
    let second_store = Arc::new(FileCas::reopen(&path)?);
    let mut reopened = owner(second_store.clone(), initial);
    assert_eq!(reopened.restore(&initial.request)?, Some(initial.clone()));
    assert_eq!(
        reopened.checkpoint(snapshots[1].head_digest, &snapshots[2]),
        Err(Error::Conflict)
    );
    current.checkpoint(initial.head_digest, &snapshots[1])?;
    let mut branch = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
    let mut receipt = snapshots[1].receipts[0].clone();
    receipt.evidence_digest = Digest32::of_bytes(b"different actual receipt");
    branch.record(receipt, 20)?;
    assert_eq!(
        reopened.checkpoint(initial.head_digest, branch.snapshot()),
        Err(Error::Conflict)
    );
    assert_eq!(
        reopened.checkpoint(Digest32::ZERO, initial),
        Err(Error::Conflict)
    );
    let mut foreign = initial.request.clone();
    foreign.operation_id = codex_hepta_types::StableId::new("other-operation")?;
    assert_eq!(reopened.restore(&foreign), Err(Error::WrongScope));
    reopened.owner_id = "foreign-owner".into();
    assert_eq!(
        reopened.restore(&initial.request),
        Err(Error::Store(AuthorityTrustError::Invalid))
    );
    reopened.owner_id = OWNER.into();
    assert_eq!(
        reopened.restore(&initial.request)?,
        Some(snapshots[1].clone())
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 2);
    assert_eq!(second_store.commits.load(Ordering::SeqCst), 0);
    Ok(())
}

#[test]
fn valid_json_with_corrupt_protected_record_metadata_is_never_restored() -> anyhow::Result<()> {
    let snapshots = snapshots(Decision::Update)?;
    let initial = &snapshots[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(&path, &vacant)?);
    owner(store.clone(), initial).checkpoint(Digest32::ZERO, initial)?;
    let original = store.load(OWNER)?;
    drop(store);
    type Mutation = fn(&mut LearningIterationCheckpointRecordV1);
    let cases: [(&str, Mutation, Error); 5] = [
        ("schema", |record| record.schema = 2, Error::WrongScope),
        (
            "binding",
            |record| record.binding = Digest32::of_bytes(b"other binding").to_string(),
            Error::WrongScope,
        ),
        (
            "predecessor",
            |record| record.predecessor = Digest32::of_bytes(b"other predecessor").to_string(),
            Error::InvalidRecord,
        ),
        (
            "invalid-base64",
            |record| record.snapshot = Some("%%%".into()),
            Error::InvalidRecord,
        ),
        (
            "noncanonical-base64",
            |record| record.snapshot.as_mut().unwrap().push('='),
            Error::InvalidRecord,
        ),
    ];
    for (label, mutate, expected) in cases {
        let mut corrupt = original.clone();
        mutate(&mut corrupt);
        let bytes = serde_json::to_vec(&corrupt)?;
        assert_eq!(
            serde_json::from_slice::<LearningIterationCheckpointRecordV1>(&bytes)?,
            corrupt
        );
        std::fs::write(&path, &bytes)?;
        std::fs::File::open(&path)?.sync_all()?;
        let reopened = owner(Arc::new(FileCas::reopen(&path)?), initial);
        assert_eq!(reopened.restore(&initial.request), Err(expected), "{label}");
        assert_eq!(std::fs::read(&path)?, bytes);
    }
    Ok(())
}

#[test]
fn write_failure_and_lost_ack_reconcile_original_record_without_reexecution() -> anyhow::Result<()>
{
    let snapshots = snapshots(Decision::Update)?;
    let initial = &snapshots[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-frontier");
    let vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let store = Arc::new(FileCas::create(&path, &vacant)?);
    let current = owner(store.clone(), initial);
    store.failure.store(1, Ordering::SeqCst);
    assert_eq!(
        current.checkpoint(Digest32::ZERO, initial),
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert_eq!(current.restore(&initial.request)?, None);
    assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    current.checkpoint(Digest32::ZERO, initial)?;
    store.failure.store(2, Ordering::SeqCst);
    assert_eq!(
        current.checkpoint(initial.head_digest, &snapshots[1]),
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert_eq!(store.commits.load(Ordering::SeqCst), 2);
    drop(current);
    drop(store);
    let reopened_store = Arc::new(FileCas::reopen(&path)?);
    let reopened = owner(reopened_store.clone(), initial);
    assert_eq!(
        reopened.restore(&initial.request)?,
        Some(snapshots[1].clone())
    );
    assert_eq!(
        reopened.checkpoint(initial.head_digest, &snapshots[1])?,
        snapshots[1].head_digest
    );
    assert_eq!(reopened_store.commits.load(Ordering::SeqCst), 0);
    reopened.checkpoint(snapshots[1].head_digest, &snapshots[2])?;
    assert_eq!(reopened_store.commits.load(Ordering::SeqCst), 1);
    std::fs::write(&path, b"{truncated")?;
    assert_eq!(
        reopened.restore(&initial.request),
        Err(Error::Store(AuthorityTrustError::Invalid))
    );
    assert_eq!(
        reopened.checkpoint(Digest32::ZERO, initial),
        Err(Error::Store(AuthorityTrustError::Invalid))
    );
    drop(reopened);
    drop(reopened_store);
    std::fs::remove_file(&path)?;
    assert!(FileCas::reopen(&path).is_err());
    Ok(())
}
