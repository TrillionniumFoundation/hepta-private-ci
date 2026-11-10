//! Persistence controls only; fixture receipts are not training evidence.

use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateReasonV2;
use codex_hepta_learning_artifacts::LearningTrainingNoUpdateV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

use super::*;

fn cuts() -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let old = snapshots(Decision::EvaluatedNoUpdate)?;
    let mut cuts = old[..3].to_vec();
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(old[2].clone())?;
    let mut training = old[3].receipts.last().unwrap().clone();
    training.observation = LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
        retained_bundle: coordinator.snapshot().request.selected_bundle.digest()?,
        dataset: Digest32::of_bytes(b"data"), update_rule: Digest32::of_bytes(b"rule"),
        steps: 1, milliseconds: 1,
        reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
    });
    coordinator.record(training, 20)?;
    cuts.push(coordinator.snapshot().clone());
    for old_cut in &old[5..] {
        let mut receipt = old_cut.receipts.last().unwrap().clone();
        receipt.predecessor = coordinator.snapshot().head_digest;
        coordinator.record(receipt, 20)?;
        cuts.push(coordinator.snapshot().clone());
    }
    Ok(cuts)
}

fn scope(initial: &LearningIterationSnapshotV1) -> anyhow::Result<FrozenLearningScopeV2> {
    Ok(FrozenLearningScopeV2::freeze(&initial.request, &initial.owners,
        LearningUpdateScopeV2::Cell, Digest32::of_bytes(b"rule"))?)
}

fn scoped(store: Arc<FileCas>, initial: &LearningIterationSnapshotV1,
    scope: &FrozenLearningScopeV2) -> LearningIterationCheckpointOwnerV1 {
    LearningIterationCheckpointOwnerV1 {
        owner_id: OWNER.into(), store: Store::Test(store),
        initial: initial.clone(), scope: Some(scope.clone()),
    }
}

#[test]
fn trainer_no_update_uses_new_codec_without_changing_old_bytes_or_allowing_downgrade() -> anyhow::Result<()> {
    for decision in [Decision::Update, Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
        for old in snapshots(decision)? {
            let bytes = codec::encode(&old)?;
            assert_eq!(&bytes[..8], b"HEPLCP02");
            assert_eq!(codec::encode(&codec::decode(&bytes)?)?, bytes);
            let mut rebound = bytes;
            rebound[..8].copy_from_slice(b"HEPLCP03");
            assert_eq!(codec::decode(&rebound), Err(Error::InvalidRecord));
        }
    }
    for (index, cut) in cuts()?.iter().enumerate() {
        let bytes = codec::encode(cut)?;
        assert_eq!(&bytes[..8], if index < 3 { b"HEPLCP02" } else { b"HEPLCP03" });
        assert_eq!(codec::decode(&bytes)?, *cut);
        assert_eq!(codec::encode(&codec::decode(&bytes)?)?, bytes);
        if index >= 3 {
            let mut downgraded = bytes;
            downgraded[..8].copy_from_slice(b"HEPLCP02");
            assert_eq!(codec::decode(&downgraded), Err(Error::InvalidRecord));
        }
    }
    let mut unknown_reason = codec::encode(&cuts()?[3])?;
    let tag_offset = unknown_reason.len() - 32 - (1 + 1 + 3 * 32 + 2 * 8);
    assert_eq!(unknown_reason[tag_offset], 8);
    unknown_reason[tag_offset + 1] = 1;
    assert_eq!(codec::decode(&unknown_reason), Err(Error::InvalidRecord));
    Ok(())
}

#[test]
fn trainer_no_update_reopens_original_scope_and_rejects_unscoped_or_changed_rule_before_cas() -> anyhow::Result<()> {
    let cuts = cuts()?;
    let initial = &cuts[0];
    let scope = scope(initial)?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-scoped-root");
    let vacant = LearningIterationCheckpointRecordV1::vacant_scoped_v2(
        initial.request.clone(), initial.owners.clone(), &scope)?;
    FileCas::create(&path, &vacant)?;
    for (index, cut) in cuts.iter().enumerate() {
        let store = Arc::new(FileCas::reopen(&path)?);
        let current = scoped(store.clone(), initial, &scope);
        let predecessor = if index == 0 { Digest32::ZERO } else { cuts[index - 1].head_digest };
        assert_eq!(current.checkpoint(predecessor, cut)?, cut.head_digest);
        let bytes = std::fs::read(&path)?;
        assert_eq!(current.checkpoint(predecessor, cut)?, cut.head_digest);
        assert_eq!(store.commits.load(Ordering::SeqCst), 1);
        assert_eq!(std::fs::read(&path)?, bytes);
        drop(current);
        drop(store);
        assert_eq!(scoped(Arc::new(FileCas::reopen(&path)?), initial, &scope)
            .restore(&initial.request)?, Some(cut.clone()));
    }
    let legacy_path = directory.path().join("legacy-root");
    let legacy_vacant = LearningIterationCheckpointRecordV1::vacant(
        initial.request.clone(), initial.owners.clone())?;
    let legacy_store = Arc::new(FileCas::create(&legacy_path, &legacy_vacant)?);
    let legacy = owner(legacy_store.clone(), initial);
    for (index, cut) in cuts[..3].iter().enumerate() {
        legacy.checkpoint(if index == 0 { Digest32::ZERO } else { cuts[index - 1].head_digest }, cut)?;
    }
    let before = std::fs::read(&legacy_path)?;
    assert_eq!(legacy.checkpoint(cuts[2].head_digest, &cuts[3]), Err(Error::WrongScope));
    assert_eq!(std::fs::read(&legacy_path)?, before);
    assert_eq!(legacy.restore(&initial.request)?, Some(cuts[2].clone()));
    // Even a structurally sound v3 payload cannot give a legacy outer owner
    // the separately held frozen rule that it never possessed.
    let injected = LearningIterationCheckpointRecordV1 {
        schema: 1, binding: initial.head_digest.to_string(),
        predecessor: cuts[2].head_digest.to_string(),
        snapshot: Some(STANDARD_NO_PAD.encode(codec::encode(&cuts[3])?)),
    };
    let injected_path = directory.path().join("injected-legacy-root");
    let injected_store = Arc::new(FileCas::create(&injected_path, &injected)?);
    assert_eq!(owner(injected_store, initial).restore(&initial.request), Err(Error::WrongScope));
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(cuts[2].clone())?;
    let mut changed = cuts[3].receipts.last().unwrap().clone();
    let LearningIterationObservationV1::TrainingNoUpdateV2(outcome) = &mut changed.observation
    else { panic!("trainer outcome") };
    outcome.update_rule = Digest32::of_bytes(b"unfrozen-rule");
    coordinator.record(changed, 20)?;
    let bytes = std::fs::read(&path)?;
    assert!(matches!(scoped(Arc::new(FileCas::reopen(&path)?), initial, &scope)
        .checkpoint(cuts[2].head_digest, coordinator.snapshot()), Err(Error::Snapshot(_))));
    assert_eq!(std::fs::read(&path)?, bytes);
    Ok(())
}
