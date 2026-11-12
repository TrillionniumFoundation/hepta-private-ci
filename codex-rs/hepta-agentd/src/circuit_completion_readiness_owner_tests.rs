//! Actual different ordinary C and the original Published readiness producer.
//! Training metadata and same-UID transport are explicit mechanism fixtures.
//! Root grant/registry dispatch is covered by the separate resident test module.

use super::*;
use pretty_assertions::assert_eq;

use crate::OriginalCircuitLearningReadErrorV1 as ReadError;
use crate::circuit_feature_current::original_readiness_fixture as readiness;

fn finish_readiness(
    client: crate::OriginalCircuitCompletionReadinessClientV1,
    server: std::thread::JoinHandle<Result<u64, ReadError>>,
) -> anyhow::Result<u64> {
    drop(client);
    Ok(server
        .join()
        .map_err(|_| anyhow::anyhow!("readiness peer"))??)
}

#[tokio::test]
async fn q24_readiness_waits_for_actual_c_without_consuming_observer_dispatch() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    let context = next_use_context(&f.f.original.config);
    let published = original(&f.f.original, context.clone())?;
    let (wait, channel) = readiness::client(context)?;
    let waiter = readiness::serve(published, channel);
    let service = ObserverService::start(&f, f.f.original.create_owner()?)?;
    let (observer, channel) = next::client(f.context()?, false, None)?;
    let observer_peer = next::serve(Arc::clone(&service.owner), channel);
    let receipt_before = f.f.original.bytes()?;
    let task_before = owner_bytes(&f.f.original.session)?;
    assert_eq!(wait.read_current().await?, None);
    next::reject_wrong_context(&service.owner)?;
    assert_eq!(f.f.original.bytes()?, receipt_before);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_before);

    f.complete_c().await?;
    let task_completed = owner_bytes(&f.f.original.session)?;
    let ready = wait
        .read_current()
        .await?
        .expect("actual ordinary C completed");
    assert_eq!(f.f.original.bytes()?, receipt_before);
    assert_eq!(owner_bytes(&f.f.original.session)?, task_completed);
    let attested = observer.attest_completed_task().await?;
    assert_eq!(&attested.receipt().observation, ready.observation());
    assert_eq!(owner_bytes(&f.f.original.session)?, task_completed);
    assert_eq!(finish_readiness(wait, waiter)?, 2);
    assert_eq!(finish_observer(observer, observer_peer)?, 1);
    service.finish(false, false)?;
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_readiness_withdrawal_is_fatal_and_never_becomes_pending() -> anyhow::Result<()> {
    let f = CompletionFixture::ready(None).await?;
    let context = next_use_context(&f.f.original.config);
    let published = original(&f.f.original, context.clone())?;
    let (wait, channel) = readiness::client(context)?;
    let waiter = readiness::serve(published, channel);
    assert_eq!(wait.read_current().await?, None);
    let task_before = owner_bytes(&f.f.original.session)?;
    f.f.original.version.withdraw()?;
    assert!(wait.read_current().await.is_err());
    assert!(matches!(
        wait.read_current().await,
        Err(ReadError::Unavailable)
    ));
    assert_eq!(owner_bytes(&f.f.original.session)?, task_before);
    drop(wait);
    assert!(
        waiter
            .join()
            .map_err(|_| anyhow::anyhow!("withdrawn readiness peer"))?
            .is_err()
    );
    // The original Selector's separate stream was not contacted after withdrawal.
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_readiness_completed_identity_cannot_revert_or_change_publication() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let before = owner_bytes(&f.f.original.session)?;
    for change in [
        readiness::Change::PendingAfterReady,
        readiness::Change::PublicationAfterReady,
    ] {
        let context = next_use_context(&f.f.original.config);
        let published = original(&f.f.original, context.clone())?;
        let (wait, channel) = readiness::client(context)?;
        let server = readiness::changed_reply(published, channel, change);
        assert!(wait.read_current().await?.is_some());
        assert!(matches!(
            wait.read_current().await,
            Err(ReadError::Binding(
                "completed original C cannot change or become pending"
            ))
        ));
        assert!(matches!(
            wait.read_current().await,
            Err(ReadError::Unavailable)
        ));
        drop(wait);
        assert_eq!(
            server
                .join()
                .map_err(|_| anyhow::anyhow!("changed readiness peer"))??,
            2
        );
        assert_eq!(owner_bytes(&f.f.original.session)?, before);
    }
    f.finish(false).await?;
    Ok(())
}

#[tokio::test]
async fn q24_readiness_requires_original_selection_and_consumes_wrong_purpose() -> anyhow::Result<()>
{
    let f = CompletionFixture::ready(None).await?;
    f.complete_c().await?;
    let context = next_use_context(&f.f.original.config);
    let mut incomplete = context.clone();
    let removed = incomplete
        .prefix
        .receipts
        .pop()
        .expect("original Selection");
    incomplete.prefix.head_digest = removed.predecessor;
    incomplete.selection_evidence = None;
    assert!(readiness::client(incomplete).is_err());
    let published = original(&f.f.original, context.clone())?;
    let before = owner_bytes(&f.f.original.session)?;
    readiness::reject_unknown_request_fields(&published, &context)?;
    let (wait, channel) = readiness::client(context)?;
    let server = readiness::changed_reply(published, channel, readiness::Change::WrongPurpose);
    assert!(matches!(
        wait.read_current().await,
        Err(ReadError::Binding("fixed completion-readiness purpose"))
    ));
    assert!(matches!(
        wait.read_current().await,
        Err(ReadError::Unavailable)
    ));
    drop(wait);
    assert_eq!(
        server
            .join()
            .map_err(|_| anyhow::anyhow!("wrong purpose peer"))??,
        1
    );
    assert_eq!(owner_bytes(&f.f.original.session)?, before);
    f.finish(false).await?;
    Ok(())
}
