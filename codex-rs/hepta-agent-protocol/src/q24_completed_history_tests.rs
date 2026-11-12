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
