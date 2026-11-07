//! Command profile selection inside the existing PoN adapter.
//! Profiles supply pinned arguments, never execution or account authority.
use super::AgentdError;
use super::Sha256Digest;
use super::read_protected_file;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;

const APPLICATION_PROFILE: &str = "pon-native-pq-application-v6";

#[derive(Clone, Debug)]
pub(super) enum Profile {
    NativePq(Box<NativePqConfig>),
    // Only historical unit-test fixtures can select the classical CLI profile.
    #[cfg(test)]
    Development {
        state_backend: String,
        genesis_time: u64,
        evaluation_policy: String,
        task_profile: String,
        model_profile: String,
    },
}

impl Profile {
    pub(super) fn append_arguments(&self, command: &mut Command) {
        match self {
            Self::NativePq(config) => config.append_arguments(command),
            #[cfg(test)]
            Self::Development {
                state_backend,
                genesis_time,
                evaluation_policy,
                task_profile,
                model_profile,
            } => {
                command
                    .arg("--state-backend")
                    .arg(state_backend)
                    .arg("--genesis-time")
                    .arg(genesis_time.to_string())
                    .arg("--evaluation-policy")
                    .arg(evaluation_policy)
                    .arg("--task-profile")
                    .arg(task_profile)
                    .arg("--model-profile")
                    .arg(model_profile);
            }
        }
    }
}

impl Profile {
    pub(super) fn validate_selected_configuration(&self) -> Result<(), AgentdError> {
        match self {
            #[cfg(test)]
            Self::Development { .. } => Ok(()),
            Self::NativePq(config) => config.validate(),
        }
    }

    pub(super) fn readback_matches(&self, stdout: &[u8], packet: &[u8]) -> bool {
        match self {
            #[cfg(test)]
            Self::Development { .. } => true,
            Self::NativePq(config) => config.readback_matches(stdout, packet),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "profile", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum NativeOwner {
    NetworkV2 {},
    WitnessV4 { writer_key: PathBuf },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct NativePqConfig {
    pub(super) configuration: PathBuf,
    pub(super) configuration_sha256: String,
    pub(super) application_profile: String,
    pub(super) network: String,
    pub(super) parameters: String,
    pub(super) genesis: String,
    pub(super) network_policy: String,
    pub(super) owner: NativeOwner,
}

impl NativePqConfig {
    fn owner_profile(&self) -> &'static str {
        match &self.owner {
            NativeOwner::NetworkV2 {} => "network_v2",
            NativeOwner::WitnessV4 { .. } => "witness_v4",
        }
    }

    pub(super) fn validate(&self) -> Result<(), AgentdError> {
        if !cfg!(target_os = "linux") || self.application_profile != APPLICATION_PROFILE {
            return Err(invalid("explicit Linux NPQ6 application profile required"));
        }
        for digest in [
            &self.configuration_sha256,
            &self.network,
            &self.parameters,
            &self.genesis,
            &self.network_policy,
        ] {
            Sha256Digest::parse(digest.clone()).map_err(invalid)?;
        }
        if !self.configuration.is_absolute()
            || self.configuration.canonicalize()? != self.configuration
        {
            return Err(invalid("NPQ6 configuration path must be canonical"));
        }
        let bytes = read_protected_file(
            &self.configuration,
            262_144,
            "pinned NPQ6 application configuration",
        )?;
        if Sha256Digest::for_bytes(&bytes).as_str() != self.configuration_sha256 {
            return Err(invalid("NPQ6 configuration digest mismatch"));
        }
        let value: Value = serde_json::from_slice(&bytes)?;
        for (name, expected) in [
            ("schema", "native-pq-application-local-config-v1"),
            ("network", self.network.as_str()),
            ("parameters", self.parameters.as_str()),
            ("genesis", self.genesis.as_str()),
            ("network_policy", self.network_policy.as_str()),
            ("owner_profile", self.owner_profile()),
        ] {
            if value.get(name).and_then(Value::as_str) != Some(expected) {
                return Err(invalid(
                    "NPQ6 signed provider/configuration context mismatch",
                ));
            }
        }
        if let NativeOwner::WitnessV4 { writer_key } = &self.owner
            && (!writer_key.is_absolute() || writer_key.canonicalize()? != *writer_key)
        {
            return Err(invalid("NPQ6 witness key path must be canonical"));
        }
        // The pinned Chain entry still parses its complete strict DTO and
        // reconstructs Settings/role roots. This precheck grants no authority.
        Ok(())
    }

    fn append_arguments(&self, command: &mut Command) {
        command
            .arg("--pq-application-config")
            .arg(&self.configuration)
            .arg("--pq-application-config-sha256")
            .arg(&self.configuration_sha256);
        if let NativeOwner::WitnessV4 { writer_key } = &self.owner {
            command.arg("--witness-writer-key").arg(writer_key);
        }
    }

    fn readback_matches(&self, stdout: &[u8], packet: &[u8]) -> bool {
        // Decode the original stdout directly so duplicate or unknown binding
        // fields cannot be hidden by first converting them into a JSON Value.
        let Ok(observation) = serde_json::from_slice::<Observation>(stdout) else {
            return false;
        };
        let actual = observation.pq_application_context;
        actual.schema == "native-pq-application-local-observation-v1"
            && actual.configuration_sha256 == self.configuration_sha256
            && actual.profile == self.application_profile
            && actual.network == self.network
            && actual.parameters == self.parameters
            && actual.genesis == self.genesis
            && actual.network_policy == self.network_policy
            && actual.owner_profile == self.owner_profile()
            && actual.packet_sha256 == Sha256Digest::for_bytes(packet).as_str()
            && Sha256Digest::parse(actual.block.clone()).is_ok()
            && observation.result.get("block").and_then(Value::as_str)
                == Some(actual.block.as_str())
            && observation.clock_scope == "local-wall"
            && observation.local_owner_only
            && !observation.whole_node_rollback_protection
            && !observation.production_activation
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Observation {
    result: Value,
    pq_application_context: Readback,
    clock_scope: String,
    local_owner_only: bool,
    whole_node_rollback_protection: bool,
    production_activation: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Readback {
    schema: String,
    configuration_sha256: String,
    profile: String,
    network: String,
    parameters: String,
    genesis: String,
    network_policy: String,
    owner_profile: String,
    packet_sha256: String,
    block: String,
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(format!("PoN NPQ6 provider binding: {error}"))
}

#[cfg(all(test, target_os = "linux"))]
#[path = "automation_effect_host_pon_profile_tests.rs"]
mod tests;
