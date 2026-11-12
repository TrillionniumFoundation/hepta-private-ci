//! Real bounded T transport and actual B/retention owners; no replacement T
//! replies or CURRENT DTOs. Each case retains the original 60-second budget.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellEvaluationCommandErrorV1 as CommandError;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_training_proof_rejects_new_source_reentry_and_incomplete_slots()
-> anyhow::Result<()> {
    let fixture = Box::pin(TrainingFixture::new(Control::Original)).await?;
    let before = fixture.host.upstream_files()?;
    let evaluator = fixture.host.original_files()?;
    tokio::task::block_in_place(|| {
        fixture
            .host
            .host
            .as_ref()
            .unwrap()
            .fixture_training_proof_lifecycle()
    })?;
    assert_eq!(fixture.requests(), 5);
    assert_eq!(fixture.current_responses(), 5);
    assert_eq!(fixture.host.upstream_files()?, before);
    assert_eq!(fixture.host.original_files()?, evaluator);
    assert_eq!(fixture.finish().await?.0, 5);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_same_call_training_keeps_four_execute_and_three_readback_frames()
-> anyhow::Result<()> {
    let fixture = Box::pin(TrainingFixture::new(Control::Original)).await?;
    let upstream = fixture.host.upstream_files()?;
    let missing = fixture.host.original_files()?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    // Missing does not complete or retain a partial proof. The next call must
    // perform a new first actual T read on the same finite channel.
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Missing)
    ));
    assert_eq!(fixture.requests(), 1);
    assert_eq!(fixture.host.original_files()?, missing);
    let original = client.execute_evaluation().await?;
    assert_eq!(fixture.requests(), 5);
    let completed = fixture.host.original_files()?;
    assert_ne!(completed, missing);
    assert_eq!(client.readback().await?, original);
    assert_eq!(fixture.requests(), 8);
    assert_eq!(client.readback().await?, original);
    assert_eq!(fixture.requests(), 11);
    assert_eq!(fixture.current_responses(), 11);
    assert_eq!(finish(client, peer)?, 4);
    assert_eq!(fixture.host.original_files()?, completed);
    assert_eq!(fixture.host.upstream_files()?, upstream);
    assert_eq!(fixture.finish().await?.0, 11);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_last_actual_training_failure_never_returns_or_resigns_b()
-> anyhow::Result<()> {
    let fixture = Box::pin(TrainingFixture::new(Control::WithdrawNativeAt(4))).await?;
    let before = fixture.host.original_files()?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    assert!(client.execute_evaluation().await.is_err());
    assert_eq!(fixture.requests(), 4);
    assert_eq!(fixture.current_responses(), 3);
    // The unchanged receipt owner already committed before the last panel
    // read. This is an uncertain durable effect, not a no-effect assertion.
    let durable = fixture.host.original_files()?;
    assert_ne!(durable, before);
    assert_eq!(finish(client, peer)?, 1);
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    assert!(matches!(
        client.execute_evaluation().await,
        Err(CommandError::ReadbackRequired)
    ));
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert_eq!(fixture.requests(), 4);
    assert_eq!(fixture.host.original_files()?, durable);
    assert_eq!(finish(client, peer)?, 2);
    assert_eq!(fixture.finish().await?.0, 4);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_last_training_slot_keeps_the_actual_cohort_tail() -> anyhow::Result<()> {
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let fixture = Box::pin(TrainingFixture::new(Control::PauseAt {
        request: 4,
        entered,
        release: blocked,
    }))
    .await?;
    let before = fixture.host.original_files()?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    let client = Arc::new(client);
    let active = Arc::clone(&client);
    let request = tokio::spawn(async move { active.execute_evaluation().await });
    observed.await?;
    // Last T is unchanged. A real non-T Source withdrawal at that exact slot
    // must still be detected by the original retention cohort's physical tail.
    let withdrawal = fixture.host.retention_b.withdraw_target();
    release.send(())?;
    withdrawal?;
    assert!(request.await?.is_err());
    assert_eq!(fixture.requests(), 4);
    assert_eq!(fixture.current_responses(), 4);
    let durable = fixture.host.original_files()?;
    assert_ne!(durable, before);
    let client = Arc::try_unwrap(client).map_err(|_| anyhow::anyhow!("completed B request"))?;
    assert_eq!(finish(client, peer)?, 1);
    let (client, peer) = fixture.host.commands(true, None, "original")?;
    assert!(matches!(
        client.readback().await,
        Err(CommandError::CommitUncertain)
    ));
    assert_eq!(fixture.requests(), 4);
    assert_eq!(fixture.host.original_files()?, durable);
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.finish().await?.0, 4);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_panel_cancel_keeps_the_held_lane_and_consumed_channel() -> anyhow::Result<()> {
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let fixture = Box::pin(TrainingFixture::new(Control::PauseAt {
        request: 1,
        entered,
        release: blocked,
    }))
    .await?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    let client = Arc::new(client);
    let active = Arc::clone(&client);
    let request = tokio::spawn(async move { active.execute_evaluation().await });
    observed.await?;
    request.abort();
    assert!(request.await.unwrap_err().is_cancelled());
    let (contender, contender_peer) = fixture.host.commands(true, None, "original")?;
    let occupied = contender.readback().await;
    release.send(())?;
    assert!(matches!(occupied, Err(CommandError::Busy)));
    assert_eq!(finish(contender, contender_peer)?, 1);
    assert!(matches!(
        client.readback().await,
        Err(CommandError::Unavailable)
    ));
    let client = Arc::try_unwrap(client).map_err(|_| anyhow::anyhow!("canceled B client"))?;
    // The original blocking exchange finishes naturally. Canceling its waiter
    // cannot free the owner lane or reopen the taken transport.
    assert_eq!(finish(client, peer)?, 1);
    assert_eq!(fixture.requests(), 4);
    assert_eq!(fixture.current_responses(), 4);
    assert!(
        fixture
            .host
            .host
            .as_ref()
            .unwrap()
            .fixture_dispatch_consumed()
    );
    let durable = fixture.host.original_files()?;
    let (client, peer) = fixture.host.commands(false, None, "original")?;
    assert!(matches!(
        client.execute_evaluation().await,
        Err(CommandError::ReadbackRequired)
    ));
    let original = client.readback().await?;
    assert_eq!(
        original.training_attestation(),
        &fixture.host.original.config.training_evidence
    );
    assert_eq!(fixture.requests(), 7);
    assert_eq!(fixture.host.original_files()?, durable);
    assert_eq!(finish(client, peer)?, 2);
    assert_eq!(fixture.finish().await?.0, 7);
    Ok(())
}
