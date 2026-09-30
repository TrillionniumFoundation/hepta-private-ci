//! Startup-only binding to the existing Supervisor owner. No hot-path RPC,
//! candidate selection, writer handoff, code loading or additional store.
use std::str::FromStr;
use std::time::Duration;

use codex_hepta_agent_components::fleet::RuntimeModuleCatalogV1;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;
use codex_hepta_agent_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use codex_hepta_agent_protocol::RuntimeModuleSelectionV1;
use codex_hepta_agent_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use codex_uds::UnixStream;
use serde::Deserialize;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::runtime_executable::RuntimeExecutableIdentity;

/// Select the startup composition source, never a new effect authority.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum RuntimeModuleProfileV1 {
    #[default]
    Compiled,
    SupervisorSelected,
}

impl FromStr for RuntimeModuleProfileV1 {
    type Err = AgentdError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "compiled" => Ok(Self::Compiled),
            "supervisor-selected" => Ok(Self::SupervisorSelected),
            _ => Err(AgentdError::Invalid(
                "runtime module profile must be compiled or supervisor-selected".to_string(),
            )),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Response {
    schema_version: u32,
    request_id: u64,
    payload: Payload,
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
enum Payload {
    RuntimeModuleSelection { selection: RuntimeModuleSelectionV1 },
}

pub(crate) async fn observe_compiled_selection(
    identity: &AgentdIdentity,
    module_id: &str,
) -> Result<RuntimeModuleSelectionV1, AgentdError> {
    let root = HeptaFleetRoot::parse(identity.fleet_root.clone())
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let path = root.layout().supervisor_socket().to_path_buf();
    let request = serde_json::to_vec(&serde_json::json!({
        "schema_version": SUPERVISORD_CONTROL_SCHEMA_VERSION,
        "request_id": 1,
        "method": {"type": "runtime_module_selection", "module_id": module_id},
    }))?;
    let observation = timeout(Duration::from_secs(2), async {
        let mut stream = UnixStream::connect(&path).await?;
        codex_uds::ensure_current_user_peer(&stream)?;
        stream.write_all(&request).await?;
        stream.write_all(b"\n").await?;
        stream.shutdown().await?;
        let mut reader = BufReader::new(stream).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
        let mut bytes = Vec::new();
        let count = reader.read_until(b'\n', &mut bytes).await?;
        if count == 0
            || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            || !bytes.ends_with(b"\n")
        {
            return Err(AgentdError::Protocol(
                "invalid Supervisor selection frame".to_string(),
            ));
        }
        let response: Response = serde_json::from_slice(&bytes)?;
        if response.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION || response.request_id != 1
        {
            return Err(AgentdError::Protocol(
                "Supervisor selection response identity mismatch".to_string(),
            ));
        }
        let Payload::RuntimeModuleSelection { selection } = response.payload;
        selection.validate().map_err(AgentdError::Protocol)?;
        if selection.module_id != module_id {
            return Err(AgentdError::Protocol(
                "Supervisor selected a different module".to_string(),
            ));
        }
        Ok(selection)
    })
    .await
    .map_err(|_| AgentdError::Protocol("Supervisor selection timed out".to_string()))??;
    // A digest supplied by the caller is not an executable identity. Observe
    // this process image and the existing canonical module definition locally.
    if let Some(binding) = &observation.selected {
        let catalog = RuntimeModuleCatalogV1::canonical()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let definition = catalog.module(module_id).ok_or_else(|| {
            AgentdError::Invalid("selected module has no compiled definition".to_string())
        })?;
        let module =
            StableId::new(module_id).map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let manifest = definition
            .manifest_digest
            .parse::<Digest32>()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        let actual =
            RuntimeExecutableIdentity::observe_current()?.implementation_digest(&module, manifest);
        let dependencies: std::collections::BTreeSet<_> = binding.dependencies.iter().collect();
        let expected_dependencies: std::collections::BTreeSet<_> =
            definition.dependencies.iter().collect();
        let domains: std::collections::BTreeSet<_> = binding.authoritative_domains.iter().collect();
        let expected_domains: std::collections::BTreeSet<_> =
            definition.authoritative_domains.iter().collect();
        if definition.owner != binding.owner_id
            || crate::runtime_module_state::parse(&definition.state)?
                != crate::runtime_module_state::parse(&binding.state_class)?
            || expected_dependencies != dependencies
            || expected_domains != domains
            || !binding.input_ports.is_empty()
            || !binding.output_ports.is_empty()
            || !binding.effect_scope.is_empty()
            || actual.to_string() != binding.implementation_digest.as_str()
        {
            return Err(AgentdError::GenerationFenced(
                "Supervisor selection does not bind this compiled module implementation"
                    .to_string(),
            ));
        }
    }
    Ok(observation)
}

#[cfg(all(test, unix))]
#[path = "module_selection_tests.rs"]
mod tests;
