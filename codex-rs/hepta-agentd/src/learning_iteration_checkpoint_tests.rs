use std::sync::Arc;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::*;

#[path = "learning_iteration_checkpoint_test_support.rs"]
mod support;
use support::Decision;
use support::FileCas;
use support::owner;
use support::snapshots;

#[test]
fn maximum_legal_snapshots_roundtrip_all_decisions_inside_original_root_bound() -> anyhow::Result<()> {
    for decision in [Decision::Update, Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
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
            schema: 1, binding: snapshots[0].head_digest.to_string(),
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
fn each_checkpoint_reopens_and_exact_retry_performs_no_second_cas() -> anyhow::Result<()> {
    for decision in [Decision::Update, Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
        let snapshots = snapshots(decision)?;
        let initial = &snapshots[0];
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original-frontier");
        let vacant = LearningIterationCheckpointRecordV1::vacant(initial.request.clone(), initial.owners.clone())?;
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        assert_eq!(owner(store, initial).restore(&initial.request)?, None);
        for (index, snapshot) in snapshots.iter().enumerate() {
            let store = Arc::new(FileCas::reopen(&path)?);
            let current = owner(store.clone(), initial);
            let expected = if index == 0 { Digest32::ZERO } else { snapshots[index - 1].head_digest };
            assert_eq!(current.checkpoint(expected, snapshot)?, snapshot.head_digest);
            let durable_bytes = std::fs::read(&path)?;
            assert_eq!(current.checkpoint(expected, snapshot)?, snapshot.head_digest);
            assert_eq!(store.commits.load(Ordering::SeqCst), 1);
            assert_eq!(std::fs::read(&path)?, durable_bytes);
            drop(current);
            drop(store);
            let reopened = owner(Arc::new(FileCas::reopen(&path)?), initial);
            assert_eq!(reopened.restore(&initial.request)?, Some(snapshot.clone()));
        }
        let completed = owner(Arc::new(FileCas::reopen(&path)?), initial);
        assert_eq!(completed.checkpoint(Digest32::ZERO, initial), Err(Error::Conflict));
        assert_eq!(completed.restore(&initial.request)?, snapshots.last().cloned());
    }
    Ok(())
}
