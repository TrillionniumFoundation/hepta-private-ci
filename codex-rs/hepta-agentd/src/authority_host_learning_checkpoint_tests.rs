//! Explicit Root/non-Root transport qualification using fresh test registration.
//! Learning payloads are synthetic; these tests prove no trained-model benefit.

use super::*;
use crate::LearningIterationCheckpointErrorV1 as CheckpointError;
use crate::learning_iteration_checkpoint::transport::test_data as data;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::process::Stdio;

#[path = "authority_host_learning_checkpoint_fixture_tests.rs"]
mod fixture;

#[path = "authority_host_learning_delivery_tests.rs"]
mod delivery;

const CHILD: &str =
    "authority_host_service::learning_checkpoint::tests::unprivileged_checkpoint_child";

fn pidfd(pid: u32) -> OwnedFd {
    // SAFETY: pidfd_open reads a live, retained process ID and no pointers.
    let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(raw >= 0);
    // SAFETY: successful pidfd_open returned one fresh owned descriptor.
    unsafe { OwnedFd::from_raw_fd(raw as i32) }
}

#[test]
#[ignore = "actual non-Root child, only launched by the explicit registered Root fixture"]
fn unprivileged_checkpoint_child() -> anyhow::Result<()> {
    // SAFETY: these calls only read the current kernel credentials.
    assert_eq!(
        unsafe {
            (
                libc::getuid(),
                libc::geteuid(),
                libc::getgid(),
                libc::getegid(),
            )
        },
        (60001, 60001, 60001, 60001)
    );
    assert_eq!(
        std::fs::read_dir(std::env::var_os("LCP_PRIVATE_STATE").unwrap())
            .unwrap_err()
            .kind(),
        io::ErrorKind::PermissionDenied
    );
    let identity: crate::HostAuthorityRegisteredIdentity =
        serde_json::from_str(&std::env::var("LCP_IDENTITY")?)?;
    let fds: Vec<i32> = serde_json::from_str(&std::env::var("LCP_HANDOFF_FDS")?)?;
    assert_eq!(fds.len(), 5);
    let states = data::snapshots()?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    for (phase, fd) in fds.into_iter().enumerate() {
        let mut signal = [0];
        std::io::stdin().read_exact(&mut signal)?;
        assert_eq!(signal, [1]);
        // SAFETY: the Root test launcher passed exactly these owned anonymous
        // sockets through exec. Each descriptor is consumed exactly once.
        let handoff = unsafe { UnixDatagram::from_raw_fd(fd) };
        let admitted = runtime.block_on(receive_learning_checkpoint_handoff_v1(
            handoff,
            identity.identity()?,
            Duration::from_secs(5),
        ));
        if phase == 4 {
            assert!(
                admitted.is_err(),
                "revoked writer must fail a fresh authenticated restore"
            );
            std::io::stdin().read_exact(&mut signal)?;
            assert_eq!(signal, [2]);
            continue;
        }
        let client = admitted?;
        if phase == 0 {
            assert_eq!(client.restore(&states[0].request)?, None);
            assert_eq!(
                client.checkpoint(Digest32::ZERO, &states[0])?,
                states[0].head_digest
            );
            assert_eq!(
                client.checkpoint(states[0].head_digest, &states[1])?,
                states[1].head_digest
            );
            let mut different = states[0].request.clone();
            different.operation_id = codex_hepta_types::StableId::new("foreign-operation")?;
            assert_eq!(client.restore(&different), Err(CheckpointError::WrongScope));
            assert_eq!(
                client.checkpoint(Digest32::ZERO, &states[0]),
                Err(CheckpointError::Conflict)
            );
        } else if phase == 1 {
            assert_eq!(client.restore(&states[0].request)?, Some(states[1].clone()));
            assert_eq!(
                client.checkpoint(states[1].head_digest, &states[2]),
                Err(CheckpointError::CommitUncertain(
                    AuthorityTrustError::Unavailable
                ))
            );
            assert_eq!(
                client.checkpoint(states[1].head_digest, &states[2]),
                Err(CheckpointError::CommitUncertain(
                    AuthorityTrustError::Unavailable
                ))
            );
            assert_eq!(
                client.restore(&states[0].request),
                Err(CheckpointError::Store(AuthorityTrustError::Unavailable))
            );
        } else if phase == 2 {
            assert_eq!(client.restore(&states[0].request)?, Some(states[2].clone()));
            assert_eq!(
                client.checkpoint(states[0].head_digest, &states[1]),
                Err(CheckpointError::Conflict)
            );
            assert_eq!(client.restore(&states[0].request)?, Some(states[2].clone()));
        } else {
            assert_eq!(
                client.checkpoint(states[2].head_digest, &states[3]),
                Err(CheckpointError::CommitUncertain(
                    AuthorityTrustError::Unavailable
                ))
            );
            assert_eq!(
                client.restore(&states[0].request),
                Err(CheckpointError::Store(AuthorityTrustError::Unavailable))
            );
        }
        drop(client);
        println!(
            "LCP phase={phase} ordinary_pid={} uid=60001 completed",
            std::process::id()
        );
        // Keep the original pidfd live until Root has reopened and checked the
        // actual durable state; a dead client must not stand in for lost ACK.
        std::io::stdin().read_exact(&mut signal)?;
        assert_eq!(signal, [2]);
    }
    Ok(())
}

#[test]
#[ignore = "requires explicit test-only bind, actual Root and setpriv non-Root child"]
fn registered_root_cross_process_restore_conflict_and_committed_lost_ack() -> anyhow::Result<()> {
    let fixture = fixture::Fixture::create()?;
    let states = data::snapshots()?;
    let mut senders = Vec::new();
    let mut receivers = Vec::new();
    for _ in 0..5 {
        let (sender, receiver) = UnixDatagram::pair()?;
        senders.push(sender);
        receivers.push(receiver);
    }
    let numbers: Vec<_> = receivers.iter().map(AsRawFd::as_raw_fd).collect();
    let mut command = Command::new("/usr/bin/setpriv");
    command
        .args([
            "--reuid=60001",
            "--regid=60001",
            "--clear-groups",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            "--bounding-set=-all",
        ])
        .arg(&fixture.binary)
        .args(["--exact", CHILD, "--ignored", "--nocapture"])
        .stdin(Stdio::piped())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .env("LCP_HANDOFF_FDS", serde_json::to_string(&numbers)?)
        .env("LCP_IDENTITY", serde_json::to_string(&fixture.identity)?)
        .env("LCP_PRIVATE_STATE", &fixture.private_path);
    // SAFETY: after fork this callback only changes CLOEXEC on the exact
    // retained test-owned descriptors, using async-signal-safe fcntl.
    unsafe {
        command.pre_exec(move || {
            for fd in &numbers {
                if libc::fcntl(*fd, libc::F_SETFD, 0) != 0 {
                    return Err(io::Error::last_os_error());
                }
            }
            Ok(())
        });
    }
    let mut child = command.spawn()?;
    drop(receivers);
    let consumer = pidfd(child.id());
    let root_pidfd = pidfd(std::process::id());
    let end = Instant::now() + Duration::from_secs(10);
    while crate::authority_host_runtime::verify_process_credentials(child.id(), 60001, 60001)
        .is_err()
    {
        anyhow::ensure!(
            Instant::now() < end && child.try_wait()?.is_none(),
            "child did not complete its original credential drop"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    let registration = HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: child.id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: process_start(child.id())?,
        registered_identity: fixture.identity.clone(),
        checkpoint_owner_agent_id: fixture.identity.agent_id.clone(),
        publisher_epoch: 1,
    };
    for (phase, sender) in senders.into_iter().enumerate() {
        let endpoint = fixture.lanes.join(format!("checkpoint-{phase}.sock"));
        let listener = UnixListener::bind(&endpoint)?;
        std::fs::set_permissions(&endpoint, std::fs::Permissions::from_mode(0o660))?;
        let profile = RootLearningCheckpointProfileV1 {
            consumer: registration.clone(),
            peer_uid: 60001,
            peer_gid: 60001,
            endpoint: endpoint.clone(),
            timeout_ms: 5000,
            lifetime_ms: 20000,
        };
        if phase == 0 {
            let wrong = UnixStream::connect(&endpoint)?;
            let (accepted, _) = listener.accept()?;
            let prepared = fixture.service.learning_checkpoint_profile(
                fixture.owner()?,
                profile.clone(),
                consumer.try_clone()?,
            )?;
            assert!(matches!(
                prepared.serve(accepted),
                Err(HostIssuerTransportError::PeerDenied)
            ));
            drop(wrong);
            assert_eq!(fixture.owner()?.restore(&states[0].request)?, None);
        }
        let mut prepared = fixture.service.learning_checkpoint_profile(
            fixture.owner()?,
            profile,
            consumer.try_clone()?,
        )?;
        let sealed = prepared.seal_handoff()?;
        crate::send_root_production_handoff(sender, &sealed, &root_pidfd, Duration::from_secs(5))?;
        child.stdin.as_mut().unwrap().write_all(&[1])?;
        listener.set_nonblocking(true)?;
        let end = Instant::now() + Duration::from_secs(10);
        let stream = loop {
            crate::authority_host_runtime::owner_alive(&consumer, end)?;
            match listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(5))
                }
                Err(error) => return Err(error.into()),
            }
        };
        if phase == 1 || phase == 3 {
            // Test-only control around the original authenticated writer path:
            // phase 1 loses ACK after commit; phase 3 revokes after admission.
            // The same ordinary process remains alive throughout both.
            let mut channel = HostAuthorityPeerChannel::from_stream(
                stream,
                HostAuthorityPeerPolicy {
                    peer: HostIssuerPeer {
                        uid: 60001,
                        pid: child.id(),
                    },
                    timeout: Duration::from_secs(5),
                    lifetime: Duration::from_secs(20),
                    request_bound: FRAME_LIMIT,
                    response_bound: FRAME_LIMIT,
                },
                consumer.try_clone()?,
            )?;
            if phase == 3 {
                assert!(channel.exchange(|bytes| {
                    prepared
                        .service
                        .writer
                        .as_ref()
                        .unwrap()
                        .exchange_learning_checkpoint(
                            &prepared.service.issuer,
                            &prepared.service.clock,
                            &mut prepared.backend,
                            bytes,
                        )
                })?);
                // A real original registry revocation after successful fresh
                // admission must fence the next otherwise-valid append.
                let writer = &prepared.service.writer.as_ref().unwrap().registration;
                prepared.service.root_registry.as_ref().unwrap().revoke(
                    &writer.authority_lease.lease_id,
                    writer.authority_lease.revision,
                    [9; 32],
                )?;
                let result = channel.exchange(|bytes| {
                    let value: serde_json::Value = serde_json::from_slice(bytes).unwrap();
                    assert_eq!(value["command"]["command"], "checkpoint");
                    prepared
                        .service
                        .writer
                        .as_ref()
                        .unwrap()
                        .exchange_learning_checkpoint(
                            &prepared.service.issuer,
                            &prepared.service.clock,
                            &mut prepared.backend,
                            bytes,
                        )
                });
                assert!(matches!(result, Err(HostIssuerTransportError::Unavailable)));
            } else {
                let mut committed = false;
                loop {
                    let result = channel.exchange(|bytes| {
                        let value: serde_json::Value = serde_json::from_slice(bytes).unwrap();
                        let response = prepared
                            .service
                            .writer
                            .as_ref()
                            .unwrap()
                            .exchange_learning_checkpoint(
                                &prepared.service.issuer,
                                &prepared.service.clock,
                                &mut prepared.backend,
                                bytes,
                            )?;
                        if value["command"]["command"] == "checkpoint" {
                            let ack: serde_json::Value = serde_json::from_slice(&response).unwrap();
                            assert_eq!(ack["outcome"]["status"], "committed");
                            committed = true;
                            return Err(HostIssuerTransportError::Unavailable);
                        }
                        Ok(response)
                    });
                    if !matches!(result, Ok(true)) {
                        break;
                    }
                }
                assert!(committed);
            }
            drop(channel);
            drop(prepared);
        } else if phase == 4 {
            assert!(matches!(
                prepared.serve(stream),
                Err(HostIssuerTransportError::Unavailable)
            ));
        } else {
            prepared.serve(stream)?;
        }
        // Close the previous concrete handle, then open only the same existing
        // registered Root owner. No test adapter or registration retry is used.
        let expected = if phase == 0 { &states[1] } else { &states[2] };
        assert_eq!(
            fixture.owner()?.restore(&states[0].request)?,
            Some(expected.clone())
        );
        crate::authority_host_runtime::owner_alive(
            &consumer,
            Instant::now() + Duration::from_secs(1),
        )?;
        child.stdin.as_mut().unwrap().write_all(&[2])?;
    }
    assert!(child.wait()?.success());
    println!(
        "LCP Root pid={} uid=0 original-consumer={} uid=60001 durable phases verified",
        std::process::id(),
        registration.peer_pid
    );
    Ok(())
}
