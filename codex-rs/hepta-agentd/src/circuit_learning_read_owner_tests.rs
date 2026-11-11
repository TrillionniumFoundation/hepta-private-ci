//! Actual ordinary A/C and original published CURRENT, over explicit fixture
//! transport. Credential enrollment and TrainingNoUpdate metadata remain test
//! custody; these cases do not claim an installed external-UID role deployment.

use super::*;
use std::os::unix::net::UnixStream;
use std::time::Duration;

use pretty_assertions::assert_eq;

use crate::OriginalCircuitLearningReadClientV1 as ReadClient;
use crate::OriginalCircuitLearningReadContextV1 as ReadContext;
use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::OriginalCircuitLearningReadOwnerV1 as ReadOwner;
use crate::OriginalCircuitNextUseRemoteSourcesV1;
use crate::OriginalCircuitSelectionRemoteSourcesV1;
use crate::circuit_feature_current::original_learning_read_fixture as transport;

type OriginalReadOwner = ReadOwner<FileAnchorWitnessStore, FileAnchorWitnessStore>;
type ReadThread = std::thread::JoinHandle<Result<u64, ReadError>>;

fn selection_context(config: &OriginalCircuitSelectionReceiptConfigV1) -> ReadContext {
    ReadContext {
        prefix: config.decision.clone(),
        scope: config.scope.clone(),
        verifier: config.verifier.clone(),
        training_evidence: config.training_evidence.clone(),
        selection_evidence: None,
    }
}

fn next_use_context(config: &OriginalCircuitNextUseReceiptConfigV1) -> ReadContext {
    ReadContext {
        prefix: config.selection.clone(),
        scope: config.scope.clone(),
        verifier: config.verifier.clone(),
        training_evidence: config.training_evidence.clone(),
        selection_evidence: Some(config.selection_evidence.clone()),
    }
}

fn original(f: &ObserverFixture, context: ReadContext) -> anyhow::Result<Arc<OriginalReadOwner>> {
    Ok(Arc::new(ReadOwner::from_original_owners(
        f.session.cell.clone(),
        f.session.source.as_ref().clone(),
        f.session.runtime.identity.clone(),
        context,
    )?))
}

fn remote_selection<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    live: &'a ReadClient,
    trainer: &'a LearningIterationEvidenceClientV1,
) -> OriginalCircuitSelectionRemoteSourcesV1<'a> {
    OriginalCircuitSelectionRemoteSourcesV1 { snapshot, live, trainer }
}

fn remote_c<'a>(
    snapshot: &'a LearningIterationSnapshotV1,
    live: &'a ReadClient,
    peers: &'a Peers,
) -> OriginalCircuitNextUseRemoteSourcesV1<'a> {
    OriginalCircuitNextUseRemoteSourcesV1 {
        snapshot, live, trainer: &peers.trainer, selector: &peers.selector,
    }
}

fn finish_read(client: ReadClient, thread: ReadThread, reads: u64) -> anyhow::Result<()> {
    drop(client);
    let actual = thread.join().map_err(|_| anyhow::anyhow!("original read fixture panicked"))??;
    assert_eq!(actual, reads);
    Ok(())
}

#[tokio::test]
async fn q24_remote_selection_reads_original_publication_before_c_and_recovers_signature()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = selection_context(&f.config);
    let owner = original(&f.original, context.clone())?;
    let (live, channel) = transport::client(context)?;
    let server = transport::serve(owner, channel);
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 20)?;
    let mut selector = f.create()?;
    let before = f.bytes()?;
    let source_before = owner_bytes(&f.original.session)?;
    assert!(matches!(
        selector.readback_remote(remote_selection(&f.config.decision, &live, &trainer)).await,
        Err(OriginalCircuitSelectionReceiptErrorV1::Owner(
            OwnerError::Store(ProductEvaluationExecutionStoreErrorV1::Missing)
        ))
    ));
    assert_eq!(f.bytes()?, before);
    let saved = selector.attest_original_remote_selection(
        remote_selection(&f.config.decision, &live, &trainer)
    ).await?;
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    assert_eq!(saved.0.observation, f.original.session.cell.read_learning_selection(&coordinator)?);
    assert_eq!(saved.1.role, LearningEvidenceRoleV1::Selector);
    let bytes = f.bytes()?;
    assert_eq!(
        selector.readback_remote(remote_selection(&f.config.decision, &live, &trainer)).await?,
        saved,
    );
    assert_eq!(f.bytes()?, bytes);
    assert_eq!(owner_bytes(&f.original.session)?, source_before);
    let mut selected = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    selected.record(saved.0.clone(), saved.0.observed_unix_seconds)?;
    assert!(f.original.session.cell.read_learning_next_use(
        &selected, f.original.session.source.as_ref(), &f.original.session.runtime.identity,
    ).is_err());
    drop(selector);
    let mut recovered = f.recover()?;
    assert_eq!(
        recovered.readback_remote(remote_selection(&f.config.decision, &live, &trainer)).await?,
        saved,
    );
    assert_eq!(f.bytes()?, bytes);
    drop(recovered);
    finish_read(live, server, 8)?;
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_remote_c_requires_actual_completion_and_original_selector_signature()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    // Obtain an actual original Selector signature over the actual publication.
    let (trainer, thread) = f.peer(f.config.training_evidence.clone(), 2)?;
    let mut selector = f.create()?;
    let selection = selector.attest_original_selection(f.sources(&f.config.decision, &trainer)).await?;
    drop(selector);
    finish(trainer, thread)?;
    let mut selected = LearningIterationCoordinatorV1::from_snapshot(f.config.decision.clone())?;
    selected.record(selection.0.clone(), selection.0.observed_unix_seconds)?;
    f.original.config.selection = selected.snapshot().clone();
    f.original.config.selection_evidence = selection.1.clone();
    f.original.selection = selection.0;
    f.original.selection_signature = selection.1;
    let context = next_use_context(&f.original.config);
    // Bootstrap only checks the original configured C input and publication.
    // A NextUse read still cannot succeed until ordinary C actually commits.
    let owner = original(&f.original, context.clone())?;
    let (early, channel) = transport::client(context.clone())?;
    let early_server = transport::serve(Arc::clone(&owner), channel);
    assert!(early.read_current().await.is_err());
    assert!(matches!(early.read_current().await, Err(ReadError::Unavailable)));
    drop(early);
    assert!(early_server.join().map_err(|_| anyhow::anyhow!("early read thread"))?.is_err());
    let publication = execute(&f.original.session, 1).await?;
    let actual = read_receipt(&f.original.session, &f.original.definition, &publication)?;
    assert_ne!(publication.input().scope.run_id, f.original.previous.input().scope.run_id);
    assert_ne!(publication.input().observation, f.original.previous.input().observation);
    assert_eq!(actual.bundle_digest, f.original.previous_decision.bundle_digest);
    let (live, channel) = transport::client(context)?;
    let server = transport::serve(owner, channel);
    let peers = f.original.peers(18)?;
    let mut observer = f.original.create_owner()?;
    let saved = observer.attest_original_remote_completion(
        remote_c(&f.original.config.selection, &live, &peers)
    ).await?;
    assert!(matches!(&saved.0.observation,
        LearningIterationObservationV1::RetainedModelNextUse { state_partition, .. }
            if state_partition.run_id == publication.input().scope.run_id
    ));
    let bytes = f.original.bytes()?;
    assert_eq!(
        observer.readback_remote(remote_c(&f.original.config.selection, &live, &peers)).await?,
        saved,
    );
    assert_eq!(f.original.bytes()?, bytes);
    drop(observer);
    let mut recovered = f.original.recover_owner()?;
    assert_eq!(
        recovered.readback_remote(remote_c(&f.original.config.selection, &live, &peers)).await?,
        saved,
    );
    assert_eq!(f.original.bytes()?, bytes);
    drop(recovered);
    finish_read(live, server, 7)?;
    peers.finish()?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_remote_current_refuses_withdrawal_after_a_successful_read() -> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = selection_context(&f.config);
    let owner = original(&f.original, context.clone())?;
    let (live, channel) = transport::client(context)?;
    let server = transport::serve(owner, channel);
    live.read_current().await?;
    f.original.version.withdraw()?;
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 1)?;
    let mut selector = f.create()?;
    let before = f.bytes()?;
    assert!(matches!(
        selector.attest_original_remote_selection(
            remote_selection(&f.config.decision, &live, &trainer)
        ).await,
        Err(OriginalCircuitSelectionReceiptErrorV1::PublishedRead(_))
    ));
    assert_eq!(f.bytes()?, before);
    assert!(matches!(live.read_current().await, Err(ReadError::Unavailable)));
    drop(selector);
    drop(live);
    assert!(server.join().map_err(|_| anyhow::anyhow!("withdrawn read thread"))?.is_err());
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_remote_context_pins_full_signatures_and_refuses_uploaded_observations()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let mut context = selection_context(&f.config);
    context.training_evidence.expires_at += 1;
    context.training_evidence.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&context.training_evidence.signing_bytes()).to_bytes();
    context.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &context.training_evidence,
        &learning_iteration_receipt_signing_bytes_v1(&f.original.training)?,
        now()?,
    )?;
    let owner = original(&f.original, context.clone())?;
    let source_before = owner_bytes(&f.original.session)?;
    transport::reject_wrong_context(&owner, &context)?;
    assert_eq!(owner_bytes(&f.original.session)?, source_before);
    let (live, channel) = transport::client(context)?;
    let server = transport::serve(owner, channel);
    let (trainer, peer) = f.peer(f.config.training_evidence.clone(), 0)?;
    let mut selector = f.create()?;
    let before = f.bytes()?;
    assert!(matches!(
        selector.attest_original_remote_selection(
            remote_selection(&f.config.decision, &live, &trainer)
        ).await,
        Err(OriginalCircuitSelectionReceiptErrorV1::PublishedRead(ReadError::Binding(_)))
    ));
    assert_eq!(f.bytes()?, before);
    assert_eq!(owner_bytes(&f.original.session)?, source_before);
    drop(selector);
    finish_read(live, server, 0)?;
    finish(trainer, peer)?;
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_remote_read_consumes_late_and_wrong_nonce_responses_without_effects()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = selection_context(&f.config);
    let owner = original(&f.original, context.clone())?;
    let selector = f.create()?;
    let before = f.bytes()?;
    let source_before = owner_bytes(&f.original.session)?;
    let (late, channel) = transport::client(context.clone())?;
    let server = transport::delayed_response(Arc::clone(&owner), channel);
    assert!(late.read_current().await.is_err());
    assert!(matches!(late.read_current().await, Err(ReadError::Unavailable)));
    drop(late);
    server.join().map_err(|_| anyhow::anyhow!("late response thread"))??;
    let (wrong, channel) = transport::client(context)?;
    let server = transport::changed_nonce(owner, channel);
    assert!(wrong.read_current().await.is_err());
    assert!(matches!(wrong.read_current().await, Err(ReadError::Unavailable)));
    drop(wrong);
    server.join().map_err(|_| anyhow::anyhow!("nonce response thread"))??;
    assert_eq!(f.bytes()?, before);
    assert_eq!(owner_bytes(&f.original.session)?, source_before);
    drop(selector);
    f.original.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_remote_read_refuses_expired_original_window_and_same_process_bootstrap()
-> anyhow::Result<()> {
    let mut f = SelectionFixture::ready().await?;
    let context = selection_context(&f.config);
    let (stream, unused) = UnixStream::pair()?;
    // SAFETY: observe test credentials, which production must reject.
    let uid = unsafe { libc::geteuid() };
    assert!(ReadClient::from_original_stream(
        stream, transport::identity()?, uid, transport::pidfd()?, context.clone(),
        Duration::from_millis(500), Duration::from_secs(300),
    ).is_err());
    drop(unused);
    for (timeout, lifetime) in [
        (Duration::from_millis(501), Duration::from_secs(300)),
        (Duration::from_millis(500), Duration::from_secs(301)),
    ] {
        let (stream, unused) = UnixStream::pair()?;
        assert!(matches!(ReadClient::from_original_stream(
            stream, transport::identity()?, uid, transport::pidfd()?, context.clone(),
            timeout, lifetime,
        ), Err(ReadError::Binding("bounded original read timing"))));
        drop(unused);
    }
    let mut short = context;
    let expires_at = now()? + 2;
    short.training_evidence.expires_at = expires_at;
    short.training_evidence.signature = SigningKey::from_bytes(&[101; 32])
        .sign(&short.training_evidence.signing_bytes()).to_bytes();
    let owner = original(&f.original, short.clone())?;
    let (live, channel) = transport::client(short)?;
    let server = transport::serve(owner, channel);
    let selector = f.create()?;
    let before = f.bytes()?;
    live.read_current().await?;
    tokio::time::sleep(Duration::from_secs(expires_at.saturating_sub(now()?)) + Duration::from_millis(100)).await;
    assert!(live.read_current().await.is_err());
    assert!(matches!(live.read_current().await, Err(ReadError::Unavailable)));
    assert_eq!(f.bytes()?, before);
    drop(selector);
    finish_read(live, server, 1)?;
    f.original.session.stop().await?;
    Ok(())
}
