//! Bounded local control protocol shared by one Hepta agent daemon and its supervisor.

#![forbid(unsafe_code)]

use std::path::PathBuf;

use codex_hepta_automation::AutomationTask;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_CONTROL_SCHEMA_VERSION: u32 = 2;
/// Version for the transport-only host turn authority witness.  This type is
/// deliberately not an authority grant and is not consumed by the Agentd
/// runtime yet; it gives a future host/supervisor seam one strict wire shape.
pub const HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION: u32 = 1;
pub const MAX_CONTROL_FRAME_BYTES: u64 = 65_536;
pub const MAX_EVENT_BATCH: u16 = 256;
pub const MAX_FEDERATION_CONTROL_LIST: u16 = 128;
const FEDERATION_CAPABILITY_ID_PREFIX: &str = "federation:v1:";

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct MemoryFederationCapabilityId(String);

impl MemoryFederationCapabilityId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        let digest = value
            .strip_prefix(FEDERATION_CAPABILITY_ID_PREFIX)
            .ok_or_else(|| "invalid memory federation capability id".to_string())?;
        Sha256Digest::parse(digest.to_string())?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for MemoryFederationCapabilityId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryFederationScopeKind {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryFederationCapabilityState {
    Granted,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryFederationCapabilitySnapshot {
    pub capability_id: MemoryFederationCapabilityId,
    pub owner_agent_id: AgentId,
    pub consumer_agent_id: AgentId,
    pub owner_scope: MemoryFederationScopeKind,
    pub generation: u64,
    pub revision: u64,
    pub effective_at_unix_seconds: i64,
    pub expires_at_unix_seconds: i64,
    pub state: MemoryFederationCapabilityState,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub spawn_generation: u64,
    pub method: AgentdMethod,
}

impl AgentdRequest {
    pub fn health(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Health,
        }
    }

    pub fn lifecycle(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Lifecycle,
        }
    }

    pub fn session_ingress(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::SessionIngress,
        }
    }

    pub fn events(request_id: u64, spawn_generation: u64, after_cursor: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Events {
                after_cursor,
                limit,
            },
        }
    }

    pub fn automation_create(
        request_id: u64,
        spawn_generation: u64,
        draft: AutomationTaskDraft,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationCreate { draft },
        }
    }

    pub fn automation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationList { limit },
        }
    }

    pub fn automation_cancel(
        request_id: u64,
        spawn_generation: u64,
        task_id: AutomationTaskId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationCancel { task_id },
        }
    }

    pub fn automation_set_enabled(
        request_id: u64,
        spawn_generation: u64,
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationSetEnabled {
                task_id,
                enabled,
                resume_at_ms,
            },
        }
    }

    pub fn memory_federation_grant(
        request_id: u64,
        spawn_generation: u64,
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationGrant {
                consumer_agent_id,
                owner_scope,
                lifetime_seconds,
            },
        }
    }

    pub fn memory_federation_revoke(
        request_id: u64,
        spawn_generation: u64,
        capability_id: MemoryFederationCapabilityId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationRevoke { capability_id },
        }
    }

    pub fn memory_federation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationList { limit },
        }
    }

    pub fn memory_federation_status(
        request_id: u64,
        spawn_generation: u64,
        capability_id: MemoryFederationCapabilityId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationStatus { capability_id },
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdMethod {
    Health,
    Lifecycle,
    SessionIngress,
    Events {
        after_cursor: u64,
        limit: u16,
    },
    AutomationCreate {
        draft: AutomationTaskDraft,
    },
    AutomationList {
        limit: u16,
    },
    AutomationCancel {
        task_id: AutomationTaskId,
    },
    AutomationSetEnabled {
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    },
    MemoryFederationGrant {
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    },
    MemoryFederationRevoke {
        capability_id: MemoryFederationCapabilityId,
    },
    MemoryFederationList {
        limit: u16,
    },
    MemoryFederationStatus {
        capability_id: MemoryFederationCapabilityId,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdResponse {
    pub schema_version: u32,
    pub request_id: u64,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub current_generation: u64,
    pub payload: AgentdPayload,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdPayload {
    Health(HealthSnapshot),
    Lifecycle(LifecycleSnapshot),
    SessionIngress(SessionIngress),
    Events(EventBatch),
    AutomationTask(AutomationTask),
    AutomationTasks {
        tasks: Vec<AutomationTask>,
    },
    MemoryFederationCapability(MemoryFederationCapabilitySnapshot),
    MemoryFederationCapabilities {
        capabilities: Vec<MemoryFederationCapabilitySnapshot>,
    },
    MemoryFederationStatus {
        capability: Option<MemoryFederationCapabilitySnapshot>,
    },
    Error {
        code: String,
        message: String,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HealthSnapshot {
    /// True once the App Server initialized while this exact spawn still owns Starting.
    pub promotion_ready: bool,
    /// True only after the supervisor promoted this spawn to Running.
    pub ready: bool,
    pub fenced: bool,
    pub lifecycle: AgentLifecycle,
    pub process_id: u32,
    pub workspace: PathBuf,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleSnapshot {
    pub lifecycle: AgentLifecycle,
    pub app_server_ready: bool,
    pub fenced: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionIngress {
    pub socket_path: PathBuf,
    pub transport: SessionTransport,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionTransport {
    CodexAppServerWebsocketOverUds,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdEvent {
    pub cursor: u64,
    pub kind: AgentdEventKind,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdEventKind {
    Bootstrapped,
    Lifecycle {
        lifecycle: AgentLifecycle,
        generation: u64,
    },
    AppServerReady,
    Draining,
    GenerationFenced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventBatch {
    pub events: Vec<AgentdEvent>,
    pub gap: bool,
    pub next_cursor: u64,
    pub latest_cursor: u64,
}

/// Exact host-bound turn/lease identity transported across the Agentd
/// boundary.
///
/// This is a qualification contract only.  It carries the witness that a
/// supervisor can later bind to an Agent-local append-only lease CAS, but the
/// current protocol has no method that grants authority from this value.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostTurnAuthorityBinding {
    pub schema_version: u32,
    pub owner_agent_id: AgentId,
    pub lease_id: String,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub lease_expires_at_unix_seconds: u64,
    pub lease_head_sha256: Sha256Digest,
}

impl HostTurnAuthorityBinding {
    pub fn new(
        owner_agent_id: AgentId,
        lease_id: impl Into<String>,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
        lease_head_sha256: Sha256Digest,
    ) -> Result<Self, String> {
        let binding = Self {
            schema_version: HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION,
            owner_agent_id,
            lease_id: lease_id.into(),
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token: fencing_token.into(),
            lease_expires_at_unix_seconds,
            lease_head_sha256,
        };
        binding.validate()?;
        Ok(binding)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION {
            return Err("unsupported host turn authority binding schema".to_string());
        }
        validate_protocol_text(&self.lease_id, "lease id", /*max_bytes*/ 512)?;
        validate_protocol_text(&self.fencing_token, "fencing token", /*max_bytes*/ 256)?;
        if self.authority_epoch == 0 {
            return Err("authority epoch must be non-zero".to_string());
        }
        if self.owner_epoch == 0 {
            return Err("owner epoch must be non-zero".to_string());
        }
        if self.generation == 0 {
            return Err("lease generation must be non-zero".to_string());
        }
        if self.lease_expires_at_unix_seconds == 0 {
            return Err("lease expiry must be non-zero".to_string());
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for HostTurnAuthorityBinding {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            schema_version: u32,
            owner_agent_id: AgentId,
            lease_id: String,
            authority_epoch: u64,
            owner_epoch: u64,
            generation: u64,
            fencing_token: String,
            lease_expires_at_unix_seconds: u64,
            lease_head_sha256: Sha256Digest,
        }

        let wire = Wire::deserialize(deserializer)?;
        let binding = Self {
            schema_version: wire.schema_version,
            owner_agent_id: wire.owner_agent_id,
            lease_id: wire.lease_id,
            authority_epoch: wire.authority_epoch,
            owner_epoch: wire.owner_epoch,
            generation: wire.generation,
            fencing_token: wire.fencing_token,
            lease_expires_at_unix_seconds: wire.lease_expires_at_unix_seconds,
            lease_head_sha256: wire.lease_head_sha256,
        };
        binding.validate().map_err(serde::de::Error::custom)?;
        Ok(binding)
    }
}

fn validate_protocol_text(value: &str, label: &str, max_bytes: usize) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_wire_round_trip_is_strict_and_bounded() {
        let request = AgentdRequest::health(7, 11);
        let request_bytes = serde_json::to_vec(&request).expect("serialize request");
        assert!(request_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&request_bytes).expect("parse request"),
            request
        );

        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 7,
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            spawn_generation: 11,
            current_generation: 11,
            payload: AgentdPayload::Health(HealthSnapshot {
                promotion_ready: true,
                ready: true,
                fenced: false,
                lifecycle: AgentLifecycle::Running,
                process_id: 17,
                workspace: PathBuf::from("/tmp/workspace"),
                home_root: PathBuf::from("/tmp/home"),
                run_root: PathBuf::from("/tmp/run"),
            }),
        };
        let response_bytes = serde_json::to_vec(&response).expect("serialize response");
        assert!(response_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdResponse>(&response_bytes).expect("parse response"),
            response
        );
    }

    #[test]
    fn automation_wire_round_trip_is_strict_and_bounded() {
        let mut draft = AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "x".repeat(32 * 1024),
            codex_hepta_automation::AutomationSchedule::Once,
            123,
            100,
        );
        draft.task_id =
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75001").expect("task id");
        let request = AgentdRequest::automation_create(9, 3, draft);
        let bytes = serde_json::to_vec(&request).expect("serialize request");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&bytes).expect("parse request"),
            request
        );
    }

    #[test]
    fn memory_federation_control_is_typed_strict_and_bounded() {
        let consumer = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").expect("consumer id");
        let grant = AgentdRequest::memory_federation_grant(
            10,
            3,
            consumer,
            MemoryFederationScopeKind::WorkspacePrivate,
            3_600,
        );
        let grant_bytes = serde_json::to_vec(&grant).expect("serialize grant");
        assert!(grant_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&grant_bytes).expect("parse grant"),
            grant
        );

        let capability_id =
            MemoryFederationCapabilityId::parse(format!("federation:v1:{}", "a".repeat(64)))
                .expect("capability id");
        let revoke = AgentdRequest::memory_federation_revoke(11, 3, capability_id);
        let revoke_bytes = serde_json::to_vec(&revoke).expect("serialize revoke");
        assert!(revoke_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&revoke_bytes).expect("parse revoke"),
            revoke
        );

        let malformed = String::from_utf8(revoke_bytes)
            .expect("utf8")
            .replace(&"a".repeat(64), "not-a-digest");
        assert!(serde_json::from_str::<AgentdRequest>(&malformed).is_err());
    }

    #[test]
    fn host_turn_authority_binding_is_strict_and_fail_closed() {
        let owner = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("owner id");
        let binding = HostTurnAuthorityBinding::new(
            owner,
            "lease:transport-witness",
            7,
            11,
            3,
            "fence:transport-witness",
            1_900_000_000,
            Sha256Digest::for_bytes(b"transport-head"),
        )
        .expect("valid host authority binding");
        let bytes = serde_json::to_vec(&binding).expect("serialize host binding");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<HostTurnAuthorityBinding>(&bytes).expect("parse host binding"),
            binding
        );

        let mut zero_epoch = serde_json::to_string(&binding).expect("json");
        zero_epoch = zero_epoch.replace("\"authority_epoch\":7", "\"authority_epoch\":0");
        assert!(serde_json::from_str::<HostTurnAuthorityBinding>(&zero_epoch).is_err());

        let unknown = serde_json::to_string(&binding)
            .expect("json")
            .replace('}', ",\"unexpected\":true}");
        assert!(serde_json::from_str::<HostTurnAuthorityBinding>(&unknown).is_err());

        assert!(
            HostTurnAuthorityBinding::new(
                binding.owner_agent_id,
                binding.lease_id.clone(),
                binding.authority_epoch,
                binding.owner_epoch,
                binding.generation,
                "\0",
                binding.lease_expires_at_unix_seconds,
                binding.lease_head_sha256,
            )
            .is_err()
        );
    }
}
