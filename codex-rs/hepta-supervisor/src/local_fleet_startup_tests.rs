//! Real root/native cgroup child and the exact startup-maintenance phase.
//! The blocked recovery closure models a slow catalog/journal read; it issues
//! no grant, mutates no Agent lifecycle, and does not replace process adoption.

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use tokio_util::sync::CancellationToken;

use super::super::LocalFleetHost;
use crate::AgentCommand;
use crate::SpawnSpec;
use crate::daemon::owner::SingleInstanceLock;
use crate::daemon::startup::recover_with_local_host;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

struct Fixture {
    host: Arc<LocalFleetHost>,
    instance: Arc<SingleInstanceLock>,
    child: Child,
    agent: AgentId,
    execution_id: String,
    cgroup: String,
    _temp: tempfile::TempDir,
}

impl Fixture {
    async fn open() -> Result<Self> {
        if unsafe { libc::geteuid() } != 0 {
            return Err("requires actual root and writable native cgroup v2".into());
        }
        let temp = tempfile::tempdir_in("/var/lib/hepta-private-ci")?;
        let cgroup = format!("hepta-startup-native-{}", uuid::Uuid::new_v4().simple());
        let agent = AgentId::parse(uuid::Uuid::new_v4().to_string())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let registry =
            FleetRegistry::initialize(HeptaFleetRoot::parse(temp.path().join("fleet"))?)?;
        let instance = Arc::new(SingleInstanceLock::acquire(
            registry.layout().supervisor_lock(),
        )?);
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
        let release = registry.install_release(
            "native-startup-sleep".parse()?,
            Path::new("/usr/bin/sleep"),
            vec!["180".into()],
        )?;
        let policy = temp.path().join("policy.json");
        std::fs::write(
            &policy,
            serde_json::to_vec(&serde_json::json!({
                "version": 1, "workload_uid": 1000, "workload_gid": 1000,
                "cgroup_root": cgroup, "resource_authority_frontier": temp.path().join("frontier.json"),
                "process_thread_reserve": 64,
                "matrix_resources": { "cpu_millis": 1000, "memory_bytes": 134_217_728,
                    "accelerator_millis": 0, "concurrent_turns": 1, "tool_processes": 1, "turn_queue_slots": 64 }
            }))?,
        )?;
        std::fs::set_permissions(&policy, std::fs::Permissions::from_mode(0o600))?;
        let host = LocalFleetHost::open(&policy, registry.clone()).await?;
        let _release_read_pin = registry.prevalidate_release_for_launch(&release.release_id)?;
        let spec = SpawnSpec {
            agent_id: agent.clone(),
            generation: 1,
            fleet_root: registry.layout().fleet_root().as_path().to_path_buf(),
            workspace,
            home_root: record.layout.home_root().to_path_buf(),
            run_root: record.layout.run_root().to_path_buf(),
            control_socket: record.layout.agentd_control_socket().to_path_buf(),
            logs_root: record.layout.logs_root().to_path_buf(),
            command: AgentCommand::new(release.program, vec!["180".into()])?,
        };
        let execution = host.prepare_agent(&spec)?;
        let mut command = Command::new(&spec.command.program);
        command.args(&spec.command.args);
        host.constrain(&mut command, &execution)?;
        let mut child = command.spawn()?;
        if let Err(error) = host.bind(&execution, child.id()) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error.into());
        }
        drop(execution.launch);
        Ok(Self {
            host,
            instance,
            child,
            agent,
            execution_id: execution.id,
            cgroup,
            _temp: temp,
        })
    }

    async fn finish(mut self) -> Result<()> {
        self.host.request_stop(&self.execution_id)?;
        self.host.kill(&self.execution_id)?;
        self.child.wait()?;
        if !self.host.finish_exit(&self.execution_id)? {
            return Err("actual native execution was not reclaimed".into());
        }
        self.host.validate_retirement(&self.agent)?;
        self.host.store.close().await;
        let base = Path::new("/sys/fs/cgroup").join(&self.cgroup);
        std::fs::remove_dir(base.join(format!("agent-{}", self.agent)))?;
        std::fs::remove_dir(base)?;
        Ok(())
    }
}

// Both runs cross the unchanged 30-second resource expiry; the harness also
// includes actual installation/spawn/SQLite and native exit reclamation.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires root and writable native cgroup v2"]
async fn original_host_upkeep_covers_recovery_blocked_beyond_resource_ttl() -> Result<()> {
    let fixture = Fixture::open().await?;
    fixture.host.maintain().await?;
    let original = fixture
        .host
        .store
        .execution_hold(&fixture.execution_id)
        .await?
        .ok_or("original hold absent")?;
    let initial = fixture
        .host
        .store
        .allocation_grant(&original.context.allocation_id)
        .await?
        .ok_or("original grant absent")?;
    let first_pending = fixture
        .host
        .store
        .pending_local_renewal(&fixture.execution_id)
        .await?
        .ok_or("original pending receipt absent")?;
    let cancellation = CancellationToken::new();
    let _shutdown = cancellation.clone().drop_guard();
    let host = Arc::clone(&fixture.host);
    let check = Arc::clone(&host);
    let execution_id = fixture.execution_id.clone();
    let allocation = original.context.allocation_id.clone();
    let result = async {
        let (recovered, maintenance) = recover_with_local_host(
            host,
            Arc::clone(&fixture.instance),
            cancellation.clone(),
            move || {
                std::thread::sleep(Duration::from_secs(35));
                Ok(())
            },
        )
        .await?;
        recovered.outcome?;
        let held = check
            .store
            .execution_hold(&execution_id)
            .await?
            .ok_or("original hold lost during recovery")?;
        let grant = check.store.allocation_grant(&allocation).await?;
        let pending = check.store.pending_local_renewal(&execution_id).await?;
        cancellation.cancel();
        maintenance.await??;
        if held != original
            || fixture.child.id() as u64 != held.process_id.ok_or("native PID missing")?
        {
            return Err("recovery replaced the original native execution proof".into());
        }
        let now = super::super::trust::HostClock::system_now()?;
        let grant = grant.ok_or("slow recovery allowed the original grant to expire")?;
        if now <= initial.expires_at_ms
            || grant.expires_at_ms <= now
            || grant.lease_generation <= initial.lease_generation
        {
            return Err(
                "original host did not maintain a valid lease beyond its original expiry".into(),
            );
        }
        if check.recover_execution(&fixture.agent.to_string(), fixture.child.id())? != execution_id
        {
            return Err(
                "same PID/start/boot/cgroup binding changed during blocked recovery".into(),
            );
        }
        let pending = pending.ok_or("maintenance lost its original receipt obligation")?;
        if pending.subject_id != first_pending.subject_id || pending.authority_witness.is_none() {
            return Err("local renewal lost authoritative same-allocation receipt binding".into());
        }
        Ok(())
    }
    .await;
    cancellation.cancel();
    fixture.finish().await?;
    result
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires root and writable native cgroup v2"]
async fn early_upkeep_never_resurrects_an_already_expired_native_grant() -> Result<()> {
    let fixture = Fixture::open().await?;
    let original = fixture
        .host
        .store
        .execution_hold(&fixture.execution_id)
        .await?
        .ok_or("original hold absent")?;
    tokio::time::sleep(Duration::from_secs(35)).await;
    let cancellation = CancellationToken::new();
    let _shutdown = cancellation.clone().drop_guard();
    let result = async {
        let (recovered, maintenance) = recover_with_local_host(
            Arc::clone(&fixture.host),
            Arc::clone(&fixture.instance),
            cancellation.clone(),
            || Ok(()),
        )
        .await?;
        recovered.outcome?;
        tokio::time::sleep(Duration::from_secs(1)).await;
        cancellation.cancel();
        maintenance.await??;
        let held = fixture
            .host
            .store
            .execution_hold(&fixture.execution_id)
            .await?
            .ok_or("expired hold lost before physical exit")?;
        let mut stopped = original.clone();
        // Expiry invalidates use and durably requests the original native
        // execution's stop. Its identity and budget remain until actual exit.
        stopped.state = "stop_requested".into();
        if held != stopped {
            return Err("expiry changed the native identity or lost its stop obligation".into());
        }
        if fixture
            .host
            .store
            .allocation_grant(&original.context.allocation_id)
            .await?
            .is_some()
        {
            return Err("upkeep recreated the expired allocation grant".into());
        }
        Ok(())
    }
    .await;
    cancellation.cancel();
    fixture.finish().await?;
    result
}
