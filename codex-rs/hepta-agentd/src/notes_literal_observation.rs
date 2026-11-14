//! The existing Desktop Submission observation schema, retained by the original
//! sender. It is metadata from one transport attempt, never an effect receipt.

use codex_hepta_agent_protocol::ObjectiveRunAdmission;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::ObjectiveSenderObservation;
use codex_hepta_memory::ObjectiveSenderObservationKind;
use codex_hepta_memory::ObjectiveSenderRequest;
use serde_json::Value;
use serde_json::json;

use crate::AgentdPayload;
use crate::AgentdResponse;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdNotesSubmissionState {
    NotSent {
        issue: &'static str,
    },
    SubmitUnknown {
        issue: &'static str,
    },
    RefusedBeforePublication {
        reason: &'static str,
        response_generation: u64,
    },
    Admitted {
        receipt: ObjectiveRunAdmission,
        response_generation: u64,
    },
    Conflict {
        run_id: String,
        conflict_digest: String,
        response_generation: u64,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdNotesObservationRetention {
    Acknowledged,
    Unknown,
}

/// No text, signature, endpoint or authority crosses this metadata projection.
/// An admitted response and acknowledged local observation remain distinct from
/// original run termination, application durability and protected Current.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdNotesSubmissionObservation {
    pub request_sha256: Sha256Digest,
    pub run_id: String,
    pub state: AgentdNotesSubmissionState,
    pub retention: AgentdNotesObservationRetention,
}

pub(crate) fn classify(
    request: &ObjectiveSenderRequest,
    response: AgentdResponse,
) -> Result<AgentdNotesSubmissionState, &'static str> {
    let generation = response.current_generation;
    match response.payload {
        AgentdPayload::ObjectiveRun(receipt) => {
            if receipt.run_id != request.identity().run_id
                || [
                    &receipt.objective_digest,
                    &receipt.hard_constraint_digest,
                    &receipt.publication_digest,
                    &receipt.chain_digest,
                ]
                .into_iter()
                .any(|value| !valid_digest(value))
                || !matches!(
                    receipt.disposition.as_str(),
                    "compiled"
                        | "explicit_abstain"
                        | "canonical_ready"
                        | "canonical_abstained"
                        | "canonical_slow_path"
                )
            {
                return Err("objective_protocol_mismatch");
            }
            Ok(AgentdNotesSubmissionState::Admitted {
                receipt,
                response_generation: generation,
            })
        }
        AgentdPayload::ObjectiveConflict {
            run_id,
            conflict_digest,
        } => {
            if run_id != request.identity().run_id || !valid_digest(&conflict_digest) {
                return Err("objective_protocol_mismatch");
            }
            Ok(AgentdNotesSubmissionState::Conflict {
                run_id,
                conflict_digest,
                response_generation: generation,
            })
        }
        AgentdPayload::Error { code, message } => {
            let reason = match (code.as_str(), message.as_str()) {
                ("objective_unavailable", "no owner objective profile is configured") => {
                    "objective_unavailable"
                }
                ("unsupported_schema", "unsupported agentd control schema")
                    if generation == request.origin().spawn_generation =>
                {
                    "unsupported_schema"
                }
                ("request_rejected", _) => return Err("objective_owner_request_rejected"),
                _ => return Err("objective_owner_error"),
            };
            Ok(AgentdNotesSubmissionState::RefusedBeforePublication {
                reason,
                response_generation: generation,
            })
        }
        _ => Err("objective_protocol_mismatch"),
    }
}

pub(crate) fn retained_observation(
    request: &ObjectiveSenderRequest,
    state: &AgentdNotesSubmissionState,
    bytes_written: usize,
    frame_bytes: usize,
) -> Result<ObjectiveSenderObservation, &'static str> {
    let status: Value = match state {
        AgentdNotesSubmissionState::NotSent { issue } => json!({"type":"not_sent", "issue":issue}),
        AgentdNotesSubmissionState::SubmitUnknown { issue } => {
            json!({"type":"submit_unknown", "issue":issue})
        }
        AgentdNotesSubmissionState::RefusedBeforePublication {
            reason,
            response_generation,
        } => {
            json!({"type":"refused_before_publication", "reason":reason, "response_generation":response_generation})
        }
        AgentdNotesSubmissionState::Admitted {
            receipt,
            response_generation,
        } => json!({
            "type":"admitted", "run_id":receipt.run_id, "objective_digest":receipt.objective_digest,
            "hard_constraint_digest":receipt.hard_constraint_digest,
            "publication_digest":receipt.publication_digest, "chain_digest":receipt.chain_digest,
            "disposition":receipt.disposition, "idempotent":receipt.idempotent,
            "response_generation":response_generation,
        }),
        AgentdNotesSubmissionState::Conflict {
            run_id,
            conflict_digest,
            response_generation,
        } => json!({"type":"conflict", "run_id":run_id, "conflict_digest":conflict_digest,
                "response_generation":response_generation}),
    };
    let origin = request.origin();
    let identity = request.identity();
    let original = serde_json::to_string(&json!({
        "schema":1, "original_sha256":identity.original_sha256.as_str(),
        "submission":{
            "request_id":origin.request_id, "agent_id":origin.agent_id.as_str(),
            "spawn_generation":origin.spawn_generation, "expected_peer_uid":origin.expected_peer_uid,
            "expected_peer_pid":origin.expected_peer_pid,
            "objective":{
                "issuer_id":identity.issuer_id, "key_epoch":identity.key_epoch,
                "message_id":identity.message_id, "sequence":identity.sequence,
                "expires_at_ms":identity.expires_at_ms, "spawn_generation":identity.body_spawn_generation,
                "run_id":identity.run_id, "objective_revision":identity.objective_revision,
                "authority_epoch":identity.authority_epoch, "runtime_body_digest":identity.runtime_body_digest,
                "preference_state_digest":identity.preference_state_digest, "model_tuple_digest":identity.model_tuple_digest,
                "prompt_registry_digest":identity.prompt_registry_digest, "artifact_set_digest":identity.artifact_set_digest,
            },
        },
        "bytes_written":bytes_written, "request_frame_bytes":frame_bytes, "status":status,
    })).map_err(|_| "objective_protocol_mismatch")?;
    ObjectiveSenderObservation::from_original(ObjectiveSenderObservationKind::Submission, original)
        .map_err(|_| "objective_protocol_mismatch")
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
        && value.bytes().any(|byte| byte != b'0')
}
