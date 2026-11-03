//! The real control socket observes the original Objective, Core QueueStore,
//! canonical owners and native writer. Only the existing transport ACK is held.

use super::*;
use codex_uds::UnixStream;
use pretty_assertions::assert_eq;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::control::AgentdControlServer;
use crate::{AgentdClient, AgentdRequest, ObjectiveStartOutcome};

const WAIT: Duration = Duration::from_secs(15);

struct Control {
    client: AgentdClient,
    cancellation: CancellationToken,
    task: JoinHandle<std::result::Result<(), AgentdError>>,
}

impl Control {
    async fn start(fixture: &ObjectiveFixture) -> Result<Self> {
        let identity = fixture.base.state.identity();
        let cancellation = CancellationToken::new();
        let server = AgentdControlServer::bind(identity.control_socket.clone(),
            fixture.base.state.clone(), cancellation.clone()).await?;
        let client = AgentdClient::new(identity.control_socket.clone(),
            identity.agent_id.clone(), identity.spawn_generation)?;
        Ok(Self { client, cancellation, task: tokio::spawn(server.run()) })
    }

    async fn stop(self) -> Result<()> {
        self.cancellation.cancel();
        timeout(WAIT, self.task).await.context("control connections did not join")???;
        Ok(())
    }
}

fn admission(outcome: ObjectiveStartOutcome) -> Result<ObjectiveRunAdmission> {
    match outcome {
        ObjectiveStartOutcome::Admitted { receipt } => Ok(receipt),
        ObjectiveStartOutcome::Conflict { run_id, conflict_digest } =>
            anyhow::bail!("original Objective conflicted: {run_id}/{conflict_digest}"),
    }
}

async fn original_ack(fixture: &ObjectiveFixture) -> Result<()> {
    timeout(WAIT, async {
        while fixture.queue.acknowledged.load(Ordering::SeqCst) == 0 {
            tokio::task::yield_now().await;
        }
    }).await.context("original QueueStore ACK was cancelled with its observer")?;
    assert_eq!(fixture.queue.acknowledged.load(Ordering::SeqCst), 1);
    Ok(())
}

async fn assert_original_once(fixture: &ObjectiveFixture, server: &MockServer) -> Result<()> {
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.base.final_use.capacity()?.used_nonces,
        server.received_requests().await.context("model HTTP capture")?.len()), (1, 1, 1, 1));
    assert!(fixture.queue.service()?.list(fixture.core.session_configured.thread_id).await?.is_empty());
    assert_eq!(fixture.base.state.native_run_receipt(&fixture.request.body.run_id)?.phase, RunPhase::Succeeded);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_control_observes_original_queue_ack_beyond_two_seconds() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::HoldAfterQueue).await?;
    let control = Control::start(&fixture).await?;
    let original = {
        let pending = control.client.objective_start(fixture.request.clone());
        tokio::pin!(pending);
        tokio::select! {
            result = &mut pending => anyhow::bail!("reply escaped the original queue hold: {result:?}"),
            reached = timeout(WAIT, fixture.queue.wait_until_held()) => reached?,
        }
        let original = (fixture.host.original_record(&fixture.request.body.run_id)?,
            fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?);
        assert!(original.1.is_some(), "queue hold must follow durable preparation");
        assert_eq!(fixture.queue.reconciles.load(Ordering::SeqCst), 1);
        // This exceeds the old whole-request two-second cutoff while retaining
        // the original queue owner's unchanged five-second reply deadline.
        tokio::time::sleep(Duration::from_millis(2250)).await;
        assert!(control.client.health().await?.ready);
        assert_eq!(fixture.queue.acknowledged.load(Ordering::SeqCst), 0);
        fixture.queue.release_reply();
        assert!(!admission(pending.await?)?.idempotent);
        original
    };
    completed_turn(&fixture.core).await?;
    assert!(admission(control.client.objective_start(fixture.request.clone()).await?)?.idempotent);
    assert_eq!((fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?), original);
    assert_original_once(&fixture, &server).await?;
    control.stop().await?;
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_control_disconnect_keeps_the_original_durable_owner() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::HoldAfterQueue).await?;
    let control = Control::start(&fixture).await?;
    let identity = fixture.base.state.identity();
    let mut stream = UnixStream::connect(&identity.control_socket).await?;
    let request = AgentdRequest::objective_start(/*request_id*/ 77,
        identity.spawn_generation, fixture.request.clone());
    let mut bytes = serde_json::to_vec(&request)?;
    bytes.push(b'\n');
    stream.write_all(&bytes).await?;
    timeout(WAIT, fixture.queue.wait_until_held()).await?;
    let original = (fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?);
    assert!(original.1.is_some());
    drop(stream);
    fixture.queue.release_reply();
    original_ack(&fixture).await?;
    completed_turn(&fixture.core).await?;
    assert!(admission(control.client.objective_start(fixture.request.clone()).await?)?.idempotent);
    assert_eq!((fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?), original);
    assert_original_once(&fixture, &server).await?;
    control.stop().await?;
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_control_observer_timeout_reconciles_the_same_original_key() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::HoldAfterQueue).await?;
    let control = Control::start(&fixture).await?;
    let error = control.client.objective_start_with_timeout(fixture.request.clone(),
        Duration::from_millis(50)).await.err().context("held reply exceeded its observer budget")?;
    ensure!(error.to_string().contains("outcome is unknown"), "timeout lost unknown semantics: {error}");
    timeout(WAIT, fixture.queue.wait_until_held()).await?;
    let original = (fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?);
    assert!(original.1.is_some());
    fixture.queue.release_reply();
    original_ack(&fixture).await?;
    completed_turn(&fixture.core).await?;
    assert!(admission(control.client.objective_start(fixture.request.clone()).await?)?.idempotent);
    assert_eq!((fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?), original);
    assert_original_once(&fixture, &server).await?;
    control.stop().await?;
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_control_preserves_the_original_queue_deadline_and_unknown_record() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::HoldBeforeQueue).await?;
    let control = Control::start(&fixture).await?;
    let error = control.client.objective_start(fixture.request.clone()).await.err()
        .context("original held queue unexpectedly returned an admission")?;
    ensure!(error.to_string().contains("outcome is unknown")
        && error.to_string().contains("original objective queue reply is unknown after timeout"),
        "socket budget replaced the original queue deadline: {error}");
    let original = (fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?);
    assert!(original.1.is_some());
    assert_eq!((fixture.queue.reconciles.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst),
        fixture.base.final_use.capacity()?.used_nonces), (0, 0, 0));
    assert!(admission(control.client.objective_start(fixture.request.clone()).await?)?.idempotent);
    completed_turn(&fixture.core).await?;
    assert_eq!((fixture.host.original_record(&fixture.request.body.run_id)?,
        fixture.host.observe_committed_prepared(&fixture.request.body.run_id)?), original);
    assert_original_once(&fixture, &server).await?;
    control.stop().await?;
    fixture.shutdown().await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn objective_control_shutdown_joins_stalled_connections_and_releases_state() -> Result<()> {
    let server = provider().await;
    let fixture = ObjectiveFixture::new(&server, ReplyFault::None).await?;
    let original_references = Arc::strong_count(&fixture.base.state);
    let control = Control::start(&fixture).await?;
    let mut stream = UnixStream::connect(&fixture.base.state.identity().control_socket).await?;
    stream.write_all(b"{").await?;
    timeout(WAIT, async {
        while Arc::strong_count(&fixture.base.state) < original_references + 2 {
            tokio::task::yield_now().await;
        }
    }).await.context("control did not accept the original stalled connection")?;
    control.stop().await?;
    assert_eq!(Arc::strong_count(&fixture.base.state), original_references);
    let mut bytes = Vec::new();
    // Closing an accepted stream with an unread partial request can reset it.
    // Both EOF and an explicit reset must still carry no response bytes.
    match timeout(WAIT, stream.read_to_end(&mut bytes)).await? {
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        Err(error) => return Err(error.into()),
    }
    assert!(bytes.is_empty());
    assert!(!fixture.base.state.identity().control_socket.exists());
    assert_eq!((fixture.owners.calls.load(Ordering::SeqCst),
        fixture.base.issuer.grants.load(Ordering::SeqCst)), (0, 0));
    fixture.shutdown().await
}
