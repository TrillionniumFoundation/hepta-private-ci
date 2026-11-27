//! Original file-CAS persistence with explicitly synthetic policy evidence.

use super::*;
use crate::neuron_generation_update_bootstrap::learning_test_receipt;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningLocalDecisionV2;
use codex_hepta_learning_artifacts::LearningLocalDispositionV2;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

fn cuts() -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
    let updated = snapshots(Decision::Update)?;
    let retained = snapshots(Decision::EvaluatedNoUpdate)?;
    let mut cuts = updated[..6].to_vec();
    let mut c = LearningIterationCoordinatorV1::from_snapshot(updated[5].clone())?;
    let decision = LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
        proposal_head: c.snapshot().head_digest,
        candidate_bundle: c.candidate().unwrap().digest()?,
        selected_bundle: c.snapshot().request.selected_bundle.digest()?,
        policy_digest: Digest32::of_bytes(b"node-policy-v3"),
        reason_digest: Digest32::of_bytes(b"local-resource-limit"),
        disposition: LearningLocalDispositionV2::DeferCandidate,
    });
    c.record(learning_test_receipt(&c, decision), 20)?;
    cuts.push(c.snapshot().clone());
    for old in &retained[5..] {
        let observation = old.receipts.last().unwrap().observation.clone();
        c.record(learning_test_receipt(&c, observation), 20)?;
        cuts.push(c.snapshot().clone());
    }
    Ok(cuts)
}

#[test]
fn local_decision_codec_refuses_header_downgrade_unknown_choice_and_historical_relabel()
-> anyhow::Result<()> {
    for (index, snapshot) in cuts()?.iter().enumerate() {
        let bytes = codec::encode(snapshot)?;
        assert_eq!(codec::decode(&bytes)?, *snapshot);
        assert_eq!(codec::encode(&codec::decode(&bytes)?)?, bytes);
        assert_eq!(
            &bytes[..8],
            if index < 6 { b"HEPLCP02" } else { b"HEPLCP04" }
        );
        let mut changed = bytes;
        changed[..8].copy_from_slice(if index < 6 { b"HEPLCP04" } else { b"HEPLCP02" });
        assert!(codec::decode(&changed).is_err());
    }
    let mut bytes = codec::encode(&cuts()?[6])?;
    let tag_offset = bytes.len() - 32 - (2 + 5 * 32);
    assert_eq!(bytes[tag_offset], 9);
    bytes[tag_offset + 1] = 3;
    assert_eq!(codec::decode(&bytes), Err(Error::InvalidRecord));
    Ok(())
}

#[test]
fn local_decision_is_cas_persisted_before_selection_and_requires_original_scoped_owner()
-> anyhow::Result<()> {
    let cuts = cuts()?;
    let initial = &cuts[0];
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request,
        &initial.owners,
        LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("scoped-owner");
    let vacant = LearningIterationCheckpointRecordV1::vacant_scoped_v2(
        initial.request.clone(),
        initial.owners.clone(),
        &scope,
    )?;
    FileCas::create(&path, &vacant)?;
    for (index, snapshot) in cuts.iter().enumerate() {
        let store = Arc::new(FileCas::reopen(&path)?);
        let current = LearningIterationCheckpointOwnerV1 {
            owner_id: OWNER.into(),
            store: Store::Test(store.clone()),
            initial: initial.clone(),
            scope: Some(scope.clone()),
        };
        let predecessor = if index == 0 {
            Digest32::ZERO
        } else {
            cuts[index - 1].head_digest
        };
        assert_eq!(
            current.checkpoint(predecessor, snapshot)?,
            snapshot.head_digest
        );
        let bytes = std::fs::read(&path)?;
        assert_eq!(
            current.checkpoint(predecessor, snapshot)?,
            snapshot.head_digest
        );
        assert_eq!(store.commits.load(Ordering::SeqCst), 1);
        assert_eq!(std::fs::read(&path)?, bytes);
        drop(current);
        let reopened = LearningIterationCheckpointOwnerV1 {
            owner_id: OWNER.into(),
            store: Store::Test(Arc::new(FileCas::reopen(&path)?)),
            initial: initial.clone(),
            scope: Some(scope.clone()),
        };
        assert_eq!(reopened.restore(&initial.request)?, Some(snapshot.clone()));
    }
    let legacy_path = directory.path().join("legacy-owner");
    let store = Arc::new(FileCas::create(
        &legacy_path,
        &LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?,
    )?);
    let legacy = owner(store, initial);
    for (index, snapshot) in cuts[..6].iter().enumerate() {
        legacy.checkpoint(
            if index == 0 {
                Digest32::ZERO
            } else {
                cuts[index - 1].head_digest
            },
            snapshot,
        )?;
    }
    let before = std::fs::read(&legacy_path)?;
    assert_eq!(
        legacy.checkpoint(cuts[5].head_digest, &cuts[6]),
        Err(Error::WrongScope)
    );
    assert_eq!(std::fs::read(&legacy_path)?, before);
    assert_eq!(legacy.restore(&initial.request)?, Some(cuts[5].clone()));
    Ok(())
}
