use super::*;

fn fixture() -> anyhow::Result<(
    Policy,
    AgentId,
    Frontier,
    FleetExecutionResourceObservationV1,
)> {
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001".to_string())?;
    let resources = serde_json::json!({"cpu_millis":1000,"memory_bytes":134217728,
        "accelerator_millis":0,"concurrent_turns":1,"tool_processes":1,"turn_queue_slots":64});
    let policy: Policy = serde_json::from_value(serde_json::json!({
        "version":1,"workload_uid":986,"workload_gid":975,
        "agent_workload_uids":{agent.as_str():969},"cgroup_root":"hepta-test",
        "resource_authority_frontier":"/var/lib/hepta-test/frontier.json",
        "process_thread_reserve":64,"matrix_resources":resources
    }))?;
    let frontier = Frontier {
        owner_id: "local-supervisor-resources".into(),
        frontier: AuthorityLeaseFrontier::for_empty_epoch(7)?,
    };
    let observation = serde_json::from_value(serde_json::json!({
        "context":{"execution_id":"00000000-0000-4000-8000-000000000002",
            "allocation_id":"allocation","principal_id":agent.as_str(),"host_id":"host",
            "host_generation":3,"lease_generation":4,"manifest_digest":"manifest",
            "resources":resources,"containment":format!("hepta-test/agent-{agent}/main-00000000-0000-4000-8000-000000000002")},
        "process_id":11,"process_start_ticks":12,
        "allocation":{"allocation_id":"allocation","request_id":"request","principal_id":agent.as_str(),
            "host_id":"host","failure_domain_id":"local","host_generation":3,"authority_epoch":7,
            "lease_generation":5,"expires_at_ms":200,"resources":resources,
            "semantic_digest":"manifest","revoked":false}
    }))?;
    Ok((policy, agent, frontier, observation))
}

#[test]
fn enrolled_uid_and_exact_execution_containment_are_required() -> anyhow::Result<()> {
    let (policy, agent, frontier, observation) = fixture()?;
    validate(&policy, &agent, 11, 969, 100, &frontier, &observation)?;
    assert!(validate(&policy, &agent, 11, 986, 100, &frontier, &observation).is_err());
    assert!(validate(&policy, &agent, 12, 969, 100, &frontier, &observation).is_err());
    let foreign = AgentId::parse("00000000-0000-4000-8000-000000000003".to_string())?;
    assert!(validate(&policy, &foreign, 11, 969, 100, &frontier, &observation).is_err());
    for value in [
        "hepta-test/agent-foreign/main-00000000-0000-4000-8000-000000000002",
        "hepta-other/agent-agent/main-00000000-0000-4000-8000-000000000002",
    ] {
        let mut changed = observation.clone();
        changed.context.containment = value.into();
        assert!(validate(&policy, &agent, 11, 969, 100, &frontier, &changed).is_err());
    }
    Ok(())
}

#[test]
fn original_allocation_expiry_revocation_and_epoch_remain_mandatory() -> anyhow::Result<()> {
    let (policy, agent, frontier, observation) = fixture()?;
    assert!(validate(&policy, &agent, 11, 969, 200, &frontier, &observation).is_err());
    let mut changed = observation;
    changed
        .allocation
        .as_mut()
        .context("fixture grant")?
        .authority_epoch += 1;
    assert!(validate(&policy, &agent, 11, 969, 100, &frontier, &changed).is_err());
    changed
        .allocation
        .as_mut()
        .context("fixture grant")?
        .authority_epoch = 7;
    changed
        .allocation
        .as_mut()
        .context("fixture grant")?
        .revoked = true;
    assert!(validate(&policy, &agent, 11, 969, 100, &frontier, &changed).is_err());
    changed.allocation = None;
    assert!(validate(&policy, &agent, 11, 969, 100, &frontier, &changed).is_err());
    Ok(())
}

#[test]
fn kernel_metadata_is_physical_and_bounded() -> anyhow::Result<()> {
    assert_eq!(process_uid(std::process::id())?, unsafe { libc::getuid() });
    assert!(process_uid(u32::MAX).is_err());
    assert_eq!(current_boot_identity()?, current_boot_identity()?);
    assert!(read_kernel("/proc/self/status", 1).is_err());
    Ok(())
}

#[tokio::test]
async fn unprivileged_observer_is_denied_before_opening_any_authority_state() -> anyhow::Result<()>
{
    if unsafe { libc::geteuid() } != 0 {
        let root = HeptaFleetRoot::parse("/var/lib/does-not-exist-resource-observer")?;
        let (_, agent, _, _) = fixture()?;
        let error =
            observe_local_fleet_resources(&root, Path::new("/does-not-exist-policy"), &agent, 11)
                .await
                .err()
                .context("unprivileged read must fail")?;
        assert_eq!(error.to_string(), "resource observation requires root");
    } else {
        assert!(process_uid(std::process::id())? == 0);
    }
    Ok(())
}

#[test]
fn mutable_frontier_path_cannot_become_a_root_resource_witness() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("frontier.json");
    std::fs::write(
        &path,
        serde_json::to_vec(&serde_json::json!({"owner_id":"local-supervisor-resources",
        "frontier":AuthorityLeaseFrontier::for_empty_epoch(7)?}))?,
    )?;
    assert!(read_frontier(&path).is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires root and writable native cgroup v2; run explicitly"]
async fn original_owner_root_observer_is_read_only_and_rejects_real_revocation()
-> anyhow::Result<()> {
    use crate::AgentCommand;
    use crate::SpawnSpec;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use std::os::unix::fs::PermissionsExt;
    anyhow::ensure!(
        unsafe { libc::geteuid() } == 0,
        "root qualification required"
    );
    let parent = if trust::validate_root_directory(Path::new("/data")).is_ok() {
        "/data"
    } else {
        "/var/lib"
    };
    let temp = tempfile::tempdir_in(parent)?;
    // Only this isolated fixture namespace is traversable by its real child;
    // authority policy, frontier and database retain their owner protections.
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o711))?;
    let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
    let agent = AgentId::parse(uuid::Uuid::new_v4().to_string())?;
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let release = registry.install_release(
        "root-observer-native".parse()?,
        Path::new("/usr/bin/sleep"),
        vec!["30".into()],
    )?;
    let cgroup = format!("hepta-root-observe-{}", uuid::Uuid::new_v4().simple());
    let policy_path = temp.path().join("host.json");
    let frontier_path = temp.path().join("frontier.json");
    std::fs::write(
        &policy_path,
        serde_json::to_vec(&serde_json::json!({
            "version":1,"workload_uid":1000,"workload_gid":1000,"cgroup_root":cgroup,
            "resource_authority_frontier":frontier_path,"process_thread_reserve":64,
            "matrix_resources":{"cpu_millis":1000,"memory_bytes":134217728,"accelerator_millis":0,
                "concurrent_turns":1,"tool_processes":1,"turn_queue_slots":64}
        }))?,
    )?;
    std::fs::set_permissions(&policy_path, std::fs::Permissions::from_mode(0o600))?;
    let host = super::super::LocalFleetHost::open(&policy_path, registry.clone()).await?;
    let spec = SpawnSpec {
        agent_id: agent.clone(),
        generation: 1,
        fleet_root: root.as_path().to_path_buf(),
        workspace,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        logs_root: record.layout.logs_root().to_path_buf(),
        command: AgentCommand::new(release.program, vec!["30".into()])?,
    };
    let execution = host.prepare_agent(&spec)?;
    let mut command = std::process::Command::new(&spec.command.program);
    command.args(&spec.command.args);
    host.constrain(&mut command, &execution)?;
    let mut child = command.spawn()?;
    host.bind(&execution, child.id())?;
    drop(execution.launch);
    let result = async {
        let database = root.layout().state_root().join("fleet-resources.sqlite3");
        let paths = [
            policy_path.clone(),
            frontier_path,
            database.clone(),
            database.with_extension("sqlite3-wal"),
        ];
        let before = paths
            .iter()
            .map(std::fs::read)
            .collect::<Result<Vec<_>, _>>()?;
        let observation =
            observe_local_fleet_resources(&root, &policy_path, &agent, child.id()).await?;
        assert_eq!(observation.observation.context.execution_id, execution.id);
        assert_eq!(observation.observation.process_id, child.id());
        assert_eq!(observation.boot_identity, current_boot_identity()?);
        let grant = observation
            .observation
            .allocation
            .context("missing actual grant")?;
        assert!(!grant.revoked && grant.expires_at_ms > observation.observed_at_ms);
        assert_eq!(grant.authority_epoch, observation.resource_authority_epoch);
        assert_eq!(
            paths
                .iter()
                .map(std::fs::read)
                .collect::<Result<Vec<_>, _>>()?,
            before
        );
        let foreign = AgentId::parse(uuid::Uuid::new_v4().to_string())?;
        assert!(
            observe_local_fleet_resources(&root, &policy_path, &foreign, child.id())
                .await
                .is_err()
        );
        assert!(
            observe_local_fleet_resources(&root, &policy_path, &agent, std::process::id())
                .await
                .is_err()
        );
        host.request_stop(&execution.id)?;
        assert!(
            child.try_wait()?.is_none(),
            "actual child must still exist at the revoked read"
        );
        assert!(
            observe_local_fleet_resources(&root, &policy_path, &agent, child.id())
                .await
                .is_err()
        );
        Ok::<(), anyhow::Error>(())
    }
    .await;
    let _ = child.kill();
    child.wait()?;
    host.finish_exit(&execution.id)?;
    drop(host);
    let base = Path::new("/sys/fs/cgroup").join(cgroup);
    std::fs::remove_dir(base.join(format!("agent-{agent}")))?;
    std::fs::remove_dir(base)?;
    result
}
