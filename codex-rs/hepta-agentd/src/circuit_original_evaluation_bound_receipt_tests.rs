//! Bound receipt-only reduction on the original finite Trainer connection.
use anyhow::Context as _;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellEvaluationCommandErrorV1 as CommandError;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_bound_middle_receipt_rejects_wrong_order_reuse_and_cancellation()
-> anyhow::Result<()> {
    let fixture = Box::pin(TrainingFixture::new(Control::Original)).await?;
    let upstream = fixture.host.upstream_files()?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    let completed = client.execute_evaluation().await?;
    assert_eq!(fixture.requests(), 4);
    let original = fixture.host.original_files()?;
    let host = Arc::clone(fixture.host.host.as_ref().context("original Bound host")?);
    tokio::task::spawn_blocking(move || host.fixture_bound_middle_lifecycle(&completed)).await??;
    // Six complete first-panel prefixes, no replacement endpoint and no
    // physical read from any refused/reused/unverified middle capability.
    assert_eq!(fixture.requests(), 10);
    assert_eq!(fixture.current_responses(), 10);
    assert_eq!(fixture.host.original_files()?, original);
    assert_eq!(fixture.host.upstream_files()?, upstream);
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.finish().await?.0, 10);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_bound_readback_keeps_last_training_and_actual_source_tail() -> anyhow::Result<()>
{
    let (entered, reached) = tokio::sync::oneshot::channel();
    let (resume, proceed) = std::sync::mpsc::channel();
    let fixture = Box::pin(TrainingFixture::new(Control::PauseAt {
        request: 6,
        entered,
        release: proceed,
    }))
    .await?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    client.execute_evaluation().await?;
    assert_eq!(fixture.requests(), 4);
    let original = fixture.host.original_files()?;
    let upstream = fixture.host.upstream_files()?;
    let client = Arc::new(client);
    let active = Arc::clone(&client);
    let read = tokio::spawn(async move { active.readback().await });
    reached.await?;
    let withdrawal = fixture.host.retention_b.withdraw_target();
    resume.send(())?;
    withdrawal?;
    assert!(matches!(
        read.await?,
        Err(CommandError::PredecessorUnavailable)
    ));
    assert_eq!(fixture.requests(), 6);
    assert_eq!(fixture.current_responses(), 6);
    assert_ne!(fixture.host.upstream_files()?, upstream);
    assert_eq!(fixture.host.original_files()?, original);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert_eq!(fixture.requests(), 6);
    let client =
        Arc::try_unwrap(client).map_err(|_| anyhow::anyhow!("completed Bound readback"))?;
    assert_eq!(finish(client, peer)?, 3);
    assert_eq!(fixture.host.original_files()?, original);
    assert_eq!(fixture.finish().await?.0, 6);
    Ok(())
}
