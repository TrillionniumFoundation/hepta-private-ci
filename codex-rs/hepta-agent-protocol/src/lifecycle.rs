//! Static lifecycle view of the original control envelope and wire names.
//! A profile narrows only its decoder/encoder; generation and identity checks
//! remain in the original daemon and Supervisor. This carries no authority.
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdCapabilitySet;
use crate::AgentdRequestFrame;
use crate::AgentdResponseFrame;
use crate::DrainSnapshot;
use crate::HealthSnapshot;
use crate::LifecycleSnapshot;
use crate::ReadinessSnapshot;
use serde::Deserialize;
use serde::Serialize;

pub type AgentdLifecycleRequest = AgentdRequestFrame<AgentdLifecycleMethod>;
pub type AgentdLifecycleResponse = AgentdResponseFrame<AgentdLifecyclePayload>;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdLifecycleMethod {
    Capabilities,
    Health,
    Lifecycle,
    Readiness,
    Drain,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdLifecyclePayload {
    Capabilities(AgentdCapabilitySet),
    Health(HealthSnapshot),
    Lifecycle(LifecycleSnapshot),
    Readiness(ReadinessSnapshot),
    Drain(DrainSnapshot),
    Error { code: String, message: String },
}

impl AgentdLifecycleRequest {
    pub fn health(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdLifecycleMethod::Health,
        }
    }
    pub fn drain(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdLifecycleMethod::Drain,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AgentdPayload;
    use crate::AgentdRequest;
    use crate::AgentdResponse;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentLifecycle;

    #[test]
    fn lifecycle_requests_are_the_original_exact_wire() {
        for original in [
            AgentdRequest::capabilities(7, 11),
            AgentdRequest::health(7, 11),
            AgentdRequest::lifecycle(7, 11),
            AgentdRequest::readiness(7, 11),
            AgentdRequest::drain(7, 11),
        ] {
            let wire = serde_json::to_vec(&original).unwrap();
            let bounded: AgentdLifecycleRequest = serde_json::from_slice(&wire).unwrap();
            assert_eq!(serde_json::to_vec(&bounded).unwrap(), wire);
        }
        assert_eq!(
            serde_json::to_vec(&AgentdLifecycleRequest::health(7, 11)).unwrap(),
            serde_json::to_vec(&AgentdRequest::health(7, 11)).unwrap()
        );
        assert_eq!(
            serde_json::to_vec(&AgentdLifecycleRequest::drain(7, 11)).unwrap(),
            serde_json::to_vec(&AgentdRequest::drain(7, 11)).unwrap()
        );
    }

    #[test]
    fn lifecycle_decoder_rejects_other_methods_and_extra_or_duplicate_fields() {
        let other = serde_json::to_vec(&AgentdRequest::session_ingress(7, 11)).unwrap();
        assert!(serde_json::from_slice::<AgentdRequest>(&other).is_ok());
        assert!(serde_json::from_slice::<AgentdLifecycleRequest>(&other).is_err());
        let original = serde_json::to_value(AgentdRequest::health(7, 11)).unwrap();
        for location in ["envelope", "method"] {
            let mut bad = original.clone();
            let map = if location == "envelope" {
                bad.as_object_mut().unwrap()
            } else {
                bad["method"].as_object_mut().unwrap()
            };
            map.insert("unexpected".into(), serde_json::json!(true));
            assert!(serde_json::from_value::<AgentdRequest>(bad.clone()).is_err());
            assert!(serde_json::from_value::<AgentdLifecycleRequest>(bad).is_err());
        }
        let duplicate = br#"{"schema_version":2,"request_id":7,"request_id":8,"spawn_generation":11,"method":{"type":"health"}}"#;
        assert!(serde_json::from_slice::<AgentdRequest>(duplicate).is_err());
        assert!(serde_json::from_slice::<AgentdLifecycleRequest>(duplicate).is_err());
    }

    #[test]
    fn lifecycle_responses_preserve_original_payload_and_strict_envelope() {
        let payloads = [
            AgentdPayload::Health(HealthSnapshot {
                promotion_ready: false,
                ready: false,
                fenced: true,
                lifecycle: AgentLifecycle::Draining,
                process_id: 41,
                workspace: "/workspace".into(),
                home_root: "/home".into(),
                run_root: "/run/owner".into(),
            }),
            AgentdPayload::Lifecycle(LifecycleSnapshot {
                lifecycle: AgentLifecycle::Draining,
                app_server_ready: false,
                fenced: true,
            }),
            AgentdPayload::Readiness(ReadinessSnapshot {
                critical_stores_ready: false,
                revocation_ready: false,
                required_ports_ready: false,
                admission_open: false,
            }),
            AgentdPayload::Drain(DrainSnapshot {
                admission_closed: true,
                running_turns: 0,
                drained: false,
                lifecycle: AgentLifecycle::Draining,
                fenced: true,
            }),
            AgentdPayload::Error {
                code: "request_rejected".into(),
                message: "fenced".into(),
            },
        ];
        for payload in payloads {
            let original = AgentdResponse {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: 7,
                agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
                spawn_generation: 11,
                current_generation: 13,
                payload,
            };
            let bytes = serde_json::to_vec(&original).unwrap();
            let bounded: AgentdLifecycleResponse = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(serde_json::to_vec(&bounded).unwrap(), bytes);
            let mut extra = serde_json::to_value(bounded).unwrap();
            extra["unexpected"] = serde_json::json!(true);
            assert!(serde_json::from_value::<AgentdResponse>(extra.clone()).is_err());
            assert!(serde_json::from_value::<AgentdLifecycleResponse>(extra).is_err());
        }
    }
}
