//! Wire component tests; same-process peers here prove no Root admission.

use super::*;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use pretty_assertions::assert_eq;
use std::os::fd::FromRawFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::sync::mpsc;
use std::time::Duration;

#[allow(
    clippy::duplicate_mod,
    reason = "reuse bounded synthetic metadata and fsync CAS only for wire component tests"
)]
#[path = "learning_iteration_checkpoint_test_support.rs"]
mod support;

fn channel(stream: UnixStream) -> HostAuthorityPeerChannel {
    // SAFETY: the live current PID is retained for a component-only peer pair.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    assert!(raw >= 0);
    HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            // SAFETY: geteuid reads actual credentials without pointers.
            peer: HostIssuerPeer {
                uid: unsafe { libc::geteuid() },
                pid: std::process::id(),
            },
            timeout: Duration::from_secs(5),
            lifetime: Duration::from_secs(20),
            request_bound: FRAME_LIMIT,
            response_bound: FRAME_LIMIT,
        },
        // SAFETY: successful pidfd_open returned this fresh owned descriptor.
        unsafe { std::os::fd::OwnedFd::from_raw_fd(raw as i32) },
    )
    .unwrap()
}

#[test]
fn maximum_snapshots_fit_complete_frames_and_wrong_scope_never_changes_cas() -> anyhow::Result<()> {
    for decision in [
        support::Decision::Update,
        support::Decision::EvaluatedNoUpdate,
        support::Decision::ProposedNoUpdate,
    ] {
        let states = support::snapshots(decision)?;
        let initial = &states[0];
        let directory = tempfile::tempdir()?;
        let store = Arc::new(support::FileCas::create(
            &directory.path().join("frontier"),
            &LearningIterationCheckpointRecordV1::vacant(
                initial.request.clone(),
                initial.owners.clone(),
            )?,
        )?);
        let mut backend = LearningCheckpointBackend::new(support::owner(store.clone(), initial));
        let mut previous = Digest32::ZERO;
        let mut sequence = 1;
        for state in states.iter() {
            let bytes = encode_frame(&Request {
                schema_version: 1,
                operation: DOMAIN.into(),
                sequence,
                command: Command::Checkpoint {
                    expected_head: previous.to_string(),
                    snapshot: encode_snapshot(state)?,
                },
            })?;
            assert!(bytes.len() <= FRAME_LIMIT);
            let response = backend.exchange(&bytes)?;
            assert!(response.len() <= FRAME_LIMIT);
            let response: Response = serde_json::from_slice(&response)?;
            assert!(
                matches!(response.outcome, Outcome::Committed { ref head } if head == &state.head_digest.to_string())
            );
            sequence += 1;
            previous = state.head_digest;
        }
        let before = std::fs::read(directory.path().join("frontier"))?;
        let mut foreign = initial.request.clone();
        foreign.operation_id = codex_hepta_types::StableId::new("foreign-operation")?;
        let foreign = LearningIterationCoordinatorV1::new(foreign, initial.owners.clone())?;
        let request = encode_frame(&Request {
            schema_version: 1,
            operation: DOMAIN.into(),
            sequence,
            command: Command::Checkpoint {
                expected_head: Digest32::ZERO.to_string(),
                snapshot: encode_snapshot(foreign.snapshot())?,
            },
        })?;
        let response: Response = serde_json::from_slice(&backend.exchange(&request)?)?;
        assert!(matches!(response.outcome, Outcome::Refused));
        assert_eq!(std::fs::read(directory.path().join("frontier"))?, before);
        assert!(
            backend.exchange(&request).is_err(),
            "a replayed sequence must close the owner channel"
        );
    }
    Ok(())
}

#[test]
fn before_send_contention_does_not_claim_commit_or_break_the_inflight_call() -> anyhow::Result<()> {
    let initial = test_data::snapshots()?.remove(0);
    let (left, right) = UnixStream::pair()?;
    let client = Arc::new(AgentdLearningCheckpointClientV1::from_admitted_channel(
        channel(left),
        test_data::OWNER.into(),
        initial.clone(),
    ));
    let (entered_tx, entered_rx) = mpsc::sync_channel(0);
    let (release_tx, release_rx) = mpsc::sync_channel(0);
    std::thread::scope(|scope| -> anyhow::Result<()> {
        let server_initial = initial.clone();
        let server = scope.spawn(move || -> Result<(), HostIssuerTransportError> {
            let mut server = channel(right);
            server.exchange(|bytes| {
                let request: Request = serde_json::from_slice(bytes).unwrap();
                assert!(matches!(request.command, Command::Checkpoint { .. }));
                entered_tx.send(()).unwrap();
                release_rx.recv_timeout(Duration::from_secs(5)).unwrap();
                encode_frame(&Response {
                    schema_version: 1,
                    operation: DOMAIN.into(),
                    sequence: 1,
                    owner_id: test_data::OWNER.into(),
                    binding: server_initial.head_digest.to_string(),
                    outcome: Outcome::Committed {
                        head: server_initial.head_digest.to_string(),
                    },
                })
            })?;
            server.exchange(|bytes| {
                let request: Request = serde_json::from_slice(bytes).unwrap();
                assert!(matches!(request.command, Command::Restore));
                assert_eq!(request.sequence, 2);
                encode_frame(&Response {
                    schema_version: 1,
                    operation: DOMAIN.into(),
                    sequence: 2,
                    owner_id: test_data::OWNER.into(),
                    binding: server_initial.head_digest.to_string(),
                    outcome: Outcome::Current {
                        snapshot: encode_snapshot(&server_initial).unwrap(),
                    },
                })
            })?;
            Ok(())
        });
        let pending = scope.spawn(|| client.checkpoint(Digest32::ZERO, &initial));
        entered_rx.recv_timeout(Duration::from_secs(5))?;
        assert_eq!(
            client.checkpoint(Digest32::ZERO, &initial),
            Err(Error::Store(AuthorityTrustError::Unavailable))
        );
        release_tx.send(())?;
        assert_eq!(pending.join().unwrap()?, initial.head_digest);
        assert_eq!(client.restore(&initial.request)?, Some(initial.clone()));
        server.join().unwrap()?;
        Ok(())
    })
}

#[test]
fn missing_or_foreign_ack_closes_the_client_without_an_automatic_retry() -> anyhow::Result<()> {
    let initial = test_data::snapshots()?.remove(0);
    for foreign in [false, true] {
        let (left, right) = UnixStream::pair()?;
        let client = AgentdLearningCheckpointClientV1::from_admitted_channel(
            channel(left),
            test_data::OWNER.into(),
            initial.clone(),
        );
        std::thread::scope(|scope| {
            let server = scope.spawn(|| {
                let mut peer = channel(right);
                peer.exchange(|_| {
                    if !foreign {
                        return Err(HostIssuerTransportError::Unavailable);
                    }
                    encode_frame(&Response {
                        schema_version: 1,
                        operation: DOMAIN.into(),
                        sequence: 1,
                        owner_id: "foreign-owner".into(),
                        binding: initial.head_digest.to_string(),
                        outcome: Outcome::Committed {
                            head: initial.head_digest.to_string(),
                        },
                    })
                })
            });
            assert_eq!(
                client.checkpoint(Digest32::ZERO, &initial),
                Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
            );
            assert_eq!(
                client.checkpoint(Digest32::ZERO, &initial),
                Err(Error::CommitUncertain(AuthorityTrustError::Unavailable))
            );
            assert_eq!(
                client.restore(&initial.request),
                Err(Error::Store(AuthorityTrustError::Unavailable))
            );
            let result = server.join().unwrap();
            assert_eq!(result.is_ok(), foreign);
        });
    }
    Ok(())
}
