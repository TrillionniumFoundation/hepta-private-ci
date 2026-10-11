//! Typed, side-effect-free path geometry for a Hepta agent fleet.

use std::env;
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::AgentId;

use crate::validate_absolute_non_root;

pub const HEPTA_FLEET_ROOT_ENV: &str = "HEPTA_FLEET_ROOT";
const FLEET_DIRECTORY_NAME: &str = "fleet-v1";

/// A normalized, absolute, non-root path containing fleet-owned metadata.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct HeptaFleetRoot(PathBuf);

impl HeptaFleetRoot {
    pub fn parse(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        validate_absolute_non_root(&path)
            .with_context(|| format!("validate {HEPTA_FLEET_ROOT_ENV}"))?;
        Ok(Self(path))
    }

    pub fn from_env() -> Result<Self> {
        if let Some(path) = env::var_os(HEPTA_FLEET_ROOT_ENV) {
            return Self::parse(path);
        }
        let home =
            env::var_os("HOME").context("HOME is required when HEPTA_FLEET_ROOT is unset")?;
        Self::production_default(Path::new(&home))
    }

    pub fn production_default(home: &Path) -> Result<Self> {
        validate_absolute_non_root(home).context("validate home directory")?;
        Self::parse(
            home.join(".local/share/hepta-vnext")
                .join(FLEET_DIRECTORY_NAME),
        )
    }

    pub fn as_path(&self) -> &Path {
        &self.0
    }

    pub fn layout(&self) -> HeptaFleetLayout {
        HeptaFleetLayout::new(self.clone())
    }
}

impl AsRef<Path> for HeptaFleetRoot {
    fn as_ref(&self) -> &Path {
        self.as_path()
    }
}

impl fmt::Display for HeptaFleetRoot {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.display().fmt(formatter)
    }
}

/// Fleet-wide paths. Only the future supervisor may mutate the shared state
/// and run roots; independently supervised agents own their per-agent roots.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeptaFleetLayout {
    fleet_root: HeptaFleetRoot,
    fleet_config: PathBuf,
    state_root: PathBuf,
    supervisor_database: PathBuf,
    run_root: PathBuf,
    supervisor_socket: PathBuf,
    supervisor_lock: PathBuf,
    releases_root: PathBuf,
    agents_root: PathBuf,
}

impl HeptaFleetLayout {
    pub fn new(fleet_root: HeptaFleetRoot) -> Self {
        let state_root = fleet_root.as_path().join("state");
        let run_root = fleet_root.as_path().join("run");
        Self {
            fleet_config: fleet_root.as_path().join("fleet.toml"),
            supervisor_database: state_root.join("supervisor.sqlite3"),
            supervisor_socket: run_root.join("supervisor.sock"),
            supervisor_lock: run_root.join("supervisor.lock"),
            releases_root: fleet_root.as_path().join("releases"),
            agents_root: fleet_root.as_path().join("agents"),
            fleet_root,
            state_root,
            run_root,
        }
    }

    pub fn fleet_root(&self) -> &HeptaFleetRoot {
        &self.fleet_root
    }

    pub fn fleet_config(&self) -> &Path {
        &self.fleet_config
    }

    pub fn state_root(&self) -> &Path {
        &self.state_root
    }

    pub fn supervisor_database(&self) -> &Path {
        &self.supervisor_database
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn supervisor_socket(&self) -> &Path {
        &self.supervisor_socket
    }

    pub fn supervisor_lock(&self) -> &Path {
        &self.supervisor_lock
    }

    /// Fleet-owned immutable release catalog. Agents and control clients
    /// never supply executable paths to the supervisor.
    pub fn releases_root(&self) -> &Path {
        &self.releases_root
    }

    pub fn agents_root(&self) -> &Path {
        &self.agents_root
    }

    pub fn agent(&self, agent_id: &AgentId) -> HeptaAgentLayout {
        HeptaAgentLayout::new(
            self.agents_root.join(agent_id.as_str()),
            self.run_root.clone(),
            agent_id.clone(),
        )
    }
}

/// Paths exclusively owned by one independently supervised workspace agent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HeptaAgentLayout {
    agent_id: AgentId,
    agent_root: PathBuf,
    agent_config: PathBuf,
    home_root: PathBuf,
    run_root: PathBuf,
    agentd_control_socket: PathBuf,
    matrixd_control_socket: PathBuf,
    app_server_socket: PathBuf,
    writer_lock: PathBuf,
    generation_cursor: PathBuf,
    matrixd_process_lease: PathBuf,
    logs_root: PathBuf,
    releases_root: PathBuf,
    active_release: PathBuf,
    cognitive_root: PathBuf,
    matrix_root: PathBuf,
    matrix_public_binding: PathBuf,
    matrix_secrets_root: PathBuf,
    automation_root: PathBuf,
}

impl HeptaAgentLayout {
    fn new(agent_root: PathBuf, fleet_run_root: PathBuf, agent_id: AgentId) -> Self {
        let run_root = agent_root.join("run");
        let releases_root = agent_root.join("releases");
        let socket_key = compact_socket_key(&agent_id);
        Self {
            agent_config: agent_root.join("agent.toml"),
            home_root: agent_root.join("home"),
            agentd_control_socket: fleet_run_root.join(format!("a{socket_key}.ctl")),
            matrixd_control_socket: fleet_run_root.join(format!("a{socket_key}.mx")),
            app_server_socket: fleet_run_root.join(format!("a{socket_key}.app")),
            writer_lock: run_root.join("writer.lock"),
            generation_cursor: run_root.join("generation.json"),
            matrixd_process_lease: run_root.join("supervisor-matrix-process.json"),
            logs_root: agent_root.join("logs"),
            active_release: releases_root.join("active"),
            cognitive_root: agent_root.join("cognitive"),
            matrix_root: agent_root.join("matrix"),
            matrix_public_binding: agent_root.join("matrix/binding.json"),
            matrix_secrets_root: agent_root.join("matrix/secrets"),
            automation_root: agent_root.join("automation"),
            agent_id,
            agent_root,
            run_root,
            releases_root,
        }
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn agent_root(&self) -> &Path {
        &self.agent_root
    }

    pub fn agent_config(&self) -> &Path {
        &self.agent_config
    }

    pub fn home_root(&self) -> &Path {
        &self.home_root
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn app_server_socket(&self) -> &Path {
        &self.app_server_socket
    }

    pub fn agentd_control_socket(&self) -> &Path {
        &self.agentd_control_socket
    }

    /// Per-Agent Matrix companion control socket. This remains separate from
    /// agentd so a Matrix failure cannot block the execution plane.
    pub fn matrixd_control_socket(&self) -> &Path {
        &self.matrixd_control_socket
    }

    pub fn writer_lock(&self) -> &Path {
        &self.writer_lock
    }

    pub fn generation_cursor(&self) -> &Path {
        &self.generation_cursor
    }

    /// Supervisor-owned durable identity for the per-Agent Matrix process.
    pub fn matrixd_process_lease(&self) -> &Path {
        &self.matrixd_process_lease
    }

    pub fn logs_root(&self) -> &Path {
        &self.logs_root
    }

    pub fn releases_root(&self) -> &Path {
        &self.releases_root
    }

    pub fn active_release(&self) -> &Path {
        &self.active_release
    }

    pub fn cognitive_root(&self) -> &Path {
        &self.cognitive_root
    }

    pub fn matrix_root(&self) -> &Path {
        &self.matrix_root
    }

    /// Non-secret Matrix room/identity binding consumed by the companion and
    /// observed by the lifecycle supervisor.
    pub fn matrix_public_binding(&self) -> &Path {
        &self.matrix_public_binding
    }

    /// Private per-Agent credential/crypto-store root. The supervisor knows
    /// only this path and must never load or copy its contents.
    pub fn matrix_secrets_root(&self) -> &Path {
        &self.matrix_secrets_root
    }

    /// Private durable timer/task state for this exact Workspace Agent.
    pub fn automation_root(&self) -> &Path {
        &self.automation_root
    }
}

/// Encodes all 128 AgentId bits into 26 lowercase RFC 4648 base32 characters.
///
/// macOS limits Unix-domain socket paths to 103 bytes. Keeping the complete
/// identity while avoiding the deep per-agent directory prevents collisions
/// and leaves the production fleet root enough path-length headroom.
fn compact_socket_key(agent_id: &AgentId) -> String {
    const ALPHABET: &[u8; 32] = b"abcdefghijklmnopqrstuvwxyz234567";
    let mut uuid_bytes = [0_u8; 16];
    let mut nibble = None;
    let mut index = 0;
    for byte in agent_id.as_str().bytes().filter(|byte| *byte != b'-') {
        let value = match byte {
            b'0'..=b'9' => byte - b'0',
            b'a'..=b'f' => byte - b'a' + 10,
            _ => unreachable!("AgentId has already validated its alphabet"),
        };
        if let Some(high) = nibble.take() {
            uuid_bytes[index] = high << 4 | value;
            index += 1;
        } else {
            nibble = Some(value);
        }
    }
    debug_assert_eq!(index, uuid_bytes.len());

    let mut output = String::with_capacity(26);
    let mut accumulator = 0_u32;
    let mut bits = 0_u8;
    for byte in uuid_bytes {
        accumulator = accumulator << 8 | u32::from(byte);
        bits += 8;
        while bits >= 5 {
            bits -= 5;
            output.push(ALPHABET[((accumulator >> bits) & 0x1f) as usize] as char);
        }
    }
    if bits > 0 {
        output.push(ALPHABET[((accumulator << (5 - bits)) & 0x1f) as usize] as char);
    }
    debug_assert_eq!(output.len(), 26);
    output
}

#[cfg(test)]
#[path = "fleet_tests.rs"]
mod tests;
