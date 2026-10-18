//! Root-only, isolated qualification geometry for the ordinary Agentd image.
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn permissions(path: &Path, uid: u32, mode: u32) -> Result<()> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode))?;
    std::os::unix::fs::chown(path, Some(uid), Some(975))?;
    Ok(())
}
fn tree(path: &Path, uid: u32, directory: u32, file: u32) -> Result<()> {
    permissions(path, uid, directory)?;
    for entry in fs::read_dir(path)? {
        let path = entry?.path();
        if path.is_dir() {
            tree(&path, uid, directory, file)?;
        } else {
            permissions(&path, uid, file)?;
        }
    }
    Ok(())
}
fn main() -> Result<()> {
    ensure!(
        unsafe { libc::geteuid() } == 0,
        "qualification requires Root"
    );
    let args = std::env::args().collect::<Vec<_>>();
    ensure!(args.len() == 3, "init|promote isolated-root");
    let root = Path::new(&args[2]).canonicalize()?;
    ensure!(
        root.starts_with("/var/lib")
            && root
                .file_name()
                .is_some_and(|v| v.to_string_lossy().starts_with("hepta-secrets-agentd-q-")),
        "isolated qualification namespace only"
    );
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let agents = [
        (986, "3ad2bb64-09ba-4811-b892-466c5fd952df"),
        (969, "10b204bc-ec72-48a2-a2c2-cf5d2f5ed730"),
    ];
    match args[1].as_str() {
        "init" => {
            ensure!(
                !fleet.as_path().exists(),
                "never replace existing Fleet history"
            );
            let registry = FleetRegistry::initialize(fleet.clone())?;
            let mut fixtures = Vec::new();
            for (uid, id) in agents {
                let id = AgentId::parse(id)?;
                let workspace = root.join(format!("workspace-{uid}"));
                fs::create_dir(&workspace)?;
                let record = registry.register(AgentManifest::new(
                    id.clone(),
                    WorkspaceBinding::new(&workspace, &fleet)?,
                    ResourceBudget::local_default(),
                )?)?;
                registry.compare_and_transition(&id, 0, AgentLifecycle::Starting)?;
                permissions(&workspace, uid, 0o700)?;
                let layout = record.layout;
                tree(layout.agent_root(), 0, 0o750, 0o640)?;
                for path in [
                    layout.home_root(),
                    layout.run_root(),
                    layout.logs_root(),
                    layout.cognitive_root(),
                    layout.matrix_root(),
                    layout.automation_root(),
                ] {
                    tree(path, uid, 0o700, 0o600)?;
                }
                let parent = layout
                    .agentd_control_socket()
                    .parent()
                    .ok_or_else(|| anyhow::anyhow!("socket parent"))?;
                fs::create_dir(parent)?;
                permissions(parent, uid, 0o700)?;
                fixtures.push(serde_json::json!({"uid":uid,"gid":975,"agent_id":id.as_str(),"workspace":workspace,"home":layout.home_root(),"run":layout.run_root(),"socket":layout.agentd_control_socket()}));
            }
            for path in [
                fleet.as_path(),
                registry.layout().run_root(),
                registry.layout().releases_root(),
                registry.layout().agents_root(),
            ] {
                permissions(path, 0, 0o750)?;
            }
            permissions(registry.layout().state_root(), 0, 0o700)?;
            fs::write(
                root.join("agent-fixtures.json"),
                serde_json::to_vec(&fixtures)?,
            )?;
            println!(
                "{}",
                serde_json::json!({"initialized":true,"agents":fixtures})
            );
        }
        "promote" => {
            let registry = FleetRegistry::open_existing(fleet)?;
            for (_, id) in agents {
                registry.compare_and_transition(
                    &AgentId::parse(id)?,
                    1,
                    AgentLifecycle::Running,
                )?;
            }
            println!("{}", serde_json::json!({"promoted_original_agents":true}));
        }
        _ => anyhow::bail!("qualification init|promote only"),
    }
    Ok(())
}
