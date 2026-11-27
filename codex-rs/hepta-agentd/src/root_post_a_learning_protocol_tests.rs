//! Codec tests use public data only; they do not construct an opaque ACK.

use super::*;

#[test]
fn post_a_learning_ack_rejects_other_cut_scope_and_response_shapes() -> anyhow::Result<()> {
    let profile = Digest32::of_bytes(b"actual historical profile data").to_string();
    let reply = PostAFrozenLearningResponseV1 {
        schema: 1,
        purpose: POST_A_PURPOSE.into(),
        request_id: 7,
        profile: profile.clone(),
        data_cut: Digest32::of_bytes(b"complete Task cut data").to_string(),
        frozen_scope: Digest32::of_bytes(b"Root derived scope data").to_string(),
    };
    let value = serde_json::to_value(reply)?;
    require_post_a_learning_reply(&serde_json::to_vec(&value)?, 7, &profile)?;
    for (field, replacement) in [
        ("purpose", serde_json::json!(PURPOSE)),
        ("schema", serde_json::json!(2)),
        ("request_id", serde_json::json!(8)),
        (
            "profile",
            serde_json::json!(Digest32::of_bytes(b"other").to_string()),
        ),
        ("data_cut", serde_json::json!("")),
        (
            "frozen_scope",
            serde_json::json!(Digest32::from_array([0; 32]).to_string()),
        ),
        ("completed", serde_json::json!(true)),
    ] {
        let mut changed = value.clone();
        changed[field] = replacement;
        assert!(
            require_post_a_learning_reply(&serde_json::to_vec(&changed)?, 7, &profile).is_err()
        );
    }
    assert!(require_post_a_learning_reply(&serde_json::to_vec(&value)?, 0, &profile).is_err());
    assert!(
        require_post_a_learning_reply(&serde_json::to_vec(&value)?, MAX_READS + 1, &profile)
            .is_err()
    );
    assert!(require_post_a_learning_reply(&vec![b' '; WIRE_BOUND + 1], 7, &profile).is_err());
    Ok(())
}
