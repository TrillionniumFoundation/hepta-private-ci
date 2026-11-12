//! Same-process wire/queue fixtures for the new client. Public construction
//! still rejects this peer. Profile/grants come from the actual Root fixture;
//! a signed synthetic completion tests decoding, not role CURRENT or adoption.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::os::fd::FromRawFd;
use std::sync::atomic::AtomicUsize;

fn held_pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: observe the current test process, then own the new descriptor once.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(raw >= 0, "{}", std::io::Error::last_os_error());
    // SAFETY: successful pidfd_open returned a new, unowned descriptor.
    Ok(unsafe { OwnedFd::from_raw_fd(i32::try_from(raw)?) })
}

fn peer_channel(stream: UnixStream) -> anyhow::Result<HostAuthorityPeerChannel> {
    Ok(HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid: rustix::process::geteuid().as_raw(),
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(30),
            lifetime: Duration::from_secs(300),
            request_bound: wire::BOUND,
            response_bound: wire::BOUND,
        },
        held_pidfd()?,
    )?)
}

fn fixture_client(
    profile: RootResidentLearningProfileV3,
    verifier: LearningEvidenceVerifierV1,
) -> anyhow::Result<(Arc<AgentdRootResidentLearningClientV3>, UnixStream)> {
    profile.require_verifier(&verifier)?;
    let authorization = profile::authorization_binding(&profile, &profile.intent, &profile.lease)?;
    let (stream, server) = UnixStream::pair()?;
    let peer = peer_channel(stream)?;
    Ok((Arc::new(AgentdRootResidentLearningClientV3 {
        channel: Arc::new(Mutex::new(Some(ResidentChannelV3 {
            peer, next: 1, execution_requested: false, retained: None,
        }))),
        lane: Arc::new(Semaphore::new(1)),
        profile, verifier, authorization, origin: Arc::new(ClientOriginV3::Fresh),
    }), server))
}

pub(in crate::authority_host_service::resident) fn queued_admit_cancellation(
    profile: RootResidentLearningProfileV3,
    verifier: LearningEvidenceVerifierV1,
) -> anyhow::Result<()> {
    let (client, mut peer) = fixture_client(profile, verifier)?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all().max_blocking_threads(1).build()?;
    let (entered, started) = std::sync::mpsc::sync_channel(1);
    let (release, wait) = std::sync::mpsc::sync_channel(1);
    let blocked = runtime.spawn_blocking(move || -> anyhow::Result<()> {
        entered.send(())?;
        wait.recv_timeout(Duration::from_secs(10))?;
        Ok(())
    });
    started.recv_timeout(Duration::from_secs(2))?;
    runtime.block_on(async {
        let pending_client = Arc::clone(&client);
        let pending = tokio::spawn(async move {
            AgentdRootResidentLearningClientV3::admit_after_original_claim(&pending_client).await
        });
        // The original channel has actually moved into the one queued closure,
        // while the sole blocking worker is deterministically held above.
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if client.channel.try_lock().expect("client slot").is_none() {
                    break;
                }
                tokio::task::yield_now().await;
            }
        }).await?;
        pending.abort();
        assert!(pending.await.is_err());
        release.send(())?;
        blocked.await??;
        peer.set_read_timeout(Some(Duration::from_secs(2)))?;
        let mut byte = [0_u8; 1];
        assert_eq!(peer.read(&mut byte)?, 0, "cancelled queued Admit wrote a frame");
        assert!(client.channel.try_lock().expect("client slot").is_none());
        assert!(matches!(client.readback().await, Err(Error::Unavailable)));
        Ok::<_, anyhow::Error>(())
    })
}

pub(in crate::authority_host_service::resident) fn uncertain_then_readback(
    profile: RootResidentLearningProfileV3,
    verifier: LearningEvidenceVerifierV1,
    completed: LearningIterationSnapshotV1,
    signatures: Vec<SignedLearningEvidenceV1>,
) -> anyhow::Result<()> {
    let (client, peer) = fixture_client(profile.clone(), verifier)?;
    let mut peer = peer_channel(peer)?;
    let frames = Arc::new(AtomicUsize::new(0));
    let admissions = Arc::new(AtomicUsize::new(0));
    let server_frames = Arc::clone(&frames);
    let server_admissions = Arc::clone(&admissions);
    let expected = completed.clone();
    let expected_signatures = signatures.clone();
    let authorization = client.authorization.to_string();
    let server = std::thread::spawn(move || -> anyhow::Result<()> {
        for id in 1..=2 {
            let result = if id == 1 {
                wire::Reply::Uncertain
            } else {
                wire::encode_current(super::super::runtime::ResidentRuntimeObservationV3 {
                    snapshot: Some(completed.clone()), attestations: signatures.clone(),
                    dispatch_pending: false,
                })?
            };
            assert!(peer.exchange(|bytes| {
                let request: wire::Request = serde_json::from_slice(bytes)
                    .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
                if request.schema != 3 || request.operation != wire::OPERATION
                    || request.request_id != id || request.profile != profile.binding.to_string()
                    || request.authorization != authorization
                {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                server_frames.fetch_add(1, Ordering::SeqCst);
                if request.action == wire::Action::Admit {
                    server_admissions.fetch_add(1, Ordering::SeqCst);
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                serde_json::to_vec(&wire::Response {
                    schema: 3, operation: wire::OPERATION.into(), request_id: id,
                    profile: request.profile, authorization: request.authorization,
                    action: request.action, result,
                }).map_err(|_| HostIssuerTransportError::InvalidRequest)
            })?);
        }
        Ok(())
    });
    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
    let readback = runtime.block_on(async {
        assert!(matches!(client.readback().await, Err(Error::CommitUncertain)));
        // A refused preflight cannot claim A's outbox or later become fresh.
        assert!(matches!(client.require_fresh_admission_channel(), Err(Error::CommitUncertain)));
        let readback = client.readback().await?;
        assert_eq!(readback.snapshot(), Some(&expected));
        assert_eq!(readback.attestations(), expected_signatures.as_slice());
        assert!(!readback.dispatch_pending());
        assert!(LearningIterationCoordinatorV1::from_snapshot(expected.clone())?.next_stage().is_none());
        assert!(matches!(client.require_fresh_admission_channel(), Err(Error::CommitUncertain)));
        Ok::<_, anyhow::Error>(readback)
    });
    drop(client);
    server.join().map_err(|_| anyhow::anyhow!("resident fixture peer panicked"))??;
    readback?;
    assert_eq!(frames.load(Ordering::SeqCst), 2);
    assert_eq!(admissions.load(Ordering::SeqCst), 0);
    Ok(())
}
