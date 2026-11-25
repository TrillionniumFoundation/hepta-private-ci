//! No-effect qualification client for the actual root authority service.
//! Public fixture inputs are supplied by the privileged qualification launcher;
//! they are not a production loader, current-cut witness or native role grant.

#[cfg(target_os = "linux")]
#[path = "authority_host_peer_qualification/checkpoint.rs"]
mod checkpoint;

#[cfg(target_os = "linux")]
#[path = "authority_host_peer_qualification/consumers.rs"]
mod consumers;

#[cfg(target_os = "linux")]
mod qualification {
    use codex_hepta_authority_client::AgentdFinalUseIssuerError;
    use codex_hepta_authority_client::AgentdFinalUseIssuerPeer;
    use codex_hepta_authority_client::AgentdUnixFinalUseGrantProvider;
    use codex_hepta_authority_client::authbus_objective_claims;
    use codex_hepta_authority_types::AgentdIdentity;
    use codex_hepta_authority_types::AuthBusObjectiveBody;
    use codex_hepta_authority_types::AuthBusObjectiveIngress;
    use codex_hepta_authority_types::HostAuthorityObservationResponseV2;
    use codex_hepta_authority_types::HostWriterAuthorizationReadResponseV1;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::FinalUseBinding;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::HostAuthorityClockProjection;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_paths::HeptaFleetRoot;
    use ed25519_dalek::Verifier;
    use serde::Deserialize;
    use std::io::Read;
    use std::io::Write;
    use std::os::fd::AsRawFd;
    use std::os::unix::net::UnixStream;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::Duration;
    use std::time::Instant;

    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct PublicFixtureIdentity {
        agent_id: AgentId,
        spawn_generation: u64,
        fleet_root: PathBuf,
        workspace: PathBuf,
        resources: ResourceBudget,
    }

    #[derive(Deserialize)]
    struct ObservationResponse {
        schema_version: u32,
        operation: String,
        authority_epoch: u64,
        revocations: FinalUseRevocations,
        clock: HostAuthorityClockProjection,
        observed_unix_ms: u64,
        registered_agent_id: String,
        spawn_generation: u64,
    }

    #[derive(Deserialize)]
    struct ObjectiveResponse {
        schema_version: u32,
        operation: String,
        ingress: AuthBusObjectiveIngress,
    }

    fn connect(path: &Path, root_pid: u32) -> UnixStream {
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            match UnixStream::connect(path) {
                Ok(stream) => {
                    let mut peer = libc::ucred {
                        pid: 0,
                        uid: 1,
                        gid: 1,
                    };
                    let mut length = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
                    // SAFETY: valid writable ucred and socklen objects have the
                    // exact size supplied to getsockopt for this live stream.
                    let result = unsafe {
                        libc::getsockopt(
                            stream.as_raw_fd(),
                            libc::SOL_SOCKET,
                            libc::SO_PEERCRED,
                            (&mut peer as *mut libc::ucred).cast(),
                            &mut length,
                        )
                    };
                    assert_eq!(result, 0);
                    assert_eq!(length as usize, std::mem::size_of::<libc::ucred>());
                    assert_eq!((peer.uid, peer.pid), (0, root_pid as i32));
                    stream
                        .set_read_timeout(Some(Duration::from_secs(10)))
                        .unwrap();
                    stream
                        .set_write_timeout(Some(Duration::from_secs(10)))
                        .unwrap();
                    return stream;
                }
                Err(_) => {
                    assert!(Instant::now() < deadline, "root listener deadline");
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
        }
    }

    pub(super) fn exchange<T: serde::de::DeserializeOwned>(
        stream: &mut UnixStream,
        request: &serde_json::Value,
        bound: usize,
    ) -> serde_json::Result<T> {
        let bytes = serde_json::to_vec(request).unwrap();
        stream
            .write_all(&(bytes.len() as u32).to_be_bytes())
            .unwrap();
        stream.write_all(&bytes).unwrap();
        let mut length = [0; 4];
        stream.read_exact(&mut length).unwrap();
        let length = u32::from_be_bytes(length) as usize;
        assert!((1..=bound).contains(&length));
        let mut bytes = vec![0; length];
        stream.read_exact(&mut bytes).unwrap();
        serde_json::from_slice(&bytes)
    }

    fn objective_body(spawn_generation: u64) -> AuthBusObjectiveBody {
        AuthBusObjectiveBody {
            spawn_generation,
            run_id: "root-service-qualification".into(),
            objective_revision: 1,
            source_envelope_json: "{}".into(),
            runtime_body_digest: "11".repeat(32),
            preference_state_digest: "22".repeat(32),
            model_tuple_digest: "33".repeat(32),
            prompt_registry_digest: "44".repeat(32),
            artifact_set_digest: "55".repeat(32),
            authority_epoch: 1,
        }
    }

    pub(super) fn run() -> Result<(), Box<dyn std::error::Error>> {
        // SAFETY: geteuid takes no memory pointers or borrowed data.
        assert_eq!(unsafe { libc::geteuid() }, 60001);
        let status = std::fs::read_to_string("/proc/self/status")?;
        assert!(status.lines().any(|line| line == "NoNewPrivs:\t1"));
        assert!(status.lines().any(|line| {
            line.strip_prefix("Groups:")
                .is_some_and(|groups| groups.trim().is_empty())
        }));
        for field in ["CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"] {
            assert!(status.lines().any(|line| {
                line.strip_prefix(field)
                    .is_some_and(|value| value == ":\t0000000000000000")
            }));
        }
        let state = std::env::var_os("HEPTA_SERVICE_STATE").ok_or("missing fixture state path")?;
        assert_eq!(
            std::fs::read_dir(state).unwrap_err().kind(),
            std::io::ErrorKind::PermissionDenied
        );
        let mut trusted_bootstrap = None;
        if std::env::var_os("HEPTA_SERVICE_START_STDIN").is_some() {
            let mut start = [0];
            std::io::stdin().read_exact(&mut start)?;
            assert_eq!(start, [1]);
            if std::env::var_os("HEPTA_SERVICE_CONSUMERS").is_some() {
                trusted_bootstrap = Some(super::consumers::read_bootstrap()?);
            }
        }
        let runtime = PathBuf::from(
            std::env::var_os("HEPTA_SERVICE_RUNTIME").ok_or("missing fixture runtime")?,
        );
        let root_pid: u32 = std::env::var("HEPTA_SERVICE_PID")?.parse()?;
        let mut observation = connect(&runtime.join("observation.sock"), root_pid);
        let mut issuer = connect(&runtime.join("issuer.sock"), root_pid);
        let mut checkpoint = connect(&runtime.join("checkpoint.sock"), root_pid);
        let mut consumer_streams = if std::env::var_os("HEPTA_SERVICE_CONSUMERS").is_some() {
            Some((
                connect(&runtime.join("device-frontier.sock"), root_pid),
                connect(&runtime.join("notes-frontier.sock"), root_pid),
            ))
        } else {
            None
        };
        let writer_proof = std::env::var_os("HEPTA_SERVICE_WRITER_PROOF").is_some();
        if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CONSUMER").is_some() {
            std::thread::sleep(Duration::from_secs(3));
            let device = &mut consumer_streams.as_mut().ok_or("missing consumer lanes")?.0;
            let request = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"operation":"runtime.final_use.frontier.load.v1","request_id":1}),
            )?;
            device.write_all(&(request.len() as u32).to_be_bytes())?;
            device.write_all(&request)?;
            let mut first = [0];
            assert_eq!(
                device.read(&mut first)?,
                0,
                "expired writer must not read consumer authority"
            );
            println!(
                "{}",
                serde_json::json!({"qualification":"root_consumer_expired_writer","uid":60001,"consumer_refused":true,"production_ready":false})
            );
            return Ok(());
        }

        if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_CHECKPOINT").is_some() {
            std::thread::sleep(Duration::from_secs(3));
            let request = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":"00000000000000010000000000000001","command":"read_head","expected":null,"proposal":null}),
            )?;
            checkpoint.write_all(&(request.len() as u32).to_be_bytes())?;
            checkpoint.write_all(&request)?;
            let mut first = [0];
            assert_eq!(
                checkpoint.read(&mut first)?,
                0,
                "expired writer must not read checkpoint authority"
            );
            println!(
                "{}",
                serde_json::json!({"qualification":"root_checkpoint_expired_writer","uid":60001,"checkpoint_refused":true,"production_ready":false})
            );
            return Ok(());
        }

        if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_OBJECTIVE").is_some() {
            std::thread::sleep(Duration::from_secs(3));
            let identity: PublicFixtureIdentity =
                serde_json::from_slice(std::env::var("HEPTA_SERVICE_IDENTITY")?.as_bytes())?;
            let request = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":objective_body(identity.spawn_generation)}),
            )?;
            issuer.write_all(&(request.len() as u32).to_be_bytes())?;
            issuer.write_all(&request)?;
            let mut first = [0];
            assert_eq!(
                issuer.read(&mut first)?,
                0,
                "expired writer must not emit an Objective prefix"
            );
            println!(
                "{}",
                serde_json::json!({"qualification":"root_authority_expired_objective_v1","uid":60001,"objective_refused":true,"production_ready":false})
            );
            return Ok(());
        }
        if std::env::var_os("HEPTA_SERVICE_EXPECT_EXPIRED_FEED").is_some() {
            std::thread::sleep(Duration::from_secs(3));
            let request = serde_json::to_vec(&if writer_proof {
                serde_json::json!({"schema_version":2,"operation":"runtime.authority.observation.v2"})
            } else {
                serde_json::json!({"schema_version":1,"operation":"runtime.authority.observation.v1"})
            })?;
            observation.write_all(&(request.len() as u32).to_be_bytes())?;
            observation.write_all(&request)?;
            let mut first = [0];
            assert_eq!(
                observation.read(&mut first)?,
                0,
                "expired lease must not emit a feed prefix"
            );
            let identity: PublicFixtureIdentity =
                serde_json::from_slice(std::env::var("HEPTA_SERVICE_IDENTITY")?.as_bytes())?;
            let provider = AgentdUnixFinalUseGrantProvider::from_stream(
                issuer,
                AgentdFinalUseIssuerPeer {
                    uid: 0,
                    pid: root_pid,
                },
                Duration::from_secs(10),
            )?;
            let binding = FinalUseBinding {
                subject_id: identity.agent_id.to_string(),
                destination_id: "qualification.no-effect".into(),
                scope_sha256: [2; 32],
                request_sha256: [1; 32],
                payload_sha256: [3; 32],
            };
            assert!(matches!(
                provider.request_grant(&binding),
                Err(AgentdFinalUseIssuerError::Denied)
            ));
            println!(
                "{}",
                serde_json::json!({"qualification":if writer_proof {"root_authority_expired_lease_v2"} else {"root_authority_expired_lease_v1"},"uid":60001,"feed_refused":true,"final_use_denied":true,"production_ready":false})
            );
            return Ok(());
        }
        let mut writer_expiry = None;
        if writer_proof {
            let read: HostWriterAuthorizationReadResponseV1 = exchange(
                &mut observation,
                &serde_json::json!({"schema_version":1,"operation":"runtime.authority.writer_authorization.v1"}),
                16 * 1024,
            )?;
            let public: [u8; 32] =
                serde_json::from_slice(std::env::var("HEPTA_SERVICE_PUBLIC_KEY")?.as_bytes())?;
            let key = ed25519_dalek::VerifyingKey::from_bytes(&public)?;
            let signature = read
                .proof
                .signature_hex
                .as_bytes()
                .chunks_exact(2)
                .map(|chunk| u8::from_str_radix(std::str::from_utf8(chunk).unwrap(), 16).unwrap())
                .collect::<Vec<_>>();
            key.verify(
                &read.proof.claims.signing_bytes()?,
                &ed25519_dalek::Signature::from_slice(&signature)?,
            )?;
            assert_eq!(read.proof.claims.sequence, 1);
            writer_expiry = Some(read.proof.claims.authority_lease.expires_at_unix_ms);
            let before = Instant::now();
            let feed: HostAuthorityObservationResponseV2 = exchange(
                &mut observation,
                &serde_json::json!({"schema_version":2,"operation":"runtime.authority.observation.v2"}),
                16 * 1024,
            )?;
            let fresh_ms = before.elapsed().as_millis();
            assert!(before.elapsed() <= Duration::from_millis(500));
            assert_eq!(
                feed.writer.writer_authorization_sha256,
                read.proof.sha256()?
            );
            assert_eq!(
                feed.writer.authority_lease,
                read.proof.claims.authority_lease
            );
            assert_eq!(
                feed.writer.authority_lease_sha256,
                read.proof.claims.authority_lease_sha256
            );
            assert_eq!(feed.writer.owner_epoch, read.proof.claims.owner_epoch);
            assert_eq!(feed.writer.local_lease_id, read.proof.claims.local_lease_id);
            assert_eq!(
                feed.writer.local_lease_generation,
                read.proof.claims.local_lease_generation
            );
            assert!(feed.writer.store_revision > 1);
            let again: HostWriterAuthorizationReadResponseV1 = exchange(
                &mut observation,
                &serde_json::json!({"schema_version":1,"operation":"runtime.authority.writer_authorization.v1"}),
                16 * 1024,
            )?;
            assert_eq!(again, read);
            println!(
                "{}",
                serde_json::json!({"qualification":"root_authority_writer_observation_v2","uid":60001,"read_before_feed_ms":fresh_ms,"retained_proof_sequence":1,"production_ready":false})
            );
        }
        let start = Instant::now();
        let observation_data: ObservationResponse = exchange(
            &mut observation,
            &serde_json::json!({"schema_version":1,"operation":"runtime.authority.observation.v1"}),
            16 * 1024,
        )?;
        let feed_ms = start.elapsed().as_millis();
        assert!(
            start.elapsed() <= Duration::from_millis(500),
            "feed freshness from before read"
        );
        let identity: PublicFixtureIdentity =
            serde_json::from_slice(std::env::var("HEPTA_SERVICE_IDENTITY")?.as_bytes())?;
        assert_eq!(observation_data.schema_version, 1);
        assert_eq!(
            observation_data.operation,
            "runtime.authority.observation.v1"
        );
        assert_eq!(observation_data.authority_epoch, 1);
        assert_eq!(
            observation_data.revocations.authority_epoch,
            observation_data.authority_epoch
        );
        assert_eq!(
            observation_data.registered_agent_id,
            identity.agent_id.as_str()
        );
        assert_eq!(observation_data.spawn_generation, identity.spawn_generation);
        assert_eq!(
            observation_data.clock.boot_id,
            std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
        );
        assert!(observation_data.observed_unix_ms <= observation_data.clock.ceiling_unix_ms);
        let layout = HeptaFleetRoot::parse(identity.fleet_root.clone())?
            .layout()
            .agent(&identity.agent_id);
        let identity = AgentdIdentity {
            agent_id: identity.agent_id,
            spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root,
            workspace: identity.workspace,
            resources: identity.resources,
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
        };
        let public: [u8; 32] =
            serde_json::from_slice(std::env::var("HEPTA_SERVICE_PUBLIC_KEY")?.as_bytes())?;
        let key = ed25519_dalek::VerifyingKey::from_bytes(&public)?;
        let mut unregistered_objective = issuer.try_clone()?;
        let objective_sequence = if writer_proof {
            let signed: ObjectiveResponse = exchange(
                &mut issuer,
                &serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":objective_body(identity.spawn_generation)}),
                64 * 1024,
            )?;
            assert_eq!(signed.schema_version, 1);
            assert_eq!(signed.operation, "runtime.authbus.objective.signed.v1");
            let ingress = signed.ingress;
            assert_eq!(ingress.sequence, 2);
            assert_eq!(
                ingress.expires_at_ms,
                writer_expiry.ok_or("missing writer expiry")?
            );
            let signature: Vec<u8> = ingress
                .signature_hex
                .as_bytes()
                .chunks_exact(2)
                .map(|chunk| u8::from_str_radix(std::str::from_utf8(chunk).unwrap(), 16).unwrap())
                .collect();
            key.verify(
                &authbus_objective_claims(&identity, &ingress)?.signing_bytes(),
                &ed25519_dalek::Signature::from_slice(&signature)?,
            )?;
            Some(ingress.sequence)
        } else {
            None
        };
        let provider = AgentdUnixFinalUseGrantProvider::from_stream(
            issuer,
            AgentdFinalUseIssuerPeer {
                uid: 0,
                pid: root_pid,
            },
            Duration::from_secs(10),
        )?;
        let binding = FinalUseBinding {
            subject_id: identity.agent_id.to_string(),
            destination_id: "qualification.no-effect".into(),
            scope_sha256: [2; 32],
            request_sha256: [1; 32],
            payload_sha256: [3; 32],
        };
        assert!(matches!(
            provider.request_grant(&FinalUseBinding {
                scope_sha256: [9; 32],
                ..binding.clone()
            }),
            Err(AgentdFinalUseIssuerError::Denied)
        ));
        let grant = provider.request_grant(&binding)?;
        assert!(
            grant
                .grant
                .grant_id
                .ends_with(if writer_proof { ":3" } else { ":1" })
        );
        key.verify(
            &grant.grant.signing_bytes()?,
            &ed25519_dalek::Signature::from_slice(&grant.signature)?,
        )?;
        if !writer_proof {
            let request = serde_json::to_vec(
                &serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":objective_body(identity.spawn_generation)}),
            )?;
            unregistered_objective.write_all(&(request.len() as u32).to_be_bytes())?;
            unregistered_objective.write_all(&request)?;
            let mut first = [0];
            assert_eq!(
                unregistered_objective.read(&mut first)?,
                0,
                "writer registration is required for Objective signing"
            );
        }
        let checkpoint_ack = if std::env::var_os("HEPTA_SERVICE_CHECKPOINT").is_some() {
            super::checkpoint::qualify(&mut checkpoint)?;
            true
        } else {
            false
        };
        let bytes = serde_json::to_vec(
            &serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":"00000000000000010000000000000001","command":"read_head","expected":null,"proposal":null}),
        )?;
        let bytes = if std::env::var_os("HEPTA_SERVICE_CHECKPOINT").is_some() {
            // The closed original DTO must reject a peer-selected owner.
            br#"{"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","owner":"peer-selected"}"#.to_vec()
        } else {
            bytes
        };
        checkpoint.write_all(&(bytes.len() as u32).to_be_bytes())?;
        checkpoint.write_all(&bytes)?;
        let mut response = Vec::new();
        checkpoint.read_to_end(&mut response)?;
        assert!(
            response.is_empty(),
            "absent checkpoint or malformed owner selector must not emit an ACK"
        );
        let consumer_frontier_ack = if let Some((device, notes)) = consumer_streams {
            let second = provider.request_grant(&binding)?;
            assert!(second.grant.grant_id.ends_with(":4"));
            super::consumers::qualify(
                observation,
                device,
                notes,
                trusted_bootstrap
                    .take()
                    .ok_or("missing trusted root registration")?,
                [grant.clone(), second],
                &binding,
            )?;
            true
        } else {
            false
        };
        println!(
            "{}",
            serde_json::json!({"qualification":"root_authority_original_peer_v1","uid":60001,"no_new_privileges":true,"capabilities_clear":true,"feed_elapsed_ms":feed_ms,"objective_sequence":objective_sequence,"objective_denied_without_writer":!writer_proof,"final_use_sequence":grant.grant.grant_id.rsplit(':').next().ok_or("missing sequence")?.parse::<u64>()?,"checkpoint_ack":checkpoint_ack,"consumer_frontier_ack":consumer_frontier_ack,"production_ready":false})
        );
        Ok(())
    }
}

#[cfg(target_os = "linux")]
pub fn run() -> Result<(), Box<dyn std::error::Error>> {
    qualification::run()
}

#[cfg(not(target_os = "linux"))]
pub fn run() {
    eprintln!("authority_host_peer_qualification requires Linux");
    std::process::exit(1);
}
