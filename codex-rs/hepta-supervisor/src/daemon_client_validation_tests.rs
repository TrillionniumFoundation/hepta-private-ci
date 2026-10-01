use anyhow::Result;
use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;
use crate::daemon_protocol::ControlStateDigest;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const OTHER_AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
const DIGEST: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn status(agent_id: &str) -> Result<crate::SupervisordAgentStatus> {
    Ok(serde_json::from_value(json!({
        "agent_id": agent_id, "lifecycle": "running", "lifecycle_generation": 7,
        "active": true, "healthy": true, "process_id": 100,
        "spawn_generation": 5, "runtime_generation": 7,
        "current_release": "agentd-v1", "previous_release": null,
        "release_change_pending": false,
        "control_fence": {
            "agent_id": agent_id, "supervisor_epoch": EPOCH,
            "lifecycle": "running", "lifecycle_generation": 7,
            "spawn_generation": 5, "runtime_generation": 7,
            "current_release": "agentd-v1", "previous_release": null,
            "release_change_pending": false, "state_digest": DIGEST
        },
        "matrix": {
            "configured": false, "active": false, "healthy": false, "degraded": false,
            "process_id": null, "attached_agent_generation": null, "binding_revision": null,
            "restart_attempt": 0, "last_error": null
        }
    }))?)
}

fn response(payload: SupervisordPayload) -> SupervisordResponse {
    SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: 41,
        payload,
    }
}

fn accepted() -> Result<SupervisordPayload> {
    let agent = status(AGENT)?;
    Ok(SupervisordPayload::MutationAccepted {
        operation: SupervisordMutation::Restart,
        accepted_state_digest: agent.control_fence.state_digest.clone(),
        agent,
        production_receipt: None,
    })
}

#[test]
fn response_identity_payload_and_selected_agent_must_match_request() -> Result<()> {
    let selected = status(AGENT)?;
    let request = SupervisordRequest::new(
        /*request_id*/ 41,
        SupervisordMethod::Snapshot {
            agent_id: selected.agent_id.clone(),
        },
    );
    let valid = response(SupervisordPayload::Agent(selected));
    validate_response(&request, &valid)?;
    let mut wrong_id = valid.clone();
    wrong_id.request_id += 1;
    let mut wrong_schema = valid;
    wrong_schema.schema_version += 1;
    let wrong_agent = response(SupervisordPayload::Agent(status(OTHER_AGENT)?));
    let wrong_type = response(SupervisordPayload::Roster { agents: Vec::new() });
    for invalid in [wrong_id, wrong_schema, wrong_agent, wrong_type] {
        assert!(validate_response(&request, &invalid).is_err());
    }
    Ok(())
}

#[test]
fn mutation_acceptance_binds_operation_digest_agent_and_owner_epoch() -> Result<()> {
    let fence = status(AGENT)?.control_fence;
    let request =
        SupervisordRequest::new(/*request_id*/ 41, SupervisordMethod::Restart { fence });
    let valid = response(accepted()?);
    validate_response(&request, &valid)?;
    for field in [
        "operation",
        "accepted_state_digest",
        "agent",
        "epoch",
        "status",
    ] {
        let mut changed = valid.clone();
        let SupervisordPayload::MutationAccepted {
            operation,
            accepted_state_digest,
            agent,
            ..
        } = &mut changed.payload
        else {
            unreachable!("fixture acceptance")
        };
        match field {
            "operation" => *operation = SupervisordMutation::Kill,
            "accepted_state_digest" => {
                *accepted_state_digest = ControlStateDigest::from_bytes([1; 32])
            }
            "agent" => *agent = status(OTHER_AGENT)?,
            "epoch" => agent.control_fence.supervisor_epoch = crate::SupervisorEpoch::new(),
            "status" => agent.control_fence.lifecycle_generation += 1,
            _ => unreachable!("fixture substitution"),
        }
        assert!(validate_response(&request, &changed).is_err(), "{field}");
    }
    Ok(())
}
