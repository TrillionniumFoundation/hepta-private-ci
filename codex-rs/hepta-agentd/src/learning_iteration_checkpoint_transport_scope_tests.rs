//! Scope-profile tests retain real UDS/pidfd framing and file/fsync custody.
//! Fixture keys and records do not provide production authority or adoption.

use super::*;
use crate::learning_iteration_checkpoint::ports_tests::StageOwners;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn scoped_root_checkpoint_ports_keep_scope_across_all_decisions_and_cold_recovery()
-> anyhow::Result<()> {
    for decision in [Decision::Update, Decision::EvaluatedNoUpdate, Decision::ProposedNoUpdate] {
        let history = snapshots(decision)?;
        let initial = &history[0];
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request, &initial.owners, LearningUpdateScopeV2::Cell,
            Digest32::of_bytes(b"rule"),
        )?;
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("scoped-root");
        let store = Arc::new(FileCas::create(&path,
            &LearningIterationCheckpointRecordV1::vacant_scoped_v2(
                initial.request.clone(), initial.owners.clone(), &scope,
            )?,
        )?);
        let backend = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
            store.clone(), support::OWNER.into(), initial.request.clone(),
            initial.owners.clone(), scope.clone(),
        )?;
        let (mut channel, server) = client(initial);
        channel.scope = Some(scope.clone());
        let worker = serve(server, backend);
        let stages = Arc::new(StageOwners::new(history.clone()));
        let ports = channel.with_stage_owners(stages.clone());
        assert_eq!(ports.frozen_scope_binding(), Some(scope.binding()));
        assert_eq!(ports.restore(&initial.request).await?, None);
        for (index, snapshot) in history.iter().enumerate() {
            let expected = index.checked_sub(1).map_or(Digest32::ZERO, |i| history[i].head_digest);
            assert_eq!(ports.checkpoint(expected, snapshot).await?, snapshot.head_digest);
            assert_eq!(ports.checkpoint(expected, snapshot).await?, snapshot.head_digest);
            assert_eq!(ports.restore(&initial.request).await?, Some(snapshot.clone()));
        }
        assert_eq!(store.commits.load(Ordering::SeqCst), history.len());
        drop(ports);
        worker.join().unwrap()?;
        let retained = std::fs::read(&path)?;
        let reopened = Arc::new(FileCas::reopen(&path)?);
        let backend = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
            reopened.clone(), support::OWNER.into(), initial.request.clone(),
            initial.owners.clone(), scope.clone(),
        )?;
        let (mut channel, server) = client(initial);
        channel.scope = Some(scope.clone());
        let worker = serve(server, backend);
        let ports = channel.with_stage_owners(stages);
        assert_eq!(ports.frozen_scope_binding(), Some(scope.binding()));
        assert_eq!(ports.restore(&initial.request).await?, history.last().cloned());
        assert_eq!(reopened.commits.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read(&path)?, retained);
        drop(ports);
        worker.join().unwrap()?;
    }
    Ok(())
}

#[tokio::test]
async fn root_checkpoint_refuses_legacy_scoped_and_changed_scope_substitution()
-> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let cell = FrozenLearningScopeV2::freeze(
        &initial.request, &initial.owners, LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    let organ = FrozenLearningScopeV2::freeze(
        &initial.request, &initial.owners, LearningUpdateScopeV2::Organ,
        Digest32::of_bytes(b"rule"),
    )?;
    for (root_scope, client_scope) in [
        (Some(cell.clone()), None),
        (None, Some(cell.clone())),
        (Some(cell), Some(organ)),
    ] {
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original-root");
        let vacant = match &root_scope {
            Some(scope) => LearningIterationCheckpointRecordV1::vacant_scoped_v2(
                initial.request.clone(), initial.owners.clone(), scope,
            )?,
            None => LearningIterationCheckpointRecordV1::vacant(
                initial.request.clone(), initial.owners.clone(),
            )?,
        };
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        let backend = match root_scope {
            Some(scope) => LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
                store.clone(), support::OWNER.into(), initial.request.clone(),
                initial.owners.clone(), scope,
            )?,
            None => owner(store.clone(), initial),
        };
        let original = std::fs::read(&path)?;
        let (mut channel, server) = client(initial);
        channel.scope = client_scope;
        let worker = serve(server, backend);
        assert!(channel.restore(&initial.request).await.is_err());
        assert!(worker.join().unwrap().is_err());
        assert_eq!(store.commits.load(Ordering::SeqCst), 0);
        assert_eq!(std::fs::read(&path)?, original);
    }
    Ok(())
}

#[tokio::test]
async fn scoped_root_checkpoint_lost_ack_requires_original_scope_on_fresh_connection()
-> anyhow::Result<()> {
    let history = snapshots(Decision::EvaluatedNoUpdate)?;
    let initial = &history[0];
    let scope = FrozenLearningScopeV2::freeze(
        &initial.request, &initial.owners, LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original-root");
    let store = Arc::new(FileCas::create(&path,
        &LearningIterationCheckpointRecordV1::vacant_scoped_v2(
            initial.request.clone(), initial.owners.clone(), &scope,
        )?,
    )?);
    store.failure.store(/*val*/ 2, Ordering::SeqCst);
    let backend = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
        store.clone(), support::OWNER.into(), initial.request.clone(),
        initial.owners.clone(), scope.clone(),
    )?;
    let (mut first, server) = client(initial);
    first.scope = Some(scope.clone());
    let worker = serve(server, backend);
    for _ in 0..2 {
        assert_eq!(first.checkpoint(Digest32::ZERO, initial).await,
            Err(Error::CommitUncertain(AuthorityTrustError::Unavailable)));
    }
    assert!(worker.join().unwrap().is_err());
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    let original = std::fs::read(&path)?;
    let reopened = Arc::new(FileCas::reopen(&path)?);
    let backend = LearningIterationCheckpointOwnerV1::from_research_store_scoped_v2(
        reopened.clone(), support::OWNER.into(), initial.request.clone(),
        initial.owners.clone(), scope.clone(),
    )?;
    let (mut second, server) = client(initial);
    second.scope = Some(scope);
    let worker = serve(server, backend);
    assert_eq!(second.restore(&initial.request).await?, Some(initial.clone()));
    assert_eq!(second.checkpoint(Digest32::ZERO, initial).await?, initial.head_digest);
    assert_eq!(reopened.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, original);
    drop(second);
    worker.join().unwrap()?;
    Ok(())
}
