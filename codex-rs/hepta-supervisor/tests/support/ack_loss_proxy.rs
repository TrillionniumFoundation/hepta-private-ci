//! Transport-only fault fixture: forward the first signed mutation, withhold
//! its acknowledgement, and kill the caller. The real owner still executes.
use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::UnixListener as AsyncUnixListener;
use tokio::net::UnixStream as AsyncUnixStream;
use tokio::sync::oneshot;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

pub(super) struct AckLossProxy {
    pub(super) root: HeptaFleetRoot,
    signed_requests: Arc<AtomicUsize>,
    forwarded: Option<oneshot::Receiver<()>>,
    cancellation: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}

impl AckLossProxy {
    pub(super) async fn start(directory: &Path, upstream: PathBuf) -> Result<Self> {
        let root = HeptaFleetRoot::parse(directory.join("ack-loss-fleet"))?;
        let socket = root.layout().supervisor_socket().to_path_buf();
        std::fs::create_dir_all(socket.parent().context("proxy socket parent")?)?;
        let listener = AsyncUnixListener::bind(socket)?;
        let cancellation = CancellationToken::new();
        let stop = cancellation.clone();
        let signed_requests = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&signed_requests);
        let (forwarded_tx, forwarded_rx) = oneshot::channel();
        let notification = Arc::new(tokio::sync::Mutex::new(Some(forwarded_tx)));
        let task = tokio::spawn(async move {
            let mut handlers = JoinSet::new();
            let capacity = Arc::new(tokio::sync::Semaphore::new(4));
            loop {
                tokio::select! {
                    _ = stop.cancelled() => break,
                    Some(_) = handlers.join_next(), if !handlers.is_empty() => {},
                    incoming = listener.accept() => {
                        let Ok((peer, _)) = incoming else { break };
                        let Ok(permit) = Arc::clone(&capacity).try_acquire_owned() else { continue };
                        let target = upstream.clone();
                        let counter = Arc::clone(&counter);
                        let notification = Arc::clone(&notification);
                        let handler_stop = stop.clone();
                        handlers.spawn(async move {
                            let _permit = permit;
                            let result = relay(peer, target, counter, notification, handler_stop).await;
                            if let Err(error) = result {
                                eprintln!("ack-loss transport: {error:#}");
                            }
                        });
                    }
                }
            }
            handlers.abort_all();
            while handlers.join_next().await.is_some() {}
        });
        Ok(Self {
            root,
            signed_requests,
            forwarded: Some(forwarded_rx),
            cancellation,
            task,
        })
    }

    pub(super) async fn crash_caller_after_forward(
        &mut self,
        request: &Path,
        journal: &Path,
    ) -> Result<()> {
        let mut caller =
            tokio::process::Command::new(env!("CARGO_BIN_EXE_hepta-supervisor-release-controller"))
                .arg("dispatch")
                .arg("--fleet-root")
                .arg(self.root.as_path())
                .arg("--request")
                .arg(request)
                .arg("--journal")
                .arg(journal)
                .arg("--wait-seconds")
                .arg("30")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::inherit())
                .kill_on_drop(true)
                .spawn()?;
        let forwarded = self
            .forwarded
            .take()
            .context("only one intentional lost acknowledgement")?;
        tokio::time::timeout(Duration::from_secs(30), forwarded).await??;
        caller.kill().await?;
        let status = caller.wait().await?;
        use std::os::unix::process::ExitStatusExt;
        ensure!(
            status.signal() == Some(libc::SIGKILL),
            "caller was not killed at the lost-ack cut"
        );
        let retained: ProductionReleaseJournalV1 =
            serde_json::from_slice(&std::fs::read(journal)?)?;
        ensure!(
            retained.status == ProductionReleaseCallerStatusV1::Prepared,
            "caller published a receipt despite withheld acknowledgement"
        );
        Ok(())
    }

    pub(super) fn signed_request_count(&self) -> usize {
        self.signed_requests.load(Ordering::Acquire)
    }
}

impl Drop for AckLossProxy {
    fn drop(&mut self) {
        self.cancellation.cancel();
        self.task.abort(); // Only this test-owned transport task, not the owner.
    }
}

async fn relay(
    peer: AsyncUnixStream,
    target: PathBuf,
    counter: Arc<AtomicUsize>,
    notification: Arc<tokio::sync::Mutex<Option<oneshot::Sender<()>>>>,
    stop: CancellationToken,
) -> Result<()> {
    let (reader, mut writer) = peer.into_split();
    let mut reader = tokio::io::BufReader::new(reader).take(262_145);
    let mut frame = Vec::new();
    tokio::time::timeout(
        Duration::from_secs(10),
        reader.read_until(b'\n', &mut frame),
    )
    .await??;
    ensure!(
        frame.len() <= 262_144 && frame.ends_with(b"\n"),
        "invalid proxy frame"
    );
    let request: serde_json::Value = serde_json::from_slice(&frame)?;
    let signed = matches!(
        request["method"]["type"].as_str(),
        Some("signed_upgrade" | "signed_rollback")
    );
    let ordinal = if signed {
        counter.fetch_add(1, Ordering::AcqRel)
    } else {
        usize::MAX
    };
    let mut upstream = AsyncUnixStream::connect(target).await?;
    upstream.write_all(&frame).await?;
    upstream.shutdown().await?;
    if signed && ordinal == 0 {
        if let Some(sender) = notification.lock().await.take() {
            let _ = sender.send(());
        }
        // Keep the real owner request alive but deliberately never send its ACK
        // to the caller. No authority or result is fabricated by this proxy.
        let mut response = Vec::new();
        let mut upstream = tokio::io::BufReader::new(upstream).take(262_145);
        tokio::time::timeout(
            Duration::from_secs(30),
            upstream.read_until(b'\n', &mut response),
        )
        .await??;
        stop.cancelled().await;
        return Ok(());
    }
    let mut response = Vec::new();
    let mut upstream = tokio::io::BufReader::new(upstream).take(262_145);
    tokio::time::timeout(
        Duration::from_secs(30),
        upstream.read_until(b'\n', &mut response),
    )
    .await??;
    ensure!(
        response.len() <= 262_144 && response.ends_with(b"\n"),
        "invalid upstream frame"
    );
    writer.write_all(&response).await?;
    writer.shutdown().await?;
    Ok(())
}
