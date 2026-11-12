//! These are wire checks only, not a task or Observer qualification.

use super::*;
use crate::AgentdMethod;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn q24_task_observation_zero_payload_rejects_caller_selected_task_or_authority() -> TestResult {
    let request = AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 17,
        spawn_generation: 3,
        method: AgentdMethod::Q24OriginalTaskObservation {},
    };
    let encoded = serde_json::to_vec(&request)?;
    assert_eq!(serde_json::from_slice::<AgentdRequest>(&encoded)?, request);
    for field in ["run_id", "publication_digest", "owner", "trust", "grant"] {
        let mut value = serde_json::to_value(&request)?;
        value["method"][field] = serde_json::json!("caller-selected");
        assert!(serde_json::from_value::<AgentdRequest>(value).is_err());
    }
    Ok(())
}

#[test]
fn q24_task_observation_canonical_decision_fits_control_envelope() -> TestResult {
    let response = AgentdResponse {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: u64::MAX,
        agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
            .map_err(std::io::Error::other)?,
        spawn_generation: u64::MAX,
        current_generation: u64::MAX,
        payload: AgentdPayload::Q24OriginalTaskObservation(Q24OriginalTaskObservationV1 {
            run_id: "r".repeat(128),
            source_publication_digest: "11".repeat(32),
            source_history_digest: "22".repeat(32),
            decision_preimage_hex: "ab".repeat(MAX_Q24_DECISION_PREIMAGE_BYTES),
            decision_sequence: u64::MAX,
            decision_chain_digest: "33".repeat(32),
            episode_id: "e".repeat(128),
            selected_candidate_id: "c".repeat(128),
            outcome_record_id: "o".repeat(128),
            outcome_id: "i".repeat(128),
            unit_profile_digest: "44".repeat(32),
            expected_delay_profile_digest: "55".repeat(32),
            observer_principal_id: "p".repeat(128),
            observer_controller_id: "k".repeat(128),
        }),
    };
    let bytes = serde_json::to_vec(&response)?;
    assert!((bytes.len() as u64) < crate::MAX_CONTROL_FRAME_BYTES);
    assert_eq!(serde_json::from_slice::<AgentdResponse>(&bytes)?, response);
    for field in [
        "outcome_value",
        "private_key",
        "signing_authority",
        "dataset_grant",
    ] {
        let mut value = serde_json::to_value(&response)?;
        value["payload"][field] = serde_json::json!("not task observation data");
        assert!(serde_json::from_value::<AgentdResponse>(value).is_err());
    }
    Ok(())
}
