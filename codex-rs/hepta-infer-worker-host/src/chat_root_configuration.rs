//! Root's closed chat scopes supplement the original workload principal map.
use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;

use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrixd::chat::ManagedChatProject;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::RootGatewayPeerV1;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde::Deserialize;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct AgentScope {
    pub agent_id: AgentId,
    pub project_id: Option<String>,
    pub managed_project: Option<ManagedChatProject>,
    pub workspace: AbsolutePathBuf,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Configuration {
    pub schema: String,
    pub local_host_policy: PathBuf,
    pub fleet_root: PathBuf,
    pub socket: PathBuf,
    pub agents: Vec<AgentScope>,
}

impl Configuration {
    pub(super) fn read(path: &Path) -> anyhow::Result<(Self, Vec<u8>)> {
        let bytes = RootGatewayPeerV1::read_chat_configuration(path)?;
        let configuration: Self = serde_json::from_slice(&bytes)?;
        ensure!(
            configuration.schema == "hepta.native-chat-root.v1",
            "unsupported chat host schema"
        );
        HeptaFleetRoot::parse(&configuration.fleet_root)?;
        ensure!(
            configuration.local_host_policy.is_absolute(),
            "local-host policy must be absolute"
        );
        ensure!(
            configuration.socket.is_absolute() && configuration.socket.file_name().is_some(),
            "chat socket must be absolute"
        );
        ensure!(
            !configuration.agents.is_empty() && configuration.agents.len() <= 16,
            "chat host requires a bounded scope"
        );
        let mut unique = BTreeSet::new();
        for agent in &configuration.agents {
            ensure!(
                unique.insert(agent.agent_id.clone()),
                "duplicate chat scope"
            );
            match (&agent.project_id, &agent.managed_project) {
                (Some(id), None)
                    if !id.is_empty() && id.len() <= 256 && !id.chars().any(char::is_control) => {}
                (None, Some(project)) => project.validate()?,
                _ => anyhow::bail!("exactly one existing or managed project scope is required"),
            }
            ensure!(
                agent.workspace.as_path().is_dir()
                    && agent.workspace.as_path().canonicalize()? == agent.workspace.as_path(),
                "workspace must be a current canonical directory"
            );
        }
        Ok((configuration, bytes))
    }
}
