//! Cancellation retains the same actual cleanup task, never a synthetic receipt.
use super::*;
use pretty_assertions::assert_eq;
use std::future::Future;
use std::task::Poll;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_cancelled_cleanup_await_rejoins_same_actual_task() -> TestResult<()>
{
    let (input, worker, bytes) = input_and_worker("selected-cancelled-cleanup")?;
    let fixture = Fixture::new(input.output.join("cancel-owner"), &bytes)?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    let (inputs, issuer, authority) = inputs(
        worker,
        &input.output.join("cancel-effects"),
        /*expected_claims*/ 1,
    )
    .await?;
    let mut owner =
        prepare_selected_initial_smollm_v1(fixture.config("body")?, material, current, inputs)
            .await?;
    let port = Arc::clone(owner.session.port.as_ref().unwrap());
    let (entered_tx, entered_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    // Gate only scheduling of the real port.shutdown. No model, terminal
    // receipt, time limit, driver success or original issuer response is faked.
    owner.cleanup = Some(owner.session.runtime.spawn_blocking(move || {
        entered_tx
            .send(())
            .map_err(|_| "cleanup latch closed".to_owned())?;
        release_rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .map_err(|e| e.to_string())?;
        port.shutdown()
    }));
    entered_rx.await?;
    let task_id = owner.cleanup.as_ref().unwrap().id();
    let mut waiting = Box::pin(owner.shutdown());
    std::future::poll_fn(|cx| {
        assert!(matches!(waiting.as_mut().poll(cx), Poll::Pending));
        Poll::Ready(())
    })
    .await;
    drop(waiting);
    assert_eq!(owner.cleanup.as_ref().unwrap().id(), task_id);
    assert!(owner.material.is_none());
    release_tx.send(())?;
    while !owner.cleanup.as_ref().unwrap().is_finished() {
        tokio::task::yield_now().await;
    }
    owner.shutdown().await?;
    assert!(owner.cleanup.is_none());
    assert!(owner.session.port.is_none());
    assert!(owner.with_current_initial_load(|_| Ok(())).is_err());
    issuer.await?.map_err(issuer_error)?;
    archive_authority(&authority, &input.output)?;
    Ok(())
}
