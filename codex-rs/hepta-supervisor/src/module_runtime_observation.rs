//! Read the serving topology from its existing durable owner, never a sidecar.
use codex_hepta_agent_protocol::RuntimeModuleBindingV1;
use codex_hepta_agent_protocol::RuntimeModuleSelectionV1;
use codex_hepta_agent_protocol::validate_runtime_module_id;
use codex_hepta_contracts::Sha256Digest;

use crate::DurableRuntimeModuleSupervisorErrorV1;
use crate::DurableRuntimeModuleSupervisorV1;

impl DurableRuntimeModuleSupervisorV1 {
    /// Observe one serving module. Pending candidates and retired generations
    /// cannot appear as selected. This method performs no mutation or recovery.
    pub fn module_selection(
        &self,
        module_id: &str,
    ) -> Result<RuntimeModuleSelectionV1, DurableRuntimeModuleSupervisorErrorV1> {
        validate_runtime_module_id(module_id)
            .map_err(DurableRuntimeModuleSupervisorErrorV1::Invalid)?;
        let topology = self.topology()?;
        let identity = codex_hepta_types::StableId::new(module_id)
            .map_err(|error| DurableRuntimeModuleSupervisorErrorV1::Invalid(error.to_string()))?;
        if self
            .supervisor
            .selected_module_phase(&identity)?
            .is_some_and(|phase| {
                phase != codex_hepta_control_plane::RuntimeModuleLifecycleV1::Active
            })
        {
            return Err(DurableRuntimeModuleSupervisorErrorV1::Invalid(
                "selected module has an unresolved non-serving owner reservation".to_string(),
            ));
        }
        let digest = |value: codex_hepta_types::Digest32| {
            Sha256Digest::parse(value.to_string())
                .map_err(DurableRuntimeModuleSupervisorErrorV1::Invalid)
        };
        let selected = topology
            .active
            .iter()
            .find(|module| module.module_id.as_str() == module_id)
            .map(|module| {
                Ok::<_, DurableRuntimeModuleSupervisorErrorV1>(RuntimeModuleBindingV1 {
                    owner_id: module.owner_id.as_str().to_string(),
                    generation: module.generation.get(),
                    implementation_digest: digest(module.implementation_digest)?,
                    candidate_artifact_digest: digest(module.candidate_artifact_digest)?,
                    state_class: match module.state_class {
                        codex_hepta_control_plane::RuntimeModuleStateClassV1::Stateless => {
                            "stateless"
                        }
                        codex_hepta_control_plane::RuntimeModuleStateClassV1::Stateful => {
                            "stateful"
                        }
                        codex_hepta_control_plane::RuntimeModuleStateClassV1::ExternalStateful => {
                            "stateful_external"
                        }
                    }
                    .to_string(),
                    dependencies: module
                        .dependencies
                        .iter()
                        .map(ToString::to_string)
                        .collect(),
                    authoritative_domains: module
                        .authoritative_domains
                        .iter()
                        .map(ToString::to_string)
                        .collect(),
                    input_ports: module.input_ports.iter().map(ToString::to_string).collect(),
                    output_ports: module
                        .output_ports
                        .iter()
                        .map(ToString::to_string)
                        .collect(),
                    effect_scope: module
                        .effect_scope
                        .iter()
                        .map(ToString::to_string)
                        .collect(),
                })
            })
            .transpose()?;
        let observation = RuntimeModuleSelectionV1 {
            module_id: module_id.to_string(),
            topology_digest: digest(topology.digest)?,
            selected,
        };
        observation
            .validate()
            .map_err(DurableRuntimeModuleSupervisorErrorV1::Invalid)?;
        Ok(observation)
    }
}

#[cfg(test)]
#[path = "module_runtime_observation_tests.rs"]
mod tests;
