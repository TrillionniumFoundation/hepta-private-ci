use std::fmt;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use serde::de::Error as _;

use crate::H7H89ProductionGrant;
use crate::ProductionMutationReceipt;

pub const SUPERVISORD_CONTROL_SCHEMA_VERSION: u32 = 2;
pub const MAX_SUPERVISORD_CONTROL_FRAME_BYTES: u64 = 65_536;
pub const MAX_SUPERVISORD_ROSTER: u16 = 256;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub method: SupervisordMethod,
}

impl SupervisordRequest {
    pub fn new(request_id: u64, method: SupervisordMethod) -> Self {
        Self {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id,
            method,
        }
    }

    pub fn validate(&self) -> Result<(), SupervisordRequestValidationError> {
        if self.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION {
            return Err(SupervisordRequestValidationError::UnsupportedSchema);
        }
        if self.request_id == 0 {
            return Err(SupervisordRequestValidationError::InvalidRequest);
        }
        match &self.method {
            SupervisordMethod::Health | SupervisordMethod::Snapshot { .. } => Ok(()),
            SupervisordMethod::Roster { limit } => {
                if (1..=MAX_SUPERVISORD_ROSTER).contains(limit) {
                    Ok(())
                } else {
                    Err(SupervisordRequestValidationError::InvalidRequest)
                }
            }
            SupervisordMethod::Start { fence, .. }
            | SupervisordMethod::Drain { fence }
            | SupervisordMethod::Stop { fence }
            | SupervisordMethod::Kill { fence }
            | SupervisordMethod::Restart { fence }
            | SupervisordMethod::Upgrade { fence, .. }
            | SupervisordMethod::Rollback { fence }
            | SupervisordMethod::SignedUpgrade { fence, .. }
            | SupervisordMethod::SignedRollback { fence, .. } => fence.validate(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SupervisordRequestValidationError {
    UnsupportedSchema,
    InvalidRequest,
}

/// The owner-local administrator socket retains lifecycle controls. Robrix
/// uses the separate read-only projection in `robrix_protocol`, which exposes
/// only health, roster, and snapshot requests. Every administrator mutation
/// carries the same atomic CAS fence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum SupervisordMethod {
    Health,
    Roster {
        limit: u16,
    },
    Snapshot {
        agent_id: AgentId,
    },
    Start {
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    },
    Drain {
        fence: SupervisordControlFence,
    },
    Stop {
        fence: SupervisordControlFence,
    },
    Kill {
        fence: SupervisordControlFence,
    },
    Restart {
        fence: SupervisordControlFence,
    },
    Upgrade {
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    },
    Rollback {
        fence: SupervisordControlFence,
    },
    /// A production mutation must carry both the H7 envelope and an
    /// independent authority grant.  The daemon's verifier is injected out
    /// of band; no request can choose its own trust root.
    SignedUpgrade {
        fence: SupervisordControlFence,
        grant: H7H89ProductionGrant,
        h7_envelope: H7SignedArtifactEnvelope,
    },
    SignedRollback {
        fence: SupervisordControlFence,
        grant: H7H89ProductionGrant,
        h7_envelope: H7SignedArtifactEnvelope,
    },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SupervisordMutation {
    Start,
    Drain,
    Stop,
    Kill,
    Restart,
    Upgrade,
    Rollback,
}

impl fmt::Display for SupervisordMutation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Start => "start",
            Self::Drain => "drain",
            Self::Stop => "stop",
            Self::Kill => "kill",
            Self::Restart => "restart",
            Self::Upgrade => "upgrade",
            Self::Rollback => "rollback",
        })
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SupervisorEpoch(String);

impl SupervisorEpoch {
    pub fn new() -> Self {
        Self(uuid::Uuid::new_v4().hyphenated().to_string())
    }

    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        let parsed = uuid::Uuid::parse_str(&value)
            .map_err(|_| "supervisor epoch must be a canonical UUID".to_string())?;
        if parsed.is_nil() || parsed.hyphenated().to_string() != value {
            return Err("supervisor epoch must be a canonical non-zero lowercase UUID".to_string());
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl Default for SupervisorEpoch {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for SupervisorEpoch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl Serialize for SupervisorEpoch {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for SupervisorEpoch {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ControlStateDigest(String);

impl ControlStateDigest {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err("control state digest must be lowercase SHA-256 hex".to_string());
        }
        Ok(Self(value))
    }

    #[cfg(any(unix, test))]
    pub(crate) fn from_bytes(bytes: [u8; 32]) -> Self {
        Self(hex_lower(&bytes))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    #[cfg(any(unix, test))]
    pub(crate) fn decode(&self) -> [u8; 32] {
        let mut bytes = [0_u8; 32];
        for (index, pair) in self.0.as_bytes().chunks_exact(2).enumerate() {
            bytes[index] = (hex_value(pair[0]) << 4) | hex_value(pair[1]);
        }
        bytes
    }
}

impl fmt::Display for ControlStateDigest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl Serialize for ControlStateDigest {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for ControlStateDigest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordControlFence {
    pub agent_id: AgentId,
    pub supervisor_epoch: SupervisorEpoch,
    pub lifecycle: AgentLifecycle,
    pub lifecycle_generation: u64,
    pub spawn_generation: Option<u64>,
    pub runtime_generation: Option<u64>,
    pub current_release: Option<ReleaseId>,
    pub previous_release: Option<ReleaseId>,
    pub release_change_pending: bool,
    pub state_digest: ControlStateDigest,
}

impl SupervisordControlFence {
    pub fn validate(&self) -> Result<(), SupervisordRequestValidationError> {
        if self.spawn_generation.is_some() != self.runtime_generation.is_some()
            || self
                .spawn_generation
                .zip(self.runtime_generation)
                .is_some_and(|(spawn, runtime)| spawn > runtime)
            || (matches!(
                self.lifecycle,
                AgentLifecycle::Starting | AgentLifecycle::Running | AgentLifecycle::Draining
            ) && self.runtime_generation.is_none())
            || (self.lifecycle == AgentLifecycle::Stopped && self.runtime_generation.is_some())
            || (self.current_release.is_some() && self.current_release == self.previous_release)
            || (self.release_change_pending && self.current_release.is_none())
        {
            return Err(SupervisordRequestValidationError::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordResponse {
    pub schema_version: u32,
    pub request_id: u64,
    pub payload: SupervisordPayload,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum SupervisordPayload {
    Health(SupervisordHealth),
    Roster {
        agents: Vec<SupervisordAgentStatus>,
    },
    Agent(SupervisordAgentStatus),
    MutationAccepted {
        operation: SupervisordMutation,
        accepted_state_digest: ControlStateDigest,
        agent: SupervisordAgentStatus,
        /// Present only for an externally signed lifecycle mutation.  The
        /// ordinary local-control mutations deliberately carry no authority
        /// receipt.  When present, the grant digest is the durable
        /// `supervisor-signed-intent.json` witness for this operation.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        production_receipt: Option<ProductionMutationReceipt>,
    },
    Error {
        code: String,
        message: String,
        actual: Option<SupervisordAgentStatus>,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordHealth {
    pub ready: bool,
    pub supervisor_epoch: SupervisorEpoch,
    pub process_id: u32,
    pub registered_agents: u16,
    pub observed_faults: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordAgentStatus {
    pub agent_id: AgentId,
    pub lifecycle: AgentLifecycle,
    pub lifecycle_generation: u64,
    pub active: bool,
    pub healthy: bool,
    pub process_id: Option<u64>,
    pub spawn_generation: Option<u64>,
    pub runtime_generation: Option<u64>,
    pub current_release: Option<ReleaseId>,
    pub previous_release: Option<ReleaseId>,
    pub release_change_pending: bool,
    pub control_fence: SupervisordControlFence,
    pub matrix: SupervisordMatrixStatus,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SupervisordMutationAccepted {
    pub operation: SupervisordMutation,
    pub accepted_state_digest: ControlStateDigest,
    pub agent: SupervisordAgentStatus,
    /// Signed mutation authority receipt, if this response came from the
    /// externally signed upgrade/rollback RPC.
    pub production_receipt: Option<ProductionMutationReceipt>,
}

#[cfg(any(unix, test))]
fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

#[cfg(any(unix, test))]
fn hex_value(byte: u8) -> u8 {
    match byte {
        b'0'..=b'9' => byte - b'0',
        b'a'..=b'f' => byte - b'a' + 10,
        _ => unreachable!("ControlStateDigest validates lowercase hex"),
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SupervisordMatrixStatus {
    pub configured: bool,
    pub active: bool,
    pub healthy: bool,
    pub degraded: bool,
    pub process_id: Option<u64>,
    pub attached_agent_generation: Option<u64>,
    pub binding_revision: Option<u64>,
    pub restart_attempt: u32,
    pub last_error: Option<String>,
}

#[cfg(test)]
mod tests {
    use crate::H7H89ProductionTransition;
    use crate::ProductionMutationStatus;
    use codex_hepta_contracts::Sha256Digest;
    use pretty_assertions::assert_eq;
    use serde_json::json;

    use super::*;

    const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
    const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
    const DIGEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    fn fence() -> SupervisordControlFence {
        SupervisordControlFence {
            agent_id: AgentId::parse(AGENT_ID).expect("fixed agent id"),
            supervisor_epoch: SupervisorEpoch::parse(EPOCH).expect("fixed epoch"),
            lifecycle: AgentLifecycle::Running,
            lifecycle_generation: 7,
            spawn_generation: Some(5),
            runtime_generation: Some(7),
            current_release: Some(ReleaseId::parse("agentd-v1").expect("fixed release")),
            previous_release: None,
            release_change_pending: false,
            state_digest: ControlStateDigest::parse(DIGEST).expect("fixed digest"),
        }
    }

    #[test]
    fn exact_v2_mutation_request_json_is_frozen() {
        let request = SupervisordRequest::new(41, SupervisordMethod::Restart { fence: fence() });
        let encoded = serde_json::to_string(&request).expect("serialize request");
        assert_eq!(
            encoded,
            format!(
                r#"{{"schema_version":2,"request_id":41,"method":{{"type":"restart","fence":{{"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","supervisor_epoch":"018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12","lifecycle":"running","lifecycle_generation":7,"spawn_generation":5,"runtime_generation":7,"current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"state_digest":"{DIGEST}"}}}}}}"#,
            )
        );
        assert_eq!(
            serde_json::from_str::<SupervisordRequest>(&encoded).expect("parse request"),
            request
        );
    }

    #[test]
    fn exact_v2_upgrade_and_success_payload_json_are_frozen() {
        let request = SupervisordRequest::new(
            42,
            SupervisordMethod::Upgrade {
                fence: fence(),
                release_id: ReleaseId::parse("agentd-v2").expect("fixed release"),
            },
        );
        assert_eq!(
            serde_json::to_value(request).expect("serialize request"),
            json!({
                "schema_version": 2,
                "request_id": 42,
                "method": {
                    "type": "upgrade",
                    "fence": serde_json::to_value(fence()).expect("serialize fence"),
                    "release_id": "agentd-v2"
                }
            })
        );

        let status = status();
        let response = SupervisordResponse {
            schema_version: 2,
            request_id: 43,
            payload: SupervisordPayload::MutationAccepted {
                operation: SupervisordMutation::Restart,
                accepted_state_digest: ControlStateDigest::parse(DIGEST).expect("fixed digest"),
                agent: status,
                production_receipt: None,
            },
        };
        let encoded = serde_json::to_string(&response).expect("serialize response");
        assert_eq!(
            encoded,
            format!(
                r#"{{"schema_version":2,"request_id":43,"payload":{{"type":"mutation_accepted","operation":"restart","accepted_state_digest":"{DIGEST}","agent":{{"agent_id":"{AGENT_ID}","lifecycle":"running","lifecycle_generation":7,"active":true,"healthy":true,"process_id":1234,"spawn_generation":5,"runtime_generation":7,"current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"control_fence":{{"agent_id":"{AGENT_ID}","supervisor_epoch":"{EPOCH}","lifecycle":"running","lifecycle_generation":7,"spawn_generation":5,"runtime_generation":7,"current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"state_digest":"{DIGEST}"}},"matrix":{{"configured":true,"active":true,"healthy":true,"degraded":false,"process_id":4321,"attached_agent_generation":5,"binding_revision":11,"restart_attempt":0,"last_error":null}}}}}}}}"#
            )
        );
        assert!(!encoded.contains("program"));
        assert!(!encoded.contains("args"));
        assert!(!encoded.contains("driver"));
    }

    #[test]
    fn signed_mutation_response_round_trips_its_bound_production_receipt() {
        let receipt = ProductionMutationReceipt {
            grant_sha256: Sha256Digest::for_bytes(b"grant"),
            agent_id: AGENT_ID.to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            source_release: "agentd-v1".to_string(),
            target_release: "agentd-v2".to_string(),
            control_revision: 8,
            status: ProductionMutationStatus::Queued,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
        };
        let response = SupervisordResponse {
            schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
            request_id: 45,
            payload: SupervisordPayload::MutationAccepted {
                operation: SupervisordMutation::Upgrade,
                accepted_state_digest: ControlStateDigest::parse(DIGEST).expect("digest"),
                agent: status(),
                production_receipt: Some(receipt.clone()),
            },
        };
        let encoded = serde_json::to_vec(&response).expect("serialize signed response");
        let decoded: SupervisordResponse =
            serde_json::from_slice(&encoded).expect("deserialize signed response");
        assert_eq!(decoded, response);
        let json = serde_json::from_slice::<serde_json::Value>(&encoded).expect("response JSON");
        assert_eq!(
            json["payload"]["production_receipt"]["grant_sha256"],
            serde_json::Value::String(receipt.grant_sha256.as_str().to_owned())
        );
        assert_eq!(
            json["payload"]["production_receipt"]["status"],
            serde_json::Value::String("queued".to_string())
        );
        for field in [
            "production_authority",
            "external_effects",
            "operator_acceptance",
            "promotion",
        ] {
            assert_eq!(json["payload"]["production_receipt"][field], true);
        }
    }

    #[test]
    fn exact_stale_error_has_actual_and_no_internal_details() {
        let response = SupervisordResponse {
            schema_version: 2,
            request_id: 44,
            payload: SupervisordPayload::Error {
                code: "stale_control_fence".to_string(),
                message: "selected Agent changed; refresh before retry".to_string(),
                actual: Some(status()),
            },
        };
        let encoded = serde_json::to_string(&response).expect("serialize error");
        assert_eq!(
            encoded,
            format!(
                r#"{{"schema_version":2,"request_id":44,"payload":{{"type":"error","code":"stale_control_fence","message":"selected Agent changed; refresh before retry","actual":{{"agent_id":"{AGENT_ID}","lifecycle":"running","lifecycle_generation":7,"active":true,"healthy":true,"process_id":1234,"spawn_generation":5,"runtime_generation":7,"current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"control_fence":{{"agent_id":"{AGENT_ID}","supervisor_epoch":"{EPOCH}","lifecycle":"running","lifecycle_generation":7,"spawn_generation":5,"runtime_generation":7,"current_release":"agentd-v1","previous_release":null,"release_change_pending":false,"state_digest":"{DIGEST}"}},"matrix":{{"configured":true,"active":true,"healthy":true,"degraded":false,"process_id":4321,"attached_agent_generation":5,"binding_revision":11,"restart_attempt":0,"last_error":null}}}}}}}}"#
            )
        );
        assert!(!encoded.contains("program"));
        assert!(!encoded.contains("args"));
        assert!(!encoded.contains("driver"));
    }

    #[test]
    fn epoch_and_digest_parsers_are_exact() {
        assert!(SupervisorEpoch::parse(EPOCH).is_ok());
        assert!(SupervisorEpoch::parse(EPOCH.to_uppercase()).is_err());
        assert!(SupervisorEpoch::parse("00000000-0000-0000-0000-000000000000").is_err());
        assert!(ControlStateDigest::parse(DIGEST).is_ok());
        assert!(ControlStateDigest::parse(DIGEST.to_uppercase()).is_err());
        assert!(ControlStateDigest::parse("aa").is_err());
    }

    #[test]
    fn request_validation_rejects_schema_identity_and_incoherent_fences() {
        let mut request = SupervisordRequest::new(1, SupervisordMethod::Drain { fence: fence() });
        assert_eq!(request.validate(), Ok(()));
        request.schema_version = 1;
        assert_eq!(
            request.validate(),
            Err(SupervisordRequestValidationError::UnsupportedSchema)
        );
        request.schema_version = 2;
        request.request_id = 0;
        assert_eq!(
            request.validate(),
            Err(SupervisordRequestValidationError::InvalidRequest)
        );

        let mut incoherent = fence();
        incoherent.runtime_generation = None;
        assert_eq!(
            SupervisordRequest::new(2, SupervisordMethod::Drain { fence: incoherent }).validate(),
            Err(SupervisordRequestValidationError::InvalidRequest)
        );
    }

    #[test]
    fn strict_wire_rejects_unknown_fields_and_bad_typed_identities() {
        let valid = serde_json::to_value(SupervisordRequest::new(
            7,
            SupervisordMethod::Restart { fence: fence() },
        ))
        .expect("serialize request");

        let mut unknown = valid.clone();
        unknown
            .as_object_mut()
            .expect("request object")
            .insert("program".to_string(), json!("/tmp/agentd"));
        assert!(serde_json::from_value::<SupervisordRequest>(unknown).is_err());

        for (field, value) in [
            ("state_digest", json!("AA")),
            ("agent_id", json!("../../agent")),
            ("supervisor_epoch", json!("NOT-A-UUID")),
        ] {
            let mut bad = valid.clone();
            bad["method"]["fence"][field] = value;
            assert!(
                serde_json::from_value::<SupervisordRequest>(bad).is_err(),
                "accepted invalid field {field}"
            );
        }

        let mut bad_release = serde_json::to_value(SupervisordRequest::new(
            8,
            SupervisordMethod::Upgrade {
                fence: fence(),
                release_id: ReleaseId::parse("agentd-v2").expect("fixed release"),
            },
        ))
        .expect("serialize upgrade");
        bad_release["method"]["release_id"] = json!("../../release");
        assert!(serde_json::from_value::<SupervisordRequest>(bad_release).is_err());
    }

    fn status() -> SupervisordAgentStatus {
        SupervisordAgentStatus {
            agent_id: fence().agent_id,
            lifecycle: AgentLifecycle::Running,
            lifecycle_generation: 7,
            active: true,
            healthy: true,
            process_id: Some(1234),
            spawn_generation: Some(5),
            runtime_generation: Some(7),
            current_release: Some(ReleaseId::parse("agentd-v1").expect("fixed release")),
            previous_release: None,
            release_change_pending: false,
            control_fence: fence(),
            matrix: SupervisordMatrixStatus {
                configured: true,
                active: true,
                healthy: true,
                degraded: false,
                process_id: Some(4321),
                attached_agent_generation: Some(5),
                binding_revision: Some(11),
                restart_attempt: 0,
                last_error: None,
            },
        }
    }
}
