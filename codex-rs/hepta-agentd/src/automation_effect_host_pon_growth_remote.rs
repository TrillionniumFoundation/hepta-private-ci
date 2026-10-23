//! Explicit protected-TCP transport for the existing PNP2 effect state machine.
//! A pinned CLI verifies the signed exchange. Its stdout wrapper is local
//! evidence of that verification, not an independently transferable certificate.

use super::lower_hex_32;
use super::pon_growth;
use super::pon_process;
use serde::Deserialize;
use serde_json::Value;
use std::net::SocketAddr;
use std::path::Path;
use std::process::Command;

#[path = "automation_effect_host_pon_growth_remote_config.rs"]
mod config;
pub(super) use config::HostFileV5;
pub(super) use config::SCHEMA_VERSION;
pub(super) use config::open;

pub(super) const TRANSPORT_PROFILE: &str = "public-protected-growth-development-v1";
const WRAPPER_SCHEMA: &str = "pon-native-growth-remote-client-result-v1";

#[derive(Clone, Debug)]
pub(super) struct Transport {
    pub(super) context: pon_growth::Context,
    pub(super) peer: SocketAddr,
    pub(super) server_public: String,
    pub(super) resource_profile: String,
    pub(super) admission_bits: u8,
    pub(super) admission_ttl_ms: u64,
    pub(super) credential: pon_process::CredentialPin,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct VerifiedClientResult {
    schema: String,
    transport_profile: String,
    resource_profile: String,
    server_public: String,
    network: String,
    parameters: String,
    genesis: String,
    operation: String,
    verified_signed_response: bool,
    response: PublicReply,
    production_activation: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PublicReply {
    ok: bool,
    value: Value,
    solve_trials: u64,
    solve_elapsed_ns: u64,
    body_bytes_sent: u64,
    public_network_ready: bool,
    identity_authority: bool,
}

impl Transport {
    pub(super) fn command(&self, operation: &str, executable: &Path, genesis_time: u64) -> Command {
        let mut command = Command::new(executable);
        command
            .arg(if operation == "submit" {
                "push"
            } else {
                operation
            })
            .arg("--development")
            .arg("--admission-profile")
            .arg(TRANSPORT_PROFILE)
            .arg("--growth-namespace")
            .arg(&self.context.namespace)
            .arg("--genesis-time")
            .arg(genesis_time.to_string())
            .arg("--peer")
            .arg(self.peer.to_string())
            .arg("--server-public")
            .arg(&self.server_public)
            .arg("--admission-bits")
            .arg(self.admission_bits.to_string())
            .arg("--admission-ttl-ms")
            .arg(self.admission_ttl_ms.to_string())
            .arg("--resource-profile-sha256")
            .arg(&self.resource_profile)
            .arg("--packet-stdin");
        // Only the process owner appends the verified private snapshot path
        // and the remaining original deadline. No store or recovery flags.
        command
    }

    pub(super) fn normalize(&self, operation: &str, value: Value) -> Option<Value> {
        let expected_operation = match operation {
            "submit" => "growth_submit_v1",
            "packet-status" => "growth_packet_status_v1",
            _ => return None,
        };
        let response: VerifiedClientResult = serde_json::from_value(value).ok()?;
        if response.schema != WRAPPER_SCHEMA
            || response.transport_profile != TRANSPORT_PROFILE
            || response.resource_profile != self.resource_profile
            || response.server_public != self.server_public
            || response.network != self.context.network
            || response.parameters != self.context.parameters
            || response.genesis != self.context.genesis
            || response.operation != expected_operation
            || !response.verified_signed_response
            || response.production_activation
            || !response.response.ok
            || response.response.public_network_ready
            || response.response.identity_authority
        {
            return None;
        }
        // Deserialize the bounded numeric transport accounting as well; it
        // does not confer any confirmation, work-credit, or execution right.
        let _transport_accounting = (
            response.response.solve_trials,
            response.response.solve_elapsed_ns,
            response.response.body_bytes_sent,
        );
        let value = response.response.value;
        let schema = if operation == "submit" {
            "pon-native-growth-submit-v1"
        } else {
            pon_growth::OBSERVATION_SCHEMA
        };
        if value.get("schema")?.as_str()? != schema
            || value.get("packet_profile")?.as_str()? != "PNP2"
            || value.get("state_profile")?.as_str()? != "permanent-account-growth-native-v2"
            || value.get("network")?.as_str()? != self.context.network
            || value.get("parameters")?.as_str()? != self.context.parameters
            || value.get("genesis")?.as_str()? != self.context.genesis
        {
            return None;
        }
        if operation == "submit"
            && (!value.get("admitted")?.as_bool()?
                || !lower_hex_32(value.get("block")?.as_str()?)
                || !lower_hex_32(value.get("active")?.as_str()?)
                || value.get("generation")?.as_u64().is_none()
                || value.get("physical_execution")?.as_bool()?
                || value.get("production_activation")?.as_bool()?)
        {
            return None;
        }
        // Internal shared-adapter representation only. The original exact
        // growth schema, context, membership budget and authority flags remain
        // mandatory in Context::parse_observation; no wire schema is relabeled.
        Some(serde_json::json!({"result": value}))
    }
}

#[cfg(test)]
#[path = "automation_effect_host_pon_growth_remote_tests.rs"]
mod tests;
