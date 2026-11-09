//! Real UDS/FileCas composition with the existing same-UID protocol fixture.
//! This exercises no production authority issuance or learning attestations.

use super::*;
use crate::LearningIterationRuntimeErrorV1;
use crate::learning_iteration_checkpoint::ports_tests::StageOwners;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn root_checkpoint_ports_recover_original_stages_for_all_decisions() -> anyhow::Result<()> {
    for decision in [
        Decision::Update,
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
    ] {
        let history = snapshots(decision)?;
        let initial = &history[0];
        let directory = tempfile::tempdir()?;
        let store = Arc::new(FileCas::create(
            &directory.path().join("original"),
            &LearningIterationCheckpointRecordV1::vacant(
                initial.request.clone(),
                initial.owners.clone(),
            )?,
        )?);
        let stages = Arc::new(StageOwners::new(history.clone()));
        let (client, server) = client(initial);
        let worker = serve(server, owner(store.clone(), initial));
        let ports = client.with_stage_owners(stages.clone());
        assert_eq!(ports.restore(&initial.request).await?, None);
        assert_eq!(stages.recoveries.load(Ordering::SeqCst), 0);
        for (index, snapshot) in history.iter().enumerate() {
            let expected = if index == 0 {
                Digest32::ZERO
            } else {
                history[index - 1].head_digest
            };
            assert_eq!(
                ports.checkpoint(expected, snapshot).await?,
                snapshot.head_digest
            );
            assert_eq!(
                ports.restore(&initial.request).await?,
                Some(snapshot.clone())
            );
            assert_eq!(
                ports.checkpoint(expected, snapshot).await?,
                snapshot.head_digest
            );
        }
        assert_eq!(stages.recoveries.load(Ordering::SeqCst), history.len());
        assert_eq!(store.commits.load(Ordering::SeqCst), history.len());
        let mut foreign = initial.request.clone();
        foreign.operation_id = codex_hepta_types::StableId::new("other-operation")?;
        assert!(matches!(
            ports.restore(&foreign).await,
            Err(LearningIterationRuntimeErrorV1::Checkpoint(
                Error::WrongScope
            ))
        ));
        assert_eq!(stages.recoveries.load(Ordering::SeqCst), history.len());
        stages.unavailable.store(/*val*/ true, Ordering::SeqCst);
        assert!(matches!(
            ports.restore(&initial.request).await,
            Err(LearningIterationRuntimeErrorV1::OwnerUnavailable(
                "recovery"
            ))
        ));
        assert_eq!(store.commits.load(Ordering::SeqCst), history.len());
        drop(ports);
        worker.join().unwrap()?;
    }
    Ok(())
}

#[tokio::test]
async fn root_checkpoint_ports_preserve_uncertainty_until_original_owner_reconnects()
-> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let initial = &history[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = Arc::new(FileCas::create(
        &path,
        &LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?,
    )?);
    let stages = Arc::new(StageOwners::new(history.clone()));
    store.failure.store(/*val*/ 2, Ordering::SeqCst);
    let (first, server) = client(initial);
    let worker = serve(server, owner(store.clone(), initial));
    let ports = first.with_stage_owners(stages.clone());
    for _ in 0..2 {
        assert!(matches!(
            ports.checkpoint(Digest32::ZERO, initial).await,
            Err(LearningIterationRuntimeErrorV1::CommitUncertain)
        ));
    }
    assert!(matches!(
        ports.restore(&initial.request).await,
        Err(LearningIterationRuntimeErrorV1::Checkpoint(Error::Store(
            AuthorityTrustError::Unavailable
        )))
    ));
    assert!(worker.join().unwrap().is_err());
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    assert_eq!(stages.recoveries.load(Ordering::SeqCst), 0);
    drop(ports);
    let committed = std::fs::read(&path)?;
    let reopened = Arc::new(FileCas::reopen(&path)?);
    let (second, server) = client(initial);
    let worker = serve(server, owner(reopened.clone(), initial));
    let ports = second.with_stage_owners(stages.clone());
    assert_eq!(
        ports.restore(&initial.request).await?,
        Some(initial.clone())
    );
    assert_eq!(stages.recoveries.load(Ordering::SeqCst), 1);
    assert_eq!(
        ports.checkpoint(Digest32::ZERO, initial).await?,
        initial.head_digest
    );
    assert_eq!(reopened.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, committed);
    drop(ports);
    worker.join().unwrap()?;
    Ok(())
}
