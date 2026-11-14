//! Wire data tests do not construct an original Root acknowledgement.

use super::OriginalQ24TerminalAcceptanceDataV1;

fn data() -> OriginalQ24TerminalAcceptanceDataV1 {
    OriginalQ24TerminalAcceptanceDataV1 {
        schema: 1,
        identity_digest: "11".repeat(32),
        root_profile: "22".repeat(32),
        initial: "33".repeat(32),
        frozen_scope: "44".repeat(32),
        terminal_head: "55".repeat(32),
        acceptance: "66".repeat(32),
        data_cut: "77".repeat(32),
    }
}

#[test]
fn terminal_acceptance_data_does_not_deserialize_as_completed_c_history()
-> Result<(), Box<dyn std::error::Error>> {
    let original = data();
    original.validate_data()?;
    let value = serde_json::to_value(&original)?;
    assert_eq!(
        serde_json::from_value::<OriginalQ24TerminalAcceptanceDataV1>(value.clone())?,
        original
    );
    assert!(
        serde_json::from_value::<crate::OriginalQ24CompletedHistoryDataV1>(value.clone()).is_err()
    );
    for field in ["current_head", "successor_record", "successor_cut", "grant"] {
        let mut foreign = value.clone();
        foreign[field] = serde_json::json!("caller-selected");
        assert!(
            serde_json::from_value::<OriginalQ24TerminalAcceptanceDataV1>(foreign).is_err(),
            "{field}"
        );
    }
    Ok(())
}

#[test]
fn terminal_acceptance_data_requires_all_exact_digests() -> Result<(), Box<dyn std::error::Error>> {
    let original = serde_json::to_value(data())?;
    for field in [
        "identity_digest",
        "root_profile",
        "initial",
        "frozen_scope",
        "terminal_head",
        "acceptance",
        "data_cut",
    ] {
        let mut missing = original.clone();
        let Some(object) = missing.as_object_mut() else {
            return Err("fixture must be an object".into());
        };
        object.remove(field);
        assert!(
            serde_json::from_value::<OriginalQ24TerminalAcceptanceDataV1>(missing).is_err(),
            "{field}"
        );
        for bad in [
            "0".repeat(64),
            "A".repeat(64),
            "g".repeat(64),
            "f".repeat(63),
            "f".repeat(65),
        ] {
            let mut value = original.clone();
            value[field] = serde_json::json!(bad);
            let invalid: OriginalQ24TerminalAcceptanceDataV1 = serde_json::from_value(value)?;
            assert!(invalid.validate_data().is_err(), "{field}");
        }
    }
    let mut version = data();
    version.schema = 2;
    assert!(version.validate_data().is_err());
    Ok(())
}

#[test]
fn terminal_acceptance_query_has_no_business_payload() -> Result<(), Box<dyn std::error::Error>> {
    let request = crate::AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 19,
        spawn_generation: 3,
        method: crate::AgentdMethod::OriginalQ24TerminalAcceptance {},
    };
    let value = serde_json::to_value(&request)?;
    assert_eq!(
        serde_json::from_value::<crate::AgentdRequest>(value.clone())?,
        request
    );
    for field in ["initial", "terminal_head", "acceptance", "path", "grant"] {
        let mut foreign = value.clone();
        foreign["method"][field] = serde_json::json!("caller-selected");
        assert!(
            serde_json::from_value::<crate::AgentdRequest>(foreign).is_err(),
            "{field}"
        );
    }
    Ok(())
}

#[test]
fn missing_terminal_acceptance_stays_none_on_the_wire() -> Result<(), Box<dyn std::error::Error>> {
    for data in [None, Some(data())] {
        let payload = crate::AgentdPayload::OriginalQ24TerminalAcceptance { data };
        let encoded = serde_json::to_vec(&payload)?;
        assert!((encoded.len() as u64) < crate::MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<crate::AgentdPayload>(&encoded)?,
            payload
        );
        let mut foreign = serde_json::to_value(payload)?;
        foreign["completed"] = serde_json::json!(true);
        assert!(serde_json::from_value::<crate::AgentdPayload>(foreign).is_err());
    }
    Ok(())
}
