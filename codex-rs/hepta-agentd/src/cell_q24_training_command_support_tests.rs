//! Explicit same-process transport fixture. Public bootstraps still refuse
//! this custody. Native owners and both journals in the caller are actual.

use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_neuron::AnchorWitnessStore;

use super::super::super::Channel as EvidenceChannel;
use super::super::super::LearningIterationEvidenceClientV1;
use super::super::Channel;
use super::super::OriginalCellQ24TrainingCommandClientV1;
use super::super::OriginalCellQ24TrainingCommandContextV1;
use super::super::OriginalCellQ24TrainingCommandReceiptV1;
use super::super::wire;
use super::OriginalCellQ24TrainingCommandOwnerV1;
use crate::AgentdRootAuthorityPeer;
use crate::root_observation_stream::RootObservationStream;

pub(crate) fn pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: this fixture opens a lifetime descriptor for its own live process.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(fd >= 0, "fixture pidfd");
    // SAFETY: the syscall returned a new owned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

pub(crate) fn identity() -> anyhow::Result<AgentdRootAuthorityPeer> {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("fixture process stat"))?
            .1
            .split_whitespace()
            .nth(19)
            .ok_or_else(|| anyhow::anyhow!("fixture start ticks"))?
            .parse()?,
    })
}

fn channel(stream: UnixStream, timeout: Duration) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            // SAFETY: observe the fixture process's credentials.
            peer: HostIssuerPeer {
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout,
            lifetime: Duration::from_secs(300),
            request_bound: 16_384,
            response_bound: 16_384,
        },
        pidfd()?,
    )?)
}

pub(crate) fn client(
    context: OriginalCellQ24TrainingCommandContextV1,
    readback_only: bool,
    retained: Option<OriginalCellQ24TrainingCommandReceiptV1>,
) -> anyhow::Result<(
    OriginalCellQ24TrainingCommandClientV1,
    HostAuthorityPeerChannel,
)> {
    let (stream, server) = UnixStream::pair()?;
    let binding = context.binding()?;
    Ok((
        OriginalCellQ24TrainingCommandClientV1 {
            channel: Mutex::new(Some(Channel {
                peer: channel(stream, Duration::from_secs(30))?,
                next_request_id: 1,
                execution_requested: readback_only,
            })),
            context,
            binding,
            retained: Mutex::new(retained),
        },
        channel(server, Duration::from_secs(30))?,
    ))
}

pub(crate) fn evidence_client(
    context: &OriginalCellQ24TrainingCommandContextV1,
) -> anyhow::Result<(LearningIterationEvidenceClientV1, HostAuthorityPeerChannel)> {
    let (stream, server) = UnixStream::pair()?;
    // SAFETY: this private fixture alone admits its own UID and process.
    let uid = unsafe { libc::geteuid() };
    let transport = RootObservationStream::from_stream_for_uid(
        stream,
        identity()?,
        pidfd()?,
        Duration::from_millis(500),
        Duration::from_secs(300),
        uid,
    )?;
    Ok((
        LearningIterationEvidenceClientV1 {
            channel: Mutex::new(Some(EvidenceChannel {
                transport,
                next_request_id: 1,
            })),
            initial: context.validate()?,
            actor_id: context.dataset.owners.trainer.clone(),
            verifier: context.verifier.clone(),
        },
        channel(server, Duration::from_millis(500))?,
    ))
}

pub(crate) fn serve<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, super::Error>> {
    std::thread::spawn(move || owner.serve_command_channel(&mut channel))
}

pub(crate) fn serve_evidence<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<Result<u64, super::Error>> {
    std::thread::spawn(move || owner.serve_evidence_channel(&mut channel))
}

pub(crate) fn lose_ack<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
    mut channel: HostAuthorityPeerChannel,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let mut completed_before_ack = false;
        let result = channel.exchange(|bytes| {
            let response = owner
                .command_response(bytes, 1)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            let response: wire::Response = serde_json::from_slice(&response)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            if !matches!(response.result, wire::CommandResult::Completed { .. }) {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            completed_before_ack = true;
            // The actual native/Generator completion exists. Only its response
            // is lost here; this injects no completion bytes or signature.
            Err(HostIssuerTransportError::Unavailable)
        });
        anyhow::ensure!(
            completed_before_ack,
            "actual original completion before lost ACK"
        );
        anyhow::ensure!(result.is_err(), "lost ACK closes the original channel");
        Ok(())
    })
}

pub(crate) fn reject_wrong_actor<
    TW: AnchorWitnessStore + Send + 'static,
    RW: AnchorWitnessStore + Send + 'static,
>(
    owner: Arc<OriginalCellQ24TrainingCommandOwnerV1<TW, RW>>,
) -> std::thread::JoinHandle<anyhow::Result<()>> {
    std::thread::spawn(move || {
        let mut request = wire::Request::new(
            &owner.context,
            owner.binding,
            1,
            wire::Action::Execute,
            false,
        );
        request.actor_id = "unregistered-command-actor".into();
        anyhow::ensure!(
            owner
                .command_response(&serde_json::to_vec(&request)?, 1)
                .is_err()
        );
        Ok(())
    })
}

pub(crate) fn reject_cancelled_queued_dispatch(
    context: OriginalCellQ24TrainingCommandContextV1,
) -> anyhow::Result<()> {
    std::thread::spawn(move || -> anyhow::Result<()> {
        let runtime = tokio::runtime::Builder::new_current_thread()
            .max_blocking_threads(1)
            .enable_all()
            .build()?;
        runtime.block_on(async move {
            let (client, mut channel) = client(context, false, None)?;
            let server = std::thread::spawn(move || -> anyhow::Result<()> {
                let mut delivered = false;
                let result = channel.exchange(|_| {
                    delivered = true;
                    Err(HostIssuerTransportError::Unavailable)
                });
                anyhow::ensure!(!delivered, "cancelled queued request reached the socket");
                anyhow::ensure!(matches!(result, Ok(false)), "unused connection must close");
                Ok(())
            });

            // Occupy the only blocking worker before polling the real client.
            // The Execute future has sampled false and moved its original
            // connection before its socket-request closure can begin.
            let (occupied_tx, occupied_rx) = tokio::sync::oneshot::channel();
            let (release_tx, release_rx) = std::sync::mpsc::channel();
            let blocker = tokio::task::spawn_blocking(move || {
                let _ = occupied_tx.send(());
                release_rx.recv()
            });
            occupied_rx.await?;
            let cancellation = Arc::new(AtomicBool::new(false));
            let mut execute = Box::pin(client.execute_training(Arc::clone(&cancellation)));
            std::future::poll_fn(|cx| {
                match std::future::Future::poll(execute.as_mut(), cx) {
                    std::task::Poll::Pending => std::task::Poll::Ready(()),
                    std::task::Poll::Ready(_) => panic!("Execute must queue behind the blocker"),
                }
            })
            .await;
            cancellation.store(true, Ordering::Release);
            release_tx.send(())?;
            blocker.await??;
            anyhow::ensure!(
                matches!(execute.await, Err(super::Error::Cancelled)),
                "the original cancellation token must be sampled before sending"
            );
            anyhow::ensure!(
                matches!(client.readback().await, Err(super::Error::Unavailable)),
                "cancellation must consume the original connection"
            );
            anyhow::ensure!(
                matches!(
                    client.execute_training(Arc::new(AtomicBool::new(false))).await,
                    Err(super::Error::Unavailable)
                ),
                "cancellation must not restore an executable connection"
            );
            drop(client);
            server.join().expect("cancelled original socket")?;
            Ok(())
        })
    })
    .join()
    .expect("queued cancellation runtime")
}
