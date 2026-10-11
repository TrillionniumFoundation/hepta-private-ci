use std::collections::BTreeSet;
use std::path::Path;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::HeptaAgentLayout;
use super::HeptaFleetLayout;
use super::HeptaFleetRoot;

#[cfg(unix)]
const HOME: &str = "/Users/operator";
#[cfg(windows)]
const HOME: &str = r"C:\Users\operator";
#[cfg(unix)]
const FLEET_ROOT: &str = "/srv/hepta/fleet";
#[cfg(windows)]
const FLEET_ROOT: &str = r"C:\srv\hepta\fleet";

const FIRST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

#[test]
fn production_layout_is_stable_and_fleet_scoped() -> Result<()> {
    let fleet_root = HeptaFleetRoot::production_default(Path::new(HOME))?;
    let layout = fleet_root.layout();
    let expected_root = Path::new(HOME).join(".local/share/hepta-vnext/fleet-v1");

    assert_eq!(
        layout,
        HeptaFleetLayout {
            fleet_root,
            fleet_config: expected_root.join("fleet.toml"),
            state_root: expected_root.join("state"),
            supervisor_database: expected_root.join("state/supervisor.sqlite3"),
            run_root: expected_root.join("run"),
            supervisor_socket: expected_root.join("run/supervisor.sock"),
            supervisor_lock: expected_root.join("run/supervisor.lock"),
            releases_root: expected_root.join("releases"),
            agents_root: expected_root.join("agents"),
        }
    );
    Ok(())
}

#[test]
fn agent_layout_uses_safe_id_component_and_disjoint_owned_roots() -> Result<()> {
    let fleet = HeptaFleetRoot::parse(FLEET_ROOT)?.layout();
    let agent_id = AgentId::parse(FIRST_AGENT_ID).map_err(|error| anyhow::anyhow!("{error}"))?;
    let layout = fleet.agent(&agent_id);
    let agent_root = Path::new(FLEET_ROOT).join("agents").join(FIRST_AGENT_ID);
    let socket_key = "aghu64s7r56mdd2v36p3hkrmci";

    assert_eq!(
        layout,
        HeptaAgentLayout {
            agent_id,
            agent_root: agent_root.clone(),
            agent_config: agent_root.join("agent.toml"),
            home_root: agent_root.join("home"),
            run_root: agent_root.join("run"),
            agentd_control_socket: Path::new(FLEET_ROOT).join(format!("run/a{socket_key}.ctl")),
            matrixd_control_socket: Path::new(FLEET_ROOT).join(format!("run/a{socket_key}.mx")),
            app_server_socket: Path::new(FLEET_ROOT).join(format!("run/a{socket_key}.app")),
            writer_lock: agent_root.join("run/writer.lock"),
            generation_cursor: agent_root.join("run/generation.json"),
            matrixd_process_lease: agent_root.join("run/supervisor-matrix-process.json"),
            logs_root: agent_root.join("logs"),
            releases_root: agent_root.join("releases"),
            active_release: agent_root.join("releases/active"),
            cognitive_root: agent_root.join("cognitive"),
            matrix_root: agent_root.join("matrix"),
            matrix_public_binding: agent_root.join("matrix/binding.json"),
            matrix_secrets_root: agent_root.join("matrix/secrets"),
            automation_root: agent_root.join("automation"),
        }
    );

    let owned_roots = BTreeSet::from([
        layout.home_root(),
        layout.run_root(),
        layout.logs_root(),
        layout.releases_root(),
        layout.cognitive_root(),
        layout.matrix_root(),
        layout.automation_root(),
    ]);
    assert_eq!(owned_roots.len(), 7);
    assert_ne!(layout.agentd_control_socket(), layout.app_server_socket());
    assert_ne!(
        layout.agentd_control_socket(),
        layout.matrixd_control_socket()
    );
    Ok(())
}

#[test]
fn distinct_agent_ids_cannot_alias_one_agent_root() -> Result<()> {
    let fleet = HeptaFleetRoot::parse(FLEET_ROOT)?.layout();
    let first =
        fleet.agent(&AgentId::parse(FIRST_AGENT_ID).map_err(|error| anyhow::anyhow!("{error}"))?);
    let second =
        fleet.agent(&AgentId::parse(SECOND_AGENT_ID).map_err(|error| anyhow::anyhow!("{error}"))?);

    assert_ne!(first, second);
    assert_ne!(first.agent_root(), second.agent_root());
    assert_ne!(
        first.agentd_control_socket(),
        second.agentd_control_socket()
    );
    assert_ne!(first.app_server_socket(), second.app_server_socket());
    assert_ne!(
        first.matrixd_control_socket(),
        second.matrixd_control_socket()
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn production_socket_paths_fit_the_darwin_sun_path_limit() -> Result<()> {
    let fleet = HeptaFleetRoot::production_default(Path::new(HOME))?.layout();
    let agent =
        fleet.agent(&AgentId::parse(FIRST_AGENT_ID).map_err(|error| anyhow::anyhow!("{error}"))?);

    for socket in [
        agent.agentd_control_socket(),
        agent.matrixd_control_socket(),
        agent.app_server_socket(),
    ] {
        assert!(
            socket.as_os_str().len() < 104,
            "socket path exceeds Darwin sun_path: {}",
            socket.display()
        );
    }
    Ok(())
}

#[test]
fn fleet_root_rejects_relative_root_and_dot_segments() {
    for root in ["fleet", "/", "/srv/hepta/../fleet", "/srv/hepta/./fleet"] {
        assert!(HeptaFleetRoot::parse(root).is_err(), "accepted {root:?}");
    }
}
