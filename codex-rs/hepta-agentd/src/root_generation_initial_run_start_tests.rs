//! Reply parsing tests. These data fixtures do not impersonate a Root socket,
//! live writer or actual acknowledgement; those require the original harness.

use super::*;

fn publication() -> OriginalRunStartPublicationDataV1 {
    OriginalRunStartPublicationDataV1 {
        run_id: "original-run".into(),
        profile_digest: Digest32::of_bytes(b"profile").to_string(),
        sequence: 1,
        record_digest: Digest32::of_bytes(b"record").to_string(),
        chain_digest: Digest32::of_bytes(b"chain").to_string(),
    }
}

fn reply() -> OriginalRunStartRetentionResponseV1 {
    OriginalRunStartRetentionResponseV1 {
        schema: 1,
        purpose: RUN_START_RETENTION_PURPOSE.into(),
        request_id: 7,
        profile: "original-initial-profile".into(),
        mode: RootGenerationInitialModeV1::Reserve,
        publication: publication(),
        retained: Digest32::of_bytes(b"root-retained-data").to_string(),
    }
}

#[test]
fn original_run_start_reply_binds_request_profile_mode_and_complete_tuple() -> anyhow::Result<()> {
    let original = reply();
    let expected = publication();
    let valid = serde_json::to_value(&original)?;
    require_retained_reply(
        &serde_json::to_vec(&valid)?,
        original.request_id,
        &original.profile,
        original.mode,
        &expected,
    )?;
    for (field, value) in [
        ("schema", serde_json::json!(2)),
        (
            "purpose",
            serde_json::json!("runtime.generation.initial.v1"),
        ),
        ("request_id", serde_json::json!(8)),
        ("profile", serde_json::json!("another-initial-profile")),
        (
            "mode",
            serde_json::to_value(RootGenerationInitialModeV1::Recover)?,
        ),
        ("retained", serde_json::json!(Digest32::ZERO.to_string())),
    ] {
        let mut changed = valid.clone();
        changed[field] = value;
        assert!(
            require_retained_reply(
                &serde_json::to_vec(&changed)?,
                original.request_id,
                &original.profile,
                original.mode,
                &expected,
            )
            .is_err(),
            "accepted changed {field}"
        );
    }
    for (field, value) in [
        ("run_id", serde_json::json!("another-run")),
        ("sequence", serde_json::json!(2)),
        (
            "profile_digest",
            serde_json::json!(Digest32::of_bytes(b"other-profile").to_string()),
        ),
        (
            "record_digest",
            serde_json::json!(Digest32::of_bytes(b"other-record").to_string()),
        ),
        (
            "chain_digest",
            serde_json::json!(Digest32::of_bytes(b"other-chain").to_string()),
        ),
    ] {
        let mut changed = valid.clone();
        changed["publication"][field] = value;
        assert!(
            require_retained_reply(
                &serde_json::to_vec(&changed)?,
                original.request_id,
                &original.profile,
                original.mode,
                &expected,
            )
            .is_err(),
            "accepted changed publication {field}"
        );
    }
    Ok(())
}

#[test]
fn original_run_start_reply_rejects_partial_extra_fields_and_extra_messages() -> anyhow::Result<()>
{
    let original = reply();
    let expected = publication();
    let raw = serde_json::to_vec(&original)?;
    let check = |raw: &[u8]| {
        require_retained_reply(
            raw,
            original.request_id,
            &original.profile,
            original.mode,
            &expected,
        )
    };
    check(&raw)?;
    for length in 0..raw.len() {
        assert!(
            check(&raw[..length]).is_err(),
            "accepted incomplete length {length}"
        );
    }
    let mut duplicate = raw.clone();
    duplicate.extend_from_slice(&raw);
    assert!(check(&duplicate).is_err());
    for field in ["authority", "path", "fresh", "retry", "final_use"] {
        let mut changed = serde_json::to_value(&original)?;
        changed[field] = serde_json::json!(true);
        assert!(check(&serde_json::to_vec(&changed)?).is_err());
        let mut changed = serde_json::to_value(&original)?;
        changed["publication"][field] = serde_json::json!(true);
        assert!(check(&serde_json::to_vec(&changed)?).is_err());
    }
    Ok(())
}
