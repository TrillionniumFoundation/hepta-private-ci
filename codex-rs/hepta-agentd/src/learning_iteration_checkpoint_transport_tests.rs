//! Same-UID protocol fixtures with real fd pinning and file/fsync CAS.
//! These do not qualify production Root custody or independent learning owners.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;
use std::sync::Arc;
use std::sync::atomic::Ordering;

#[path = "learning_iteration_checkpoint_test_support.rs"]
mod support;
use support::Decision;
use support::FileCas;
use support::owner;
use support::snapshots;

fn pidfd() -> OwnedFd {
    // SAFETY: a live test PID and zero flags return a new owned descriptor.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(fd >= 0);
    // SAFETY: this fresh descriptor has no other owner.
    unsafe { OwnedFd::from_raw_fd(fd as i32) }
}

fn peer() -> AgentdRootAuthorityPeer {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")
            .unwrap()
            .trim()
            .into(),
        process_start_ticks: stat
            .rsplit_once(") ")
            .unwrap()
            .1
            .split_whitespace()
            .nth(19)
            .unwrap()
            .parse()
            .unwrap(),
    }
}

fn client(initial: &LearningIterationSnapshotV1) -> (AgentdLearningCheckpointClientV1, UnixStream) {
    let (stream, server) = UnixStream::pair().unwrap();
    // SAFETY: reads the kernel identity, without changing credentials.
    let uid = unsafe { libc::geteuid() };
    let transport = RootObservationStream::from_stream_for_uid(
        stream,
        peer(),
        pidfd(),
        Duration::from_millis(500),
        Duration::from_secs(10),
        uid,
    )
    .unwrap();
    (
        AgentdLearningCheckpointClientV1 {
            channel: Mutex::new(Some(Channel {
                transport,
                next_request_id: 1,
            })),
            initial: initial.clone(),
        },
        server,
    )
}

fn serve(
    server: UnixStream,
    backend: LearningIterationCheckpointOwnerV1,
) -> std::thread::JoinHandle<Result<(), HostIssuerTransportError>> {
    std::thread::spawn(move || {
        // SAFETY: reads the kernel identity, without changing credentials.
        let uid = unsafe { libc::geteuid() };
        let policy = HostAuthorityPeerPolicy {
            peer: HostIssuerPeer {
                uid,
                pid: std::process::id(),
            },
            timeout: Duration::from_millis(500),
            lifetime: Duration::from_secs(10),
            request_bound: FRAME_BOUND,
            response_bound: FRAME_BOUND,
        };
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy, pidfd())?;
        let mut next = 1;
        while channel.exchange(|bytes| backend.exchange_learning_checkpoint(bytes, &mut next))? {}
        Ok(())
    })
}

#[tokio::test]
async fn learning_checkpoint_maximum_histories_cross_real_frames_and_reopen() -> anyhow::Result<()>
{
    for decision in [
        Decision::Update,
        Decision::EvaluatedNoUpdate,
        Decision::ProposedNoUpdate,
    ] {
        let history = snapshots(decision)?;
        let initial = &history[0];
        let directory = tempfile::tempdir()?;
        let path = directory.path().join("original");
        let vacant = LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?;
        let store = Arc::new(FileCas::create(&path, &vacant)?);
        let (client, server) = client(initial);
        let worker = serve(server, owner(store.clone(), initial));
        assert_eq!(client.restore(&initial.request).await?, None);
        for (index, snapshot) in history.iter().enumerate() {
            let predecessor = if index == 0 {
                Digest32::ZERO
            } else {
                history[index - 1].head_digest
            };
            assert_eq!(
                client.checkpoint(predecessor, snapshot).await?,
                snapshot.head_digest
            );
            assert_eq!(
                client.checkpoint(predecessor, snapshot).await?,
                snapshot.head_digest
            );
            assert_eq!(
                client.restore(&initial.request).await?,
                Some(snapshot.clone())
            );
        }
        assert_eq!(store.commits.load(Ordering::SeqCst), history.len());
        assert_eq!(
            client.checkpoint(Digest32::ZERO, initial).await,
            Err(Error::Conflict)
        );
        assert_eq!(
            client.restore(&initial.request).await?,
            history.last().cloned()
        );
        drop(client);
        worker.join().unwrap()?;
        assert_eq!(
            owner(Arc::new(FileCas::reopen(&path)?), initial).restore(&initial.request)?,
            history.last().cloned()
        );
    }
    Ok(())
}
