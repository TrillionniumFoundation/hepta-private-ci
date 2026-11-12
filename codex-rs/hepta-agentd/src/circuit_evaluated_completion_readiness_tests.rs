//! The actual C owner distinguishes unresolved work from irreversible failure.
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_readiness_waits_for_actual_c_and_preserves_original_selection()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let dataset = Box::pin(original_dataset(&f)).await?;
    let (mut c, files, selected) = Box::pin(published_and_selected(&mut f)).await?;
    let owner = task_reader(&c, selected.clone())?;
    let (client, channel) = readiness::client(&dataset.config, &dataset.receipt, &selected)?;
    readiness::reject_legacy_and_changed_requests(&owner, &client)?;
    let before = (c_bytes(&c)?, files.bytes()?);
    let server = readiness::serve(owner, channel);
    assert_eq!(client.read_current().await?, None);
    assert_eq!((c_bytes(&c)?, files.bytes()?), before);
    // The only execution is the actual original C ingress, after NotReady.
    let completed = execute(&c, 1).await?;
    let actual = read_receipt(&c, &f.definition, &completed)?;
    assert_eq!(actual.bundle_digest, f.bundle.digest()?);
    assert_ne!(actual.bundle_digest, f.host.original.candidate.digest()?);
    let after = c_bytes(&c)?;
    let read = client
        .read_current()
        .await?
        .expect("actual original C completion");
    let coordinator = LearningIterationCoordinatorV1::from_snapshot(selected.snapshot().clone())?;
    assert_eq!(
        read.observation(),
        &c.cell
            .read_learning_next_use(&coordinator, c.source.as_ref(), &c.runtime.identity,)?
    );
    assert_eq!((c_bytes(&c)?, files.bytes()?), (after, before.1));
    drop(client);
    assert_eq!(server.join().expect("original readiness owner")?, 2);
    finish_dataset(dataset)?;
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_readiness_withdrawal_is_fatal_and_consumes_original_connection()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let dataset = Box::pin(original_dataset(&f)).await?;
    let (mut c, files, selected) = Box::pin(published_and_selected(&mut f)).await?;
    let owner = task_reader(&c, selected.clone())?;
    let (client, channel) = readiness::client(&dataset.config, &dataset.receipt, &selected)?;
    let server = readiness::serve(owner, channel);
    assert_eq!(client.read_current().await?, None);
    let before = (c_bytes(&c)?, files.bytes()?);
    f.host.original.version.withdraw()?;
    assert!(client.read_current().await.is_err());
    assert!(matches!(
        client.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!((c_bytes(&c)?, files.bytes()?), before);
    drop(client);
    assert!(
        server
            .join()
            .expect("withdrawn actual readiness owner")
            .is_err()
    );
    finish_dataset(dataset)?;
    c.stop().await?;
    drop(c);
    f.finish().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn evaluated_readiness_completed_identity_and_queued_cancellation_never_revive()
-> anyhow::Result<()> {
    let mut f = Box::pin(PublicationFixture::ready()).await?;
    let dataset = Box::pin(original_dataset(&f)).await?;
    let (mut c, files, selected) = Box::pin(published_and_selected(&mut f)).await?;
    let completed = execute(&c, 1).await?;
    assert_eq!(
        read_receipt(&c, &f.definition, &completed)?.bundle_digest,
        f.bundle.digest()?
    );
    let before = (c_bytes(&c)?, files.bytes()?);
    let owner = task_reader(&c, selected.clone())?;
    let (client, channel) = readiness::client(&dataset.config, &dataset.receipt, &selected)?;
    let server = readiness::changed_ready_to_pending(Arc::clone(&owner), channel);
    assert!(client.read_current().await?.is_some());
    assert!(matches!(
        client.read_current().await,
        Err(ReadError::Binding(
            "completed evaluated C cannot change or become pending"
        ))
    ));
    assert!(matches!(
        client.read_current().await,
        Err(ReadError::Unavailable)
    ));
    drop(client);
    server
        .join()
        .expect("negative mutation after actual C read")?;

    let (cancelled, channel) = readiness::client(&dataset.config, &dataset.receipt, &selected)?;
    readiness::cancel_queued(cancelled)?;
    let server = readiness::serve(owner, channel);
    assert_eq!(
        server
            .join()
            .expect("no queued request reached original C")?,
        0
    );
    assert_eq!((c_bytes(&c)?, files.bytes()?), before);
    finish_dataset(dataset)?;
    c.stop().await?;
    drop(c);
    f.finish().await
}
