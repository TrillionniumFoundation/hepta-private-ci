use super::OriginalQ24CompletedHistoryDataV1;

fn data() -> OriginalQ24CompletedHistoryDataV1 {
    OriginalQ24CompletedHistoryDataV1 {
        schema: 1,
        identity_digest: "11".repeat(32),
        root_profile: "22".repeat(32),
        initial: "33".repeat(32),
        frozen_scope: "44".repeat(32),
        terminal_head: "55".repeat(32),
        acceptance: "66".repeat(32),
        current_head: "77".repeat(32),
        successor_record: "88".repeat(32),
        successor_cut: "99".repeat(32),
    }
}

#[test]
fn completed_history_data_round_trips_without_authority_fields()
-> Result<(), Box<dyn std::error::Error>> {
    let data = data();
    data.validate_data()?;
    let encoded = serde_json::to_vec(&data)?;
    assert_eq!(
        serde_json::from_slice::<OriginalQ24CompletedHistoryDataV1>(&encoded)?,
        data
    );
    let mut foreign = serde_json::to_value(data)?;
    foreign["grant"] = serde_json::json!(true);
    assert!(serde_json::from_value::<OriginalQ24CompletedHistoryDataV1>(foreign).is_err());
    Ok(())
}

#[test]
fn completed_history_data_requires_every_original_digest() -> Result<(), Box<dyn std::error::Error>>
{
    let original = serde_json::to_value(data())?;
    for field in [
        "schema",
        "identity_digest",
        "root_profile",
        "initial",
        "frozen_scope",
        "terminal_head",
        "acceptance",
        "current_head",
        "successor_record",
        "successor_cut",
    ] {
        let mut missing = original.clone();
        let Some(object) = missing.as_object_mut() else {
            return Err("fixture must be an object".into());
        };
        object.remove(field);
        assert!(
            serde_json::from_value::<OriginalQ24CompletedHistoryDataV1>(missing).is_err(),
            "{field}"
        );
    }
    Ok(())
}

#[test]
fn completed_history_data_rejects_zero_and_noncanonical_cuts()
-> Result<(), Box<dyn std::error::Error>> {
    let original = serde_json::to_value(data())?;
    for field in [
        "identity_digest",
        "root_profile",
        "initial",
        "frozen_scope",
        "terminal_head",
        "acceptance",
        "current_head",
        "successor_record",
        "successor_cut",
    ] {
        for bad in [
            "0".repeat(64),
            "A".repeat(64),
            "f".repeat(63),
            "f".repeat(65),
            "g".repeat(64),
        ] {
            let mut value = original.clone();
            value[field] = serde_json::json!(bad);
            let invalid: OriginalQ24CompletedHistoryDataV1 = serde_json::from_value(value)?;
            assert!(invalid.validate_data().is_err(), "{field}");
        }
    }
    let mut version = data();
    version.schema = 2;
    assert!(version.validate_data().is_err());
    Ok(())
}

#[test]
fn completed_history_query_accepts_no_caller_business_data()
-> Result<(), Box<dyn std::error::Error>> {
    let request = crate::AgentdRequest {
        schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
        request_id: 19,
        spawn_generation: 3,
        method: crate::AgentdMethod::OriginalQ24CompletedHistory {},
    };
    let encoded = serde_json::to_vec(&request)?;
    assert_eq!(
        serde_json::from_slice::<crate::AgentdRequest>(&encoded)?,
        request
    );
    for field in [
        "scope",
        "terminal_head",
        "verified_at",
        "successor_cut",
        "grant",
        "path",
    ] {
        let mut foreign = serde_json::to_value(&request)?;
        foreign["method"][field] = serde_json::json!("caller-selected");
        assert!(
            serde_json::from_value::<crate::AgentdRequest>(foreign).is_err(),
            "{field}"
        );
    }
    Ok(())
}

#[test]
fn completed_history_missing_remains_distinct_from_observed_data()
-> Result<(), Box<dyn std::error::Error>> {
    for data in [None, Some(data())] {
        let response = crate::AgentdResponse {
            schema_version: crate::AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: u64::MAX,
            agent_id: codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
                .map_err(std::io::Error::other)?,
            spawn_generation: u64::MAX,
            current_generation: u64::MAX,
            payload: crate::AgentdPayload::OriginalQ24CompletedHistory { data },
        };
        let bytes = serde_json::to_vec(&response)?;
        assert!((bytes.len() as u64) < crate::MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<crate::AgentdResponse>(&bytes)?,
            response
        );
        let mut forged = serde_json::to_value(&response)?;
        forged["payload"]["completed"] = serde_json::json!(true);
        assert!(serde_json::from_value::<crate::AgentdResponse>(forged).is_err());
    }
    Ok(())
}
