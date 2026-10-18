use std::collections::BTreeSet;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use tokio::net::UnixListener;

use super::*;
use crate::AgentCommand;
use crate::SpawnSpec;
use crate::local_fleet_host::LocalFleetHost;

const CHILD: &str = "local_model_authority::resources::tests::enrolled_resource_client_child";

#[test]
#[ignore = "executed only as the actual constrained Fleet child of the root case"]
fn enrolled_resource_client_child() -> anyhow::Result<()> {
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 1000,
        "child workload UID differs"
    );
    // Match the actual WorkerHost entry point after exec resets dumpability.
    rustix::process::set_dumpable_behavior(rustix::process::DumpableBehavior::NotDumpable)?;
    let path = std::env::var("HEPTA_RESOURCE_NATIVE_FIXTURE")?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
    let bytes = loop {
        match std::fs::read(Path::new(&path).join("request.json")) {
            Ok(bytes) => break bytes,
            Err(error)
                if error.kind() == std::io::ErrorKind::NotFound
                    && std::time::Instant::now() < deadline =>
            {
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err(error) => return Err(error.into()),
        }
    };
    let request: FleetResourceObservationRequestV1 = serde_json::from_slice(&bytes)?;
    for case in 0..6 {
        let mut candidate = serde_json::to_value(&request)?;
        match case {
            1 => candidate["subject_id"] = "different-agent".into(),
            2 => candidate["execution_id"] = "different-execution".into(),
            3 => candidate["manifest_digest"] = "f".repeat(64).into(),
            4 => candidate["extra_authority"] = true.into(),
            _ => {}
        }
        let mut stream = std::os::unix::net::UnixStream::connect(Path::new(&path).join("issuer"))?;
        stream.set_read_timeout(Some(std::time::Duration::from_secs(2)))?;
        stream.set_write_timeout(Some(std::time::Duration::from_secs(2)))?;
        let bytes = serde_json::to_vec(&candidate)?;
        stream.write_all(&u32::try_from(bytes.len())?.to_be_bytes())?;
        stream.write_all(&bytes)?;
        let mut length = [0; 4];
        let result = stream.read_exact(&mut length);
        if (1..=4).contains(&case) {
            anyhow::ensure!(result.is_err(), "foreign or ambiguous request was accepted");
            continue;
        }
        result?;
        let length = usize::try_from(u32::from_be_bytes(length))?;
        anyhow::ensure!(
            (1..=65536).contains(&length),
            "response exceeded original bound"
        );
        let mut bytes = vec![0; length];
        stream.read_exact(&mut bytes)?;
        let response: FleetResourceObservationResponseV1 = serde_json::from_slice(&bytes)?;
        assert_eq!(response.operation, FLEET_RESOURCE_OBSERVATION_OPERATION);
        assert_eq!(
            response.observation.context.execution_id,
            request.execution_id
        );
        assert_eq!(
            response.observation.context.manifest_digest,
            request.manifest_digest
        );
        assert_eq!(response.observation.process_id, std::process::id());
        let grant = response
            .observation
            .allocation
            .context("missing current allocation")?;
        anyhow::ensure!(
            !grant.revoked && grant.expires_at_ms > response.observed_at_ms,
            "returned allocation is not current"
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires root and writable native cgroup v2"]
async fn original_owner_resource_route_checks_real_peer_and_exact_launch() -> anyhow::Result<()> {
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "root qualification required"
    );
    let temp = tempfile::tempdir_in("/var/lib")?;
    let agent = AgentId::parse(uuid::Uuid::new_v4().to_string())?;
    let cgroup = format!("hepta-resource-route-{}", uuid::Uuid::new_v4().simple());
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let registry = FleetRegistry::initialize(HeptaFleetRoot::parse(temp.path().join("fleet"))?)?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, registry.layout().fleet_root())?,
        ResourceBudget {
            max_concurrent_turns: 1,
            memory_limit_mib: 128,
            max_tool_processes: 1,
            turn_queue_capacity: 64,
        },
    )?)?;
    let args = vec![
        "--exact".into(),
        CHILD.into(),
        "--ignored".into(),
        "--nocapture".into(),
    ];
    let release = registry.install_release(
        "native-resource-client".parse()?,
        &std::env::current_exe()?,
        args.clone(),
    )?;
    let policy = temp.path().join("host.json");
    std::fs::write(
        &policy,
        serde_json::to_vec(&serde_json::json!({
            "version":1,"workload_uid":1000,"workload_gid":1000,"cgroup_root":cgroup,
            "resource_authority_frontier":temp.path().join("frontier.json"),
            "process_thread_reserve":64,
            "matrix_resources":{"cpu_millis":1000,"memory_bytes":134217728,
                "accelerator_millis":0,"concurrent_turns":1,"tool_processes":1,"turn_queue_slots":64}
        }))?,
    )?;
    std::fs::set_permissions(&policy, std::fs::Permissions::from_mode(0o600))?;
    let host = LocalFleetHost::open(&policy, registry.clone()).await?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o755))?;
    let digest: String = Sha256::digest(std::fs::read(&release.program)?)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let mut config: super::super::Config = serde_json::from_value(serde_json::json!({
        "schema_version":1,"signer_id":"ordinary-model-owner",
        "key_file":temp.path().join("unused-key"),"issuer_socket":temp.path().join("issuer"),
        "process_identity_file":temp.path().join("unused-identity"),"socket_gid":1000,"workload_uid":1000,
        "state_directory":temp.path().join("model-state"),"trust_directory":temp.path().join("model-trust"),
        "revocations_file":temp.path().join("unused-revocations"),"cgroup_root":"/sys/fs/cgroup/hepta-test",
        "fleet_database":registry.layout().state_root().join("fleet-resources.sqlite3"),
        "allowed_subject_ids":[],"allowed_executable_sha256":[],"allowed_executable_paths":[],
        "grant_lifetime_ms":30000,"request_timeout_ms":2000
    }))?;
    config.allowed_subject_ids = BTreeSet::from([agent.to_string()]);
    config.allowed_executable_paths = BTreeSet::from([release.program.clone()]);
    config.allowed_executable_sha256 = BTreeSet::from([digest]);
    config.cgroup_root = Path::new("/sys/fs/cgroup").join(&cgroup);
    config.workload_policy_file = Some(policy);
    config.fleet_database = registry
        .layout()
        .state_root()
        .join("fleet-resources.sqlite3");
    config.validate()?;
    let state = temp.path().join("model-state");
    std::fs::create_dir(&state)?;
    std::fs::set_permissions(&state, std::fs::Permissions::from_mode(0o700))?;
    let signer = ed25519_dalek::SigningKey::from_bytes(&[7; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &state,
        config.signer_id.clone(),
        signer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let issuer = Issuer {
        executables: super::super::ExecutableCache::prewarm(
            &config.allowed_executable_paths,
            &config.allowed_executable_sha256,
        )?,
        verifier: codex_hepta_fleet::FleetExecutionVerifier::open(&config.fleet_database).await?,
        config,
        signer,
        authority,
        clock: Arc::new(SystemAuthorityClock),
    };
    let listener = UnixListener::bind(temp.path().join("issuer"))?;
    std::os::unix::fs::chown(temp.path().join("issuer"), Some(0), Some(1000))?;
    std::fs::set_permissions(
        temp.path().join("issuer"),
        std::fs::Permissions::from_mode(0o660),
    )?;
    let spec = SpawnSpec {
        agent_id: agent.clone(),
        generation: 1,
        fleet_root: registry.layout().fleet_root().as_path().to_path_buf(),
        workspace,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        logs_root: record.layout.logs_root().to_path_buf(),
        command: AgentCommand::new(release.program, args.into_iter().map(Into::into).collect())?,
    };
    let execution = host.prepare_agent(&spec)?;
    let mut command = Command::new(&spec.command.program);
    command
        .args(&spec.command.args)
        .env("HEPTA_RESOURCE_NATIVE_FIXTURE", temp.path());
    host.constrain(&mut command, &execution)?;
    let mut child = command.spawn()?;
    host.bind(&execution, child.id())?;
    drop(execution.launch);
    let context = issuer
        .verifier
        .observe_bound_local_resources(&agent.to_string(), child.id())
        .await?
        .context;
    let request = FleetResourceObservationRequestV1 {
        schema_version: 1,
        operation: FLEET_RESOURCE_OBSERVATION_OPERATION.into(),
        subject_id: agent.to_string(),
        execution_id: execution.id.clone(),
        manifest_digest: context.manifest_digest,
    };
    std::fs::write(
        temp.path().join("request.json"),
        serde_json::to_vec(&request)?,
    )?;
    std::fs::set_permissions(
        temp.path().join("request.json"),
        std::fs::Permissions::from_mode(0o644),
    )?;
    let result = async {
        for case in 0..6 {
            let (stream, _) =
                tokio::time::timeout(std::time::Duration::from_secs(3), listener.accept())
                    .await??;
            if case == 0 {
                let peer = super::super::capture_peer(
                    &issuer.config,
                    &issuer.verifier,
                    &issuer.executables,
                    &stream,
                )
                .await?;
                let response = observe(&issuer, request.clone(), &peer).await?;
                let expiry = response
                    .observation
                    .allocation
                    .as_ref()
                    .context("missing grant")?
                    .expires_at_ms;
                assert!(
                    validate_current(
                        &request,
                        &peer,
                        &response.observation,
                        /*authority_epoch*/ 1,
                        expiry
                    )
                    .is_err()
                );
                assert!(
                    validate_current(
                        &request,
                        &peer,
                        &response.observation,
                        /*authority_epoch*/ 2,
                        response.observed_at_ms
                    )
                    .is_err()
                );
                let mut revoked = response.observation.clone();
                revoked
                    .allocation
                    .as_mut()
                    .context("missing grant")?
                    .revoked = true;
                assert!(
                    validate_current(
                        &request,
                        &peer,
                        &revoked,
                        /*authority_epoch*/ 1,
                        response.observed_at_ms
                    )
                    .is_err()
                );
                revoked.allocation = None;
                assert!(
                    validate_current(
                        &request,
                        &peer,
                        &revoked,
                        /*authority_epoch*/ 1,
                        response.observed_at_ms
                    )
                    .is_err()
                );
            }
            let result = tokio::time::timeout(
                std::time::Duration::from_secs(2),
                issuer.exchange(stream, &super::super::Progress::new()),
            )
            .await?;
            assert_eq!(result.is_ok(), !(1..=4).contains(&case));
        }
        // Root's own process is not an enrolled workload or a substitute Agent.
        let _root_client = tokio::net::UnixStream::connect(temp.path().join("issuer")).await?;
        let (stream, _) = listener.accept().await?;
        assert!(
            issuer
                .exchange(stream, &super::super::Progress::new())
                .await
                .is_err()
        );
        Ok::<(), anyhow::Error>(())
    }
    .await;
    if result.is_err() {
        let _ = child.kill();
    }
    let status = child.wait()?;
    host.finish_exit(&execution.id)?;
    drop(host);
    let base = Path::new("/sys/fs/cgroup").join(&cgroup);
    std::fs::remove_dir(base.join(format!("agent-{agent}")))?;
    std::fs::remove_dir(base)?;
    result?;
    anyhow::ensure!(status.success(), "actual enrolled child failed");
    Ok(())
}
