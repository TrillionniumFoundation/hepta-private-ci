//! Exercise the current fail-closed command with retained development messages
//! and real inherited descriptors. No Root request or authorization may be emitted.
//! Historical process archives retain their original binary identity and results.
#[cfg(target_os = "linux")]
mod linux {
    use anyhow::Context;
    use anyhow::Result;
    use anyhow::ensure;
    use codex_hepta_agentd::AgentdIdentity;
    use codex_hepta_agentd::AuthBusTextBody;
    use codex_hepta_agentd::AuthBusTextIngress;
    use codex_hepta_agentd::DeploymentFinalUseIssuer;
    use codex_hepta_agentd::DeploymentGrantPolicy;
    use codex_hepta_agentd::PairedLearningDataUse;
    use codex_hepta_agentd::authbus_text_claims;
    use codex_hepta_agentd::text_session::AgentdTextSessionConfig;
    use codex_hepta_authbus::IssuerRegistration;
    use codex_hepta_authbus::SignedMessage;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::SystemAuthorityClock;
    use codex_hepta_evidence::AuthBusClaimRequest;
    use codex_hepta_evidence::AuthBusDeliveryState;
    use codex_hepta_evidence::HeptaEvidenceStore;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;
    use codex_state::SqliteConfig;
    use codex_utils_absolute_path::AbsolutePathBuf;
    use ed25519_dalek::VerifyingKey;
    use serde_json::json;
    use std::io;
    use std::io::Read;
    use std::os::fd::AsRawFd;
    use std::os::fd::FromRawFd;
    use std::os::fd::OwnedFd;
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::net::UnixStream;
    use std::os::unix::process::CommandExt;
    use std::path::Path;
    use std::process::Command;
    use std::process::Stdio;
    use std::sync::Arc;
    use std::time::Duration;
    use std::time::Instant;

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
            let (delivery, _ingress) = rt
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
            let (mut stream, child_endpoint) = UnixStream::pair()?;
            let request_file = root.join(format!("request-{seq}.json"));
            std::fs::write(
                &request_file,
                serde_json::to_vec(&json!({
                    "study_sha256":study.to_string(), "delivery_id":delivery.to_string(), "scope":scope_json
                }))?,
            )?;
            let mut command = launcher(Path::new(cli), root, root_pid, child_endpoint)?;
            let mut child = command
                .stdin(std::fs::File::open(&request_file)?)
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .context("spawn refusal regression with actual inherited descriptors")?;
            drop(command);
            let deadline = Instant::now() + Duration::from_secs(5);
            while child.try_wait()?.is_none() {
                if Instant::now() >= deadline {
                    child.kill()?;
                    child.wait()?;
                    anyhow::bail!("legacy consent did not refuse within the process bound");
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            let observed = child.wait_with_output().context("wait for command")?;
            ensure!(
                observed.status.code() == Some(1)
                    && observed.stdout.is_empty()
                    && String::from_utf8_lossy(&observed.stderr)
                        .contains("ORIGINAL_TURN_VERIFIER_REQUIRED"),
                "unexpected consent refusal"
            );
            stream.set_nonblocking(true)?;
            ensure!(
                stream.read(&mut [0; 1])? == 0,
                "legacy verification contacted the issuer"
            );
            println!(
                "{}",
                json!({"schema":"hepta.paired-consent.refusal-process.v2",
                    "scope":scope_json["use"],"decision":scope_json.get("outcome"),
                    "delivery":delivery.to_string(),"study":study.to_string(),
                    "fixture_acked_after_reopen":true,"issuer_request_bytes":0,
                    "result":"ORIGINAL_TURN_VERIFIER_REQUIRED", "authorization_issued":false,
                    "original_turn_verifier_executed":false,"stdout_bytes":observed.stdout.len(),
                    "exit":observed.status.code(),"authenticated_humans":0})
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
