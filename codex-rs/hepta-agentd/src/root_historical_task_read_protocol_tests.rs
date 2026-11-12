use super::*;
use pretty_assertions::assert_eq;

#[test]
fn complete_historical_reply_binds_original_purpose_profile_and_sequence() -> anyhow::Result<()> {
    let profile = Digest32::of_bytes(b"original recipient profile").to_string();
    let cut = Digest32::of_bytes(b"actual complete task cut");
    let response = HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: profile.clone(),
        data_cut: cut.to_string(),
    };
    let bytes = serde_json::to_vec(&response)?;
    assert_eq!(
        require_complete_reply(&bytes, /*request_id*/ 1, &profile)?,
        cut
    );
    for (field, value) in [
        (
            "purpose",
            serde_json::json!("runtime.learning.historical-source-cell-read.v1"),
        ),
        (
            "profile",
            serde_json::json!(Digest32::of_bytes(b"another recipient").to_string()),
        ),
        ("request_id", serde_json::json!(2)),
        ("schema", serde_json::json!(2)),
        ("data_cut", serde_json::json!("00".repeat(32))),
    ] {
        let mut altered = serde_json::to_value(&response)?;
        altered[field] = value;
        assert!(
            require_complete_reply(
                &serde_json::to_vec(&altered)?,
                /*request_id*/ 1,
                &profile
            )
            .is_err()
        );
    }
    for request_id in [0, MAX_READS + 1] {
        assert!(require_complete_reply(&bytes, request_id, &profile).is_err());
    }
    Ok(())
}

#[test]
fn complete_historical_wire_refuses_peer_selected_sources_and_raw_authority() -> anyhow::Result<()>
{
    let request = HistoricalTaskReadRequestV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: Digest32::of_bytes(b"profile").to_string(),
    };
    for field in [
        "source_path",
        "run_id",
        "authority",
        "target",
        "data_cut",
        "ledger",
    ] {
        let mut altered = serde_json::to_value(&request)?;
        altered[field] = serde_json::json!("peer choice");
        assert!(serde_json::from_value::<HistoricalTaskReadRequestV1>(altered).is_err());
    }
    let response = HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: request.profile.clone(),
        data_cut: Digest32::of_bytes(b"complete data").to_string(),
    };
    let mut bytes = serde_json::to_vec(&response)?;
    bytes.extend_from_slice(b"{}");
    assert!(require_complete_reply(&bytes, /*request_id*/ 1, &request.profile).is_err());
    let bytes = serde_json::to_vec(&response)?;
    assert!(
        require_complete_reply(
            &bytes[..bytes.len() - 1],
            /*request_id*/ 1,
            &request.profile
        )
        .is_err()
    );
    Ok(())
}
