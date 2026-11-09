use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;
#[path = "learning_iteration_checkpoint_test_support.rs"]
mod support;
use support::{Decision, FileCas, OWNER, owner, snapshots};

#[test]
fn scoped_checkpoint_reopens_all_decisions_and_refuses_profile_downgrade() -> anyhow::Result<()> {
    for decision in [Decision::Update, Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
        let cuts = snapshots(decision)?;
        let initial = &cuts[0];
        let scope = FrozenLearningScopeV2::freeze(&initial.request, &initial.owners, LearningUpdateScopeV2::Cell, Digest32::of_bytes(b"rule"))?;
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("scope-root");
        let vacant = LearningIterationCheckpointRecordV1::vacant_scoped_v2(initial.request.clone(), initial.owners.clone(), &scope)?;
        FileCas::create(&path, &vacant)?;
        for (index, cut) in cuts.iter().enumerate() {
            let store = Arc::new(FileCas::reopen(&path)?);
            let current = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(store.clone(), OWNER.into(), initial.request.clone(), initial.owners.clone(), scope.clone())?;
            let expected = if index == 0 { Digest32::ZERO } else { cuts[index - 1].head_digest };
            assert_eq!(current.checkpoint(expected, cut)?, cut.head_digest);
            let bytes = std::fs::read(&path)?;
            assert_eq!(current.checkpoint(expected, cut)?, cut.head_digest);
            assert_eq!(store.commits.load(Ordering::SeqCst), 1);
            assert_eq!(std::fs::read(&path)?, bytes);
            let reopened = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(Arc::new(FileCas::reopen(&path)?), OWNER.into(), initial.request.clone(), initial.owners.clone(), scope.clone())?;
            assert_eq!(reopened.restore(&initial.request)?, Some(cut.clone()));
        }
        let bytes = std::fs::read(&path)?;
        assert_eq!(owner(Arc::new(FileCas::reopen(&path)?), initial).restore(&initial.request), Err(Error::WrongScope));
        let organ = FrozenLearningScopeV2::freeze(&initial.request, &initial.owners, LearningUpdateScopeV2::Organ, Digest32::of_bytes(b"rule"))?;
        assert!(matches!(LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(Arc::new(FileCas::reopen(&path)?), OWNER.into(), initial.request.clone(), initial.owners.clone(), organ), Err(Error::WrongScope)));
        assert_eq!(std::fs::read(&path)?, bytes);
        let legacy = directory.path().join("legacy-root");
        let vacant = LearningIterationCheckpointRecordV1::vacant(initial.request.clone(), initial.owners.clone())?;
        let store = Arc::new(FileCas::create(&legacy, &vacant)?);
        let bytes = std::fs::read(&legacy)?;
        let legacy_owner = LearningIterationCheckpointOwnerV1::from_research_store(store.clone(), OWNER.into(), initial.request.clone(), initial.owners.clone())?;
        assert_eq!(legacy_owner.restore(&initial.request)?, None);
        assert!(matches!(LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(store, OWNER.into(), initial.request.clone(), initial.owners.clone(), scope), Err(Error::WrongScope)));
        assert_eq!(std::fs::read(&legacy)?, bytes);
    }
    Ok(())
}

#[test]
fn scoped_checkpoint_rejects_structurally_valid_cross_cadence_candidate_before_cas() -> anyhow::Result<()> {
    let cuts = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &cuts[0];
    let scope = FrozenLearningScopeV2::freeze(&initial.request, &initial.owners, LearningUpdateScopeV2::Cell, Digest32::of_bytes(b"rule"))?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("scope-root");
    let record = LearningIterationCheckpointRecordV1::vacant_scoped_v2(initial.request.clone(), initial.owners.clone(), &scope)?;
    let store = Arc::new(FileCas::create(&path, &record)?);
    let current = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(store.clone(), OWNER.into(), initial.request.clone(), initial.owners.clone(), scope.clone())?;
    for (index, cut) in cuts[..3].iter().enumerate() {
        current.checkpoint(if index == 0 { Digest32::ZERO } else { cuts[index - 1].head_digest }, cut)?;
    }
    let before = std::fs::read(&path)?;
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(cuts[2].clone())?;
    let mut training = cuts[3].receipts.last().ok_or_else(|| anyhow::anyhow!("missing training receipt"))?.clone();
    if let LearningIterationObservationV1::Training { candidate, .. } = &mut training.observation {
        candidate.components.base = Digest32::of_bytes(b"changed-base");
    }
    coordinator.record(training, 50)?;
    assert_eq!(current.checkpoint(cuts[2].head_digest, coordinator.snapshot()), Err(Error::Snapshot(LearningIterationError::UpdateScopeMismatch)));
    assert_eq!(std::fs::read(&path)?, before);
    assert_eq!(current.restore(&initial.request)?, Some(cuts[2].clone()));
    let replay_path = directory.path().join("invalid-scoped-replay");
    let replay = LearningIterationCheckpointRecordV1 {
        schema: 2,
        binding: scope.binding().to_string(),
        predecessor: cuts[2].head_digest.to_string(),
        snapshot: Some(STANDARD_NO_PAD.encode(codec::encode(coordinator.snapshot())?)),
    };
    let replay_store = Arc::new(FileCas::create(&replay_path, &replay)?);
    let replay_bytes = std::fs::read(&replay_path)?;
    assert!(matches!(LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(replay_store, OWNER.into(), initial.request.clone(), initial.owners.clone(), scope), Err(Error::Snapshot(LearningIterationError::UpdateScopeMismatch))));
    assert_eq!(std::fs::read(&replay_path)?, replay_bytes);
    store.failure.store(2, Ordering::SeqCst);
    assert!(matches!(current.checkpoint(cuts[2].head_digest, &cuts[3]), Err(Error::CommitUncertain(_))));
    assert_eq!(current.restore(&initial.request)?, Some(cuts[3].clone()));
    let commits = store.commits.load(Ordering::SeqCst);
    assert_eq!(current.checkpoint(cuts[2].head_digest, &cuts[3])?, cuts[3].head_digest);
    assert_eq!(store.commits.load(Ordering::SeqCst), commits);
    Ok(())
}
