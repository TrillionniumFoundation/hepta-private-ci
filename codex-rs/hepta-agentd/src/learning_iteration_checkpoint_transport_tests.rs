//! Same-UID protocol fixtures with real fd pinning and file/fsync CAS.
//! These do not qualify production Root custody or independent learning owners.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
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

#[tokio::test]
async fn learning_checkpoint_commit_without_ack_requires_fresh_original_connection()
-> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let initial = &history[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = Arc::new(FileCas::create(
        &path,
        &LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?,
    )?);
    store.failure.store(2, Ordering::SeqCst); // fsync succeeds; acknowledgement is lost.
    let (first, server) = client(initial);
    let worker = serve(server, owner(store.clone(), initial));
    assert_eq!(
        first.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert_eq!(
        first.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert!(worker.join().unwrap().is_err());
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    let committed = std::fs::read(&path)?;
    let reopened = Arc::new(FileCas::reopen(&path)?);
    let (second, server) = client(initial);
    let worker = serve(server, owner(reopened.clone(), initial));
    assert_eq!(
        second.restore(&initial.request).await?,
        Some(initial.clone())
    );
    assert_eq!(
        second.checkpoint(Digest32::ZERO, initial).await?,
        initial.head_digest
    );
    assert_eq!(reopened.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, committed);
    drop(second);
    worker.join().unwrap()?;
    Ok(())
}

#[test]
fn learning_checkpoint_wrong_purpose_binding_sequence_and_capacity_never_write()
-> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let initial = &history[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = Arc::new(FileCas::create(
        &path,
        &LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?,
    )?);
    let backend = owner(store.clone(), initial);
    let original = std::fs::read(&path)?;
    for change in 0..5 {
        let mut request = Request {
            schema: 1,
            operation: OPERATION.into(),
            request_id: 1,
            binding: initial.head_digest.to_string(),
            command: Command::Restore,
        };
        match change {
            0 => request.operation = "runtime.cognitive.checkpoint.v1".into(),
            1 => request.binding = Digest32::of_bytes(b"other iteration").to_string(),
            2 => request.request_id = 2,
            3 => {
                request.command = Command::Checkpoint {
                    expected_head: Digest32::ZERO.to_string(),
                    snapshot: "a".repeat(FRAME_BOUND),
                }
            }
            4 => {
                request.command = Command::Checkpoint {
                    expected_head: Digest32::ZERO.to_string(),
                    snapshot: "not base64!".into(),
                }
            }
            _ => unreachable!(),
        }
        assert!(
            backend
                .exchange_learning_checkpoint(&serde_json::to_vec(&request)?, &mut 1)
                .is_err()
        );
        assert_eq!(std::fs::read(&path)?, original);
        assert_eq!(store.commits.load(Ordering::SeqCst), 0);
    }
    Ok(())
}

#[tokio::test]
async fn learning_checkpoint_wrong_semantic_ack_consumes_original_lane() -> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let initial = &history[0];
    let (client, mut server) = client(initial);
    let worker = std::thread::spawn(move || {
        let mut length = [0; 4];
        server.read_exact(&mut length).unwrap();
        let mut bytes = vec![0; u32::from_be_bytes(length) as usize];
        server.read_exact(&mut bytes).unwrap();
        let request: Request = serde_json::from_slice(&bytes).unwrap();
        let response = serde_json::to_vec(&Response {
            schema: 1,
            request_id: request.request_id,
            binding: request.binding,
            result: Reply::Committed {
                head: Digest32::of_bytes(b"wrong checkpoint").to_string(),
            },
        })
        .unwrap();
        server
            .write_all(&(response.len() as u32).to_be_bytes())
            .unwrap();
        server.write_all(&response).unwrap();
        server
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        assert_eq!(server.read(&mut [0]).unwrap(), 0);
    });
    assert_eq!(
        client.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    assert_eq!(
        client.restore(&initial.request).await,
        Err(Error::Store(AuthorityTrustError::Unavailable))
    );
    worker.join().unwrap();
    Ok(())
}

#[tokio::test]
async fn learning_checkpoint_cancel_after_commit_requires_original_owner_reconciliation()
-> anyhow::Result<()> {
    let history = snapshots(Decision::Update)?;
    let initial = &history[0];
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("original");
    let store = Arc::new(FileCas::create(
        &path,
        &LearningIterationCheckpointRecordV1::vacant(
            initial.request.clone(),
            initial.owners.clone(),
        )?,
    )?);
    let (first, server) = client(initial);
    let first = Arc::new(first);
    let backend = owner(store.clone(), initial);
    let (committed_tx, committed_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
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
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy, pidfd()).unwrap();
        let mut next = 1;
        let mut committed_tx = Some(committed_tx);
        let result = channel.exchange(|bytes| {
            let response = backend.exchange_learning_checkpoint(bytes, &mut next)?;
            committed_tx.take().unwrap().send(()).unwrap();
            release_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            Ok(response)
        });
        assert!(result.is_err());
    });
    let pending_client = Arc::clone(&first);
    let pending_snapshot = initial.clone();
    let pending = tokio::spawn(async move {
        pending_client
            .checkpoint(Digest32::ZERO, &pending_snapshot)
            .await
    });
    committed_rx.await?;
    pending.abort();
    assert!(pending.await.unwrap_err().is_cancelled());
    assert_eq!(store.commits.load(Ordering::SeqCst), 1);
    let committed = std::fs::read(&path)?;
    assert_eq!(
        first.restore(&initial.request).await,
        Err(Error::Store(AuthorityTrustError::Unavailable))
    );
    assert_eq!(
        first.checkpoint(Digest32::ZERO, initial).await,
        Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
    );
    release_tx.send(())?;
    worker.join().unwrap();
    assert_eq!(std::fs::read(&path)?, committed);

    let reopened = Arc::new(FileCas::reopen(&path)?);
    let (recovered, server) = client(initial);
    let worker = serve(server, owner(reopened.clone(), initial));
    assert_eq!(
        recovered.restore(&initial.request).await?,
        Some(initial.clone())
    );
    assert_eq!(
        recovered.checkpoint(Digest32::ZERO, initial).await?,
        initial.head_digest
    );
    assert_eq!(reopened.commits.load(Ordering::SeqCst), 0);
    assert_eq!(std::fs::read(&path)?, committed);
    drop(recovered);
    worker.join().unwrap()?;
    Ok(())
}
