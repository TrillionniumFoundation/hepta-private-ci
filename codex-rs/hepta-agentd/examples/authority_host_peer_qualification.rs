//! No-effect qualification client for the actual root authority service.
//! Public fixture inputs are supplied by the privileged qualification launcher;
//! they are not a production loader, current-cut witness or native role grant.

#[cfg(target_os = "linux")]
mod qualification {
    use codex_hepta_agentd::AgentdFinalUseIssuerError;
    use codex_hepta_agentd::AgentdFinalUseIssuerPeer;
    use codex_hepta_agentd::AgentdIdentity;
    use codex_hepta_agentd::AgentdUnixFinalUseGrantProvider;
    use codex_hepta_agentd::AuthBusObjectiveBody;
    use codex_hepta_agentd::AuthBusObjectiveIngress;
    use codex_hepta_agentd::authbus_objective_claims;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_contracts::FinalUseBinding;
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

    fn exchange(
        stream: &mut UnixStream,
        request: &serde_json::Value,
        bound: usize,
    ) -> serde_json::Value {
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
        serde_json::from_slice(&bytes).unwrap()
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
        let runtime = PathBuf::from(
            std::env::var_os("HEPTA_SERVICE_RUNTIME").ok_or("missing fixture runtime")?,
        );
        let root_pid: u32 = std::env::var("HEPTA_SERVICE_PID")?.parse()?;
        let mut observation = connect(&runtime.join("observation.sock"), root_pid);
        let mut issuer = connect(&runtime.join("issuer.sock"), root_pid);
        let mut checkpoint = connect(&runtime.join("checkpoint.sock"), root_pid);
        let start = Instant::now();
        let observation = exchange(
            &mut observation,
            &serde_json::json!({"schema_version":1,"operation":"runtime.authority.observation.v1"}),
            16 * 1024,
        );
        let feed_ms = start.elapsed().as_millis();
        assert!(
            start.elapsed() <= Duration::from_millis(500),
            "feed freshness from before read"
        );
        let identity: PublicFixtureIdentity =
            serde_json::from_str(&std::env::var("HEPTA_SERVICE_IDENTITY")?)?;
        assert_eq!(observation["schema_version"], 1);
        assert_eq!(observation["authority_epoch"], 1);
        assert_eq!(
            observation["registered_agent_id"],
            identity.agent_id.as_str()
        );
        assert_eq!(observation["spawn_generation"], identity.spawn_generation);
        assert_eq!(
            observation["clock"]["boot_id"],
            std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim()
        );
        assert!(
            observation["observed_unix_ms"]
                .as_u64()
                .ok_or("missing observation")?
                <= observation["clock"]["ceiling_unix_ms"]
                    .as_u64()
                    .ok_or("missing ceiling")?
        );
        let body = AuthBusObjectiveBody {
            spawn_generation: identity.spawn_generation,
            run_id: "root-service-qualification".into(),
            objective_revision: 1,
            source_envelope_json: "{}".into(),
            runtime_body_digest: "11".repeat(32),
            preference_state_digest: "22".repeat(32),
            model_tuple_digest: "33".repeat(32),
            prompt_registry_digest: "44".repeat(32),
            artifact_set_digest: "55".repeat(32),
            authority_epoch: 1,
        };
        let signed = exchange(
            &mut issuer,
            &serde_json::json!({"schema_version":1,"operation":"runtime.authbus.objective.sign.v1","body":body}),
            64 * 1024,
        );
        let ingress: AuthBusObjectiveIngress = serde_json::from_value(signed["ingress"].clone())?;
        assert_eq!(ingress.sequence, 1);
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
        let public: [u8; 32] = serde_json::from_str(&std::env::var("HEPTA_SERVICE_PUBLIC_KEY")?)?;
        let key = ed25519_dalek::VerifyingKey::from_bytes(&public)?;
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
        assert!(grant.grant.grant_id.ends_with(":2"));
        key.verify(
            &grant.grant.signing_bytes()?,
            &ed25519_dalek::Signature::from_slice(&grant.signature)?,
        )?;
        let bytes = serde_json::to_vec(
            &serde_json::json!({"schema_version":1,"operation":"runtime.cognitive.checkpoint.v1","request_id":"00000000000000010000000000000001","command":"read_head","expected":null,"proposal":null}),
        )?;
        checkpoint.write_all(&(bytes.len() as u32).to_be_bytes())?;
        checkpoint.write_all(&bytes)?;
        let mut response = Vec::new();
        checkpoint.read_to_end(&mut response)?;
        assert!(
            response.is_empty(),
            "absent checkpoint must not emit an ACK"
        );
        println!(
            "{}",
            serde_json::json!({"qualification":"root_authority_original_peer_v1","uid":60001,"no_new_privileges":true,"capabilities_clear":true,"feed_elapsed_ms":feed_ms,"objective_sequence":1,"final_use_sequence":2,"checkpoint_ack":false,"production_ready":false})
        );
        Ok(())
    }
}

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    qualification::run()
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("authority_host_peer_qualification requires Linux");
    std::process::exit(1);
}
