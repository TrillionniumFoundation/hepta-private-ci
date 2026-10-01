use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use sha2::Digest;
use sha2::Sha256;
use tokio::runtime::Handle;

use super::super::LocalFleetHost;
use crate::AgentCommand;
use crate::SpawnSpec;

// This exercises the exact production nesting: a serialized blocking owner
// polls the request future, which calls the synchronous process resource port.
// Run explicitly under root on a writable native cgroup v2 host; no mock or
// skipped assertion can stand in for kernel placement and exit reclamation.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires root and writable native cgroup v2"]
async fn nested_lifecycle_resource_calls_prepare_bind_and_reclaim_real_child()
-> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let fixture = tempfile::tempdir_in("/var/lib/hepta-private-ci")?;
    let cgroup = format!("hepta-runtime-native-{}", uuid::Uuid::new_v4().simple());
    let agent = AgentId::parse(uuid::Uuid::new_v4().to_string())?;
    let workspace = fixture.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let registry = FleetRegistry::initialize(HeptaFleetRoot::parse(fixture.path().join("fleet"))?)?;
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, registry.layout().fleet_root())?,
        ResourceBudget {
            max_concurrent_turns: 1,
            memory_limit_mib: 128,
            max_tool_processes: 1,
            turn_queue_capacity: 64,
        },
    )?;
    let record = registry.register(manifest)?;
    let release = registry.install_release(
        "native-sleep".parse()?,
        Path::new("/usr/bin/sleep"),
        vec!["30".into()],
    )?;
    let policy = fixture.path().join("policy.json");
    std::fs::write(
        &policy,
        serde_json::to_vec(&serde_json::json!({
            "version": 1,
            "workload_uid": 1000,
            "workload_gid": 1000,
            "cgroup_root": cgroup,
            "resource_authority_frontier": fixture.path().join("frontier.json"),
            "process_thread_reserve": 64,
            "matrix_resources": {
                "cpu_millis": 1000, "memory_bytes": 134_217_728,
                "accelerator_millis": 0, "concurrent_turns": 1,
                "tool_processes": 1, "turn_queue_slots": 64
            }
        }))?,
    )?;
    std::fs::set_permissions(&policy, std::fs::Permissions::from_mode(0o600))?;
    let host = LocalFleetHost::open(&policy, registry.clone()).await?;
    // This is the exact production phase boundary: normalization/owner open
    // precedes the read worker, and its fact pin precedes lifecycle admission.
    let release_read_pin = registry.prevalidate_release_for_launch(&release.release_id)?;
    let spec = SpawnSpec {
        agent_id: agent.clone(),
        generation: 1,
        fleet_root: registry.layout().fleet_root().as_path().to_path_buf(),
        workspace,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        logs_root: record.layout.logs_root().to_path_buf(),
        command: AgentCommand::new(release.program, vec!["30".into()])?,
    };
    let owner_run_root = record.layout.owner_run_root().to_path_buf();
    let manifest_bytes = serde_json::to_vec(&record.manifest)?;
    let runtime = Handle::current();
    let owner = Arc::clone(&host);
    tokio::task::spawn_blocking(move || {
        runtime.block_on(async move {
            let _release_read_pin = release_read_pin;
            let proof = owner
                .prove_never_spawned(&spec.agent_id)?
                .ok_or("missing native pre-spawn proof")?;
            let epoch = uuid::Uuid::new_v4().to_string();
            let digest = "a".repeat(64);
            let prior = crate::prepare_mutation(
                &owner_run_root,
                /*request_id*/ 91,
                &spec.agent_id,
                &epoch,
                crate::SupervisordMutation::Start,
                &digest,
                /*intent_sequence*/ 1,
            )?;
            crate::mutation_journal::resolve_before_spawn(
                &owner_run_root,
                &prior.idempotency_key,
                &digest,
                &proof,
            )?;
            crate::prepare_mutation(
                &owner_run_root,
                /*request_id*/ 92,
                &spec.agent_id,
                &epoch,
                crate::SupervisordMutation::Start,
                &digest,
                /*intent_sequence*/ 2,
            )?;
            // Live registration initially creates private owner metadata; the
            // launch must expose only the shared metadata, never cold history.
            std::fs::set_permissions(&owner_run_root, std::fs::Permissions::from_mode(0o700))?;
            let execution = owner.prepare_agent(&spec)?;
            assert_eq!(
                std::fs::metadata(&owner_run_root)?.permissions().mode() & 0o7777,
                0o750
            );
            // The real launch ownership preparation must not expose private
            // history or make the earlier NoEffect receipt unqueryable.
            let archived =
                crate::mutation_journal_slots::lookup(&owner_run_root, /*request_id*/ 91)?
                    .ok_or("archived request lost across real launch preparation")?;
            assert_eq!(
                archived.status.phase,
                crate::DurableMutationPhaseV1::NoEffect
            );
            let held = owner.store.execution_hold(&execution.id).await?;
            let held = held.ok_or("prepared execution was not durable before spawn")?;
            assert_eq!((held.state.as_str(), held.process_id), ("prepared", None));
            // The factual prefix must preserve every byte of the original
            // installed-launch commitment used by recovery and native holds.
            let mut original = Sha256::new();
            original.update(std::fs::read(&spec.command.program)?);
            original.update(&manifest_bytes);
            original.update(spec.generation.to_be_bytes());
            for (name, value) in &execution.environment {
                for bytes in [name.as_encoded_bytes(), value.as_encoded_bytes()] {
                    original.update((bytes.len() as u64).to_be_bytes());
                    original.update(bytes);
                }
            }
            for arg in &spec.command.args {
                let bytes = arg.as_encoded_bytes();
                original.update((bytes.len() as u64).to_be_bytes());
                original.update(bytes);
            }
            assert_eq!(
                held.context.manifest_digest,
                super::super::hex_digest(original.finalize())
            );
            assert!(owner.validate_retirement(&spec.agent_id).is_err());

            let mut command = Command::new(&spec.command.program);
            command.args(&spec.command.args);
            owner.constrain(&mut command, &execution)?;
            let mut child = command.spawn()?;
            owner.bind(&execution, child.id())?;
            assert_eq!(
                owner.recover_execution(&spec.agent_id.to_string(), child.id())?,
                execution.id
            );
            let status = std::fs::read_to_string(format!("/proc/{}/status", child.id()))?;
            assert!(
                status
                    .lines()
                    .any(|line| line == "Uid:\t1000\t1000\t1000\t1000")
            );
            assert!(
                status
                    .lines()
                    .any(|line| line == "Gid:\t1000\t1000\t1000\t1000")
            );
            let membership = std::fs::read_to_string(format!("/proc/{}/cgroup", child.id()))?;
            assert_eq!(membership, format!("0::/{}\n", execution.relative));
            let bound = owner.store.execution_hold(&execution.id).await?;
            let bound = bound.ok_or("bound execution disappeared")?;
            assert_eq!(
                (bound.state.as_str(), bound.process_id),
                ("running", Some(u64::from(child.id())))
            );
            drop(execution.launch);

            owner.request_stop(&execution.id)?;
            owner.kill(&execution.id)?;
            assert!(!child.wait()?.success());
            assert!(owner.finish_exit(&execution.id)?);
            owner.validate_retirement(&spec.agent_id)?;
            assert!(owner.prove_never_spawned(&spec.agent_id)?.is_none());
            assert_eq!(
                owner
                    .store
                    .active_execution_for_principal(&spec.agent_id.to_string())
                    .await?,
                None
            );
            Ok::<(), Box<dyn std::error::Error + Send + Sync>>(())
        })
    })
    .await??;
    host.store.close().await;
    let base = Path::new("/sys/fs/cgroup").join(&cgroup);
    std::fs::remove_dir(base.join(format!("agent-{agent}")))?;
    std::fs::remove_dir(base)?;
    Ok(())
}
