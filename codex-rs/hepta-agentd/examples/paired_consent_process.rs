//! Exercise the released consent command with a signed and acknowledged development
//! delivery, a real Root issuer channel, and an issuer with no physical user session.
//! Build this example on Linux and run it in the private root described in the qualification.
#[cfg(target_os = "linux")]
mod linux {
    use anyhow::{Context, Result, ensure};
    use codex_hepta_agentd::text_session::AgentdTextSessionConfig;
    use codex_hepta_agentd::{
        AgentdIdentity, AuthBusTextBody, AuthBusTextIngress, DeploymentFinalUseIssuer,
        DeploymentGrantPolicy, HostAuthorityLane, HostAuthorityService, PairedLearningDataUse,
        authbus_text_claims,
    };
    use codex_hepta_authbus::{IssuerRegistration, SignedMessage};
    use codex_hepta_contracts::{
        AgentId, HostAuthorityClock, HostAuthorityPeerPolicy, HostIssuerPeer,
        HostIssuerTransportError, RootAuthorityDirectory, SystemAuthorityClock,
    };
    use codex_hepta_evidence::{AuthBusClaimRequest, AuthBusDeliveryState, HeptaEvidenceStore};
    use codex_hepta_types::{Digest32, Generation, StableId};
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use ed25519_dalek::VerifyingKey;
    use serde_json::{Value, json};
    use std::io::{self, Write};
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::net::UnixStream;
    use std::os::unix::process::CommandExt;
    use std::path::Path;
    use std::process::{Command, Stdio};
    use std::sync::Arc;
    use std::time::{Duration, Instant};

    fn pidfd(pid: u32) -> io::Result<OwnedFd> {
        // SAFETY: successful pidfd_open returns an owned descriptor.
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
    }

    fn launcher(cli: &Path, root: &Path, pid: u32, stream: UnixStream) -> Result<Command> {
        // The trusted fixture launcher creates the pair and delegates one endpoint
        // to its child. Both socket peer credentials identify that original launcher.
        let identity = pidfd(pid)?;
        let mut command = Command::new(cli);
        command
            .arg(pid.to_string())
            .arg(root.join("sqlite"))
            .arg(root.join("route.json"));
        // SAFETY: Both source descriptors are live and distinct. Copy the sources
        // first so neither fixed destination can overwrite another source.
        unsafe {
            command.pre_exec(move || {
                let socket = libc::fcntl(stream.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 5);
                if socket < 0 {
                    return Err(io::Error::last_os_error());
                }
                let birth = libc::fcntl(identity.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 5);
                if birth < 0 || libc::dup2(socket, 3) < 0 || libc::dup2(birth, 4) < 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        Ok(command)
    }

    async fn retain(
        root: &Path,
        owner: &AgentdIdentity,
        signer: &DeploymentFinalUseIssuer,
        route: &AgentdTextSessionConfig,
        text: String,
        seq: u64,
    ) -> Result<(Digest32, AuthBusTextIngress)> {
        let sqlite = SqliteConfig::from_sqlite_home(AbsolutePathBuf::from_absolute_path(
            root.join("sqlite"),
        )?);
        let store = HeptaEvidenceStore::open(&sqlite).await?;
        let key = signer.trust_key()?;
        let ingress = signer.text(
            owner,
            &format!("development:{seq}"),
            AuthBusTextBody {
                spawn_generation: route.spawn_generation,
                thread_id: route.thread_id.clone(),
                text,
            },
            codex_hepta_agentd::TextIssuerOperation::Sign,
        )?;
        let issuer = IssuerRegistration {
            issuer_id: StableId::new(&ingress.issuer_id)?,
            key_epoch: Generation::new(ingress.key_epoch)?,
            verifying_key: VerifyingKey::from_bytes(&key.verifying_key)?,
            revoked: false,
        };
        let claims = authbus_text_claims(&route.agent_id, &ingress)?;
        let mut signature = [0_u8; 64];
        ensure!(ingress.signature_hex.len() == 2 * signature.len());
        for (i, byte) in signature.iter_mut().enumerate() {
            *byte = u8::from_str_radix(&ingress.signature_hex[2 * i..2 * i + 2], 16)?;
        }
        let message = SignedMessage { claims, signature };
        let payload = serde_json::to_vec(&ingress.body)?;
        let receipt = store
            .enqueue_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                &payload,
            )
            .await?;
        let worker = StableId::new("development-consumer")?;
        let claimed = store
            .claim_authbus_delivery(
                &issuer,
                AuthBusClaimRequest {
                    delivery_id: receipt.delivery_id,
                    subject_id: &message.claims.subject_id,
                    scope_digest: message.claims.scope_digest,
                    worker_id: &worker,
                    lease_ms: 30_000,
                },
            )
            .await?;
        let acknowledgement = Digest32::of_bytes(format!("development-ack-{seq}").as_bytes());
        store
            .ack_authbus_delivery(&issuer, &claimed.lease, acknowledgement)
            .await?;
        store.close().await;
        let reopened = HeptaEvidenceStore::open_existing_read_only(&sqlite).await?;
        let retained = reopened
            .retained_authbus_delivery(receipt.delivery_id)
            .await?;
        ensure!(
            retained.status.state == AuthBusDeliveryState::Acked
                && retained.status.acknowledgement == Some(acknowledgement)
                && retained.message.signature == signature
        );
        reopened.close().await;
        Ok((receipt.delivery_id, ingress))
    }

    fn peek_exact(stream: &UnixStream, expected: &Value) -> Result<Digest32> {
        let until = Instant::now() + Duration::from_secs(3);
        let read = |buf: &mut [u8]| -> Result<()> {
            loop {
                // SAFETY: recv writes within the supplied buffer. PEEK preserves the original frame.
                let size = unsafe {
                    libc::recv(
                        stream.as_raw_fd(),
                        buf.as_mut_ptr().cast(),
                        buf.len(),
                        libc::MSG_PEEK | libc::MSG_DONTWAIT,
                    )
                };
                if size == buf.len() as isize {
                    return Ok(());
                }
                if size < 0 && io::Error::last_os_error().kind() != io::ErrorKind::WouldBlock {
                    return Err(io::Error::last_os_error().into());
                }
                ensure!(
                    size != 0 && Instant::now() < until,
                    "incomplete original issuer request"
                );
                std::thread::sleep(Duration::from_millis(2));
            }
        };
        let mut prefix = [0; 4];
        read(&mut prefix)?;
        let len = u32::from_be_bytes(prefix) as usize;
        ensure!((1..=32 * 1024).contains(&len));
        let mut bytes = vec![0; len + 4];
        read(&mut bytes)?;
        ensure!(
            serde_json::from_slice::<Value>(&bytes[4..])? == *expected,
            "original signed human request differs"
        );
        Ok(Digest32::of_bytes(&bytes[4..]))
    }

    pub fn main() -> Result<()> {
        let args = std::env::args().collect::<Vec<_>>();
        let [_, cli, root] = args.as_slice() else {
            anyhow::bail!("supply the released CLI and an unused absolute directory")
        };
        let root = Path::new(root);
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(root)
            .context("create private data root")?;
        let id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let fleet = codex_hepta_paths::HeptaFleetRoot::parse(root.join("fleet"))?;
        let layout = fleet.layout().agent(&id);
        let owner = AgentdIdentity {
            agent_id: id,
            spawn_generation: 1,
            fleet_root: fleet.as_path().into(),
            workspace: root.into(),
            resources: codex_hepta_fleet::ResourceBudget::local_default(),
            home_root: layout.home_root().into(),
            run_root: layout.run_root().into(),
            control_socket: layout.agentd_control_socket().into(),
            app_server_socket: layout.app_server_socket().into(),
            layout,
        };
        let route = AgentdTextSessionConfig {
            agent_id: owner.agent_id.clone(),
            spawn_generation: 1,
            control_socket: owner.control_socket.clone(),
            codex_home: owner.home_root.clone(),
            thread_id: "development-thread".into(),
            app_server_session_id: "development-app".into(),
        };
        std::fs::write(root.join("route.json"), serde_json::to_vec(&route)?)?;
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(root.join("sqlite"))?;
        let state = root.join("clock");
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&state)
            .context("create clock dir")?;
        let clock = HostAuthorityClock::initialize(
            RootAuthorityDirectory::open(&state).context("open Root authority dir")?,
            "development-clock".into(),
        )
        .context("initialize clock")?;
        let policy = DeploymentGrantPolicy {
            subject_id: owner.agent_id.to_string(),
            destination_id: DeploymentFinalUseIssuer::text_destination(&route.thread_id)?,
            scope_sha256: DeploymentFinalUseIssuer::text_scope(&owner.agent_id),
            lifetime_ms: 30000,
        };
        let issuer = DeploymentFinalUseIssuer::create(
            &root.join("issuer"),
            "development-issuer".into(),
            vec![policy],
            Arc::new(SystemAuthorityClock),
        )
        .context("initialize development issuer")?;
        let issuer = Arc::new(issuer);
        let service = HostAuthorityService::from_registered_owner(
            issuer.clone(),
            Arc::new(clock),
            owner.clone(),
        )?;
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .context("create tokio runtime")?;
        let study = Digest32::of_bytes(b"development study");
        let a = Digest32::of_bytes(b"development first record");
        let b = Digest32::of_bytes(b"development second record");
        let pair = Digest32::of_bytes(b"development pair");
        let operation = Digest32::of_bytes(b"development operation");
        let run = Digest32::of_bytes(b"development run");
        let output = Digest32::of_bytes(b"development output");
        let effect = Digest32::of_bytes(b"development effect");
        let consumer_report = |seq, accepted| {
            (
                seq,
                PairedLearningDataUse::ReportConsumerOutcome {
                    operation,
                    pair,
                    candidate: a,
                    task: b,
                    run_receipt: run,
                    output,
                    effect,
                    accepted,
                },
                json!({"use":"report_consumer_outcome", "operation":operation.to_string(),
                       "pair":pair.to_string(),"candidate":a.to_string(),"task":b.to_string(),
                       "run_receipt":run.to_string(),"output":output.to_string(),"effect":effect.to_string(),
                       "outcome":if accepted {"accepted"} else {"rejected"}}),
            )
        };
        for (seq, scope, scope_json) in [
            (
                1,
                PairedLearningDataUse::TrainOnFailureAndCorrection {
                    failure: a,
                    correction: b,
                },
                json!({"use":"train","failure":a.to_string(),"correction":b.to_string()}),
            ),
            (
                2,
                PairedLearningDataUse::EvaluateOnlyAfterFreeze { freeze: a, task: b },
                json!({"use":"evaluate_only","freeze":a.to_string(),"task":b.to_string()}),
            ),
            (
                3,
                PairedLearningDataUse::RequestConsumerRun {
                    operation,
                    pair,
                    candidate: a,
                    task: b,
                },
                json!({"use":"request_consumer_run","operation":operation.to_string(),
                       "pair":pair.to_string(),"candidate":a.to_string(),"task":b.to_string()}),
            ),
            consumer_report(4, true),
            consumer_report(5, false),
        ] {
            let (delivery, ingress) = rt
                .block_on(retain(
                    root,
                    &owner,
                    &issuer,
                    &route,
                    scope.consent_text(study),
                    seq,
                ))
                .context("sign admit ack and reopen original row")?;
            let root_pid = std::process::id();
            let (stream, child_endpoint) = UnixStream::pair()?;
            let mut child = launcher(Path::new(cli), root, root_pid, child_endpoint)?
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .context("spawn child after initial private authorization")?;
            child.stdin.take().unwrap().write_all(&serde_json::to_vec(&json!({"study_sha256":study.to_string(),"delivery_id":delivery.to_string(),"scope":scope_json}))?)?;
            let expected = json!({"schema_version":1,"operation":"runtime.authbus.human_text.verify.v1","ingress":ingress});
            let received = peek_exact(&stream, &expected)?;
            let peer = HostAuthorityPeerPolicy {
                peer: HostIssuerPeer {
                    uid: 0,
                    pid: root_pid,
                },
                timeout: Duration::from_secs(3),
                lifetime: Duration::from_secs(8),
                request_bound: 65536,
                response_bound: 65536,
            };
            let held = pidfd(root_pid).context("open socket-owner pidfd")?;
            let refusal = service.serve(HostAuthorityLane::Issuer, stream, peer, held);
            ensure!(
                matches!(refusal, Err(HostIssuerTransportError::Unavailable)),
                "unexpected Root result: {refusal:?}"
            );
            let observed = child.wait_with_output().context("wait for command")?;
            ensure!(
                observed.status.code() == Some(1) && observed.stdout.is_empty(),
                "unexpected consent return"
            );
            println!(
                "{}",
                json!({"scope":scope_json["use"],"decision":scope_json.get("outcome"),"delivery":delivery.to_string(),"study":study.to_string(),"issuer_request_sha256":received.to_string(),"acked_after_reopen":true,"exact_request_observed":true,"production_root_result":"Unavailable","stdout_bytes":observed.stdout.len(),"exit":observed.status.code(),"authenticated_humans":0})
            );
        }
        Ok(())
    }
}
#[cfg(target_os = "linux")]
fn main() -> anyhow::Result<()> {
    linux::main()
}
#[cfg(not(target_os = "linux"))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("requires Linux socket credentials and pidfds")
}
