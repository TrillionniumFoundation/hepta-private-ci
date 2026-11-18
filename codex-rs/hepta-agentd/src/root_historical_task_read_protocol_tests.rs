use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn complete_historical_reply_binds_original_purpose_profile_and_sequence()
-> anyhow::Result<()> {
    let profile = Digest32::of_bytes(b"original recipient profile").to_string();
    let cut = Digest32::of_bytes(b"actual complete task cut");
    let (publication, ledger, _, _) = crate::circuit_task::publication_data_fixture().await?;
    let response = HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: profile.clone(),
        data_cut: cut.to_string(),
        ledger: ledger.clone(),
        publication: publication.clone(),
    };
    let bytes = serde_json::to_vec(&response)?;
    assert_eq!(
        require_complete_reply(&bytes, /*request_id*/ 1, &profile)?,
        HistoricalTaskReadDataV1 {
            data_cut: cut,
            ledger,
            publication,
        }
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
    for field in ["ledger", "publication"] {
        let mut missing = serde_json::to_value(&response)?;
        missing
            .as_object_mut()
            .ok_or_else(|| io::Error::other("wire fixture object missing"))?
            .remove(field);
        assert!(
            require_complete_reply(
                &serde_json::to_vec(&missing)?,
                /*request_id*/ 1,
                &profile
            )
            .is_err()
        );
    }
    Ok(())
}

#[tokio::test]
async fn complete_historical_wire_refuses_peer_selected_sources_and_raw_authority()
-> anyhow::Result<()> {
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
        "publication",
    ] {
        let mut altered = serde_json::to_value(&request)?;
        altered[field] = serde_json::json!("peer choice");
        assert!(serde_json::from_value::<HistoricalTaskReadRequestV1>(altered).is_err());
    }
    let (publication, ledger, _, _) = crate::circuit_task::publication_data_fixture().await?;
    let response = HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: request.profile.clone(),
        data_cut: Digest32::of_bytes(b"complete data").to_string(),
        ledger,
        publication,
    };
    let mut bytes = serde_json::to_vec(&response)?;
    bytes.extend_from_slice(b"{}");
    assert!(require_complete_reply(&bytes, /*request_id*/ 1, &request.profile).is_err());
    let bytes = serde_json::to_vec(&response)?;
    assert!(bytes.len() <= WIRE_BOUND);
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

fn task_response_for_codec_test(
    profile: &str,
    ledger: RootHistoricalLedgerReadDataV1,
    publication: RootHistoricalTaskPublicationDataV1,
) -> HistoricalTaskReadResponseV1 {
    HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: profile.into(),
        data_cut: Digest32::of_bytes(b"codec-only original complete cut").to_string(),
        ledger,
        publication,
    }
}

// Controlled Source/Cell execution plus the existing untrusted Ledger DTO.
// These are codec/transport regressions, not native-owner qualification.
#[tokio::test]
async fn complete_task_accepts_large_original_data_and_retains_refusal_bounds() -> anyhow::Result<()>
{
    let profile = Digest32::of_bytes(b"bounded task recipient").to_string();
    let (publication, ledger, _, _) = crate::circuit_task::publication_data_fixture().await?;
    let baseline = task_response_for_codec_test(&profile, ledger, publication);
    let baseline_length = serde_json::to_vec(&baseline)?.len();

    // Grow the actual Source input before execution and canonical projection.
    // Base64 expands each three additional input bytes to four encoded bytes.
    let additional = (WIRE_BOUND + 1024)
        .saturating_sub(baseline_length)
        .div_ceil(4)
        * 3
        + 12;
    let mut observation = b"original data observation".to_vec();
    observation.resize(observation.len() + additional, b'x');
    let (publication, ledger, _, _) =
        crate::circuit_task::publication_data_fixture_with_observation(&observation).await?;
    ledger.validate_data()?;
    publication.validate_against(&ledger)?;
    assert!(serde_json::to_vec(&ledger)?.len() <= RootHistoricalLedgerReadDataV1::JSON_BOUND);
    assert!(
        serde_json::to_vec(&publication)?.len() <= RootHistoricalTaskPublicationDataV1::JSON_BOUND
    );
    let response = task_response_for_codec_test(&profile, ledger, publication);
    let bytes = serde_json::to_vec(&response)?;
    assert!(bytes.len() > WIRE_BOUND);
    assert!(bytes.len() <= TASK_RESPONSE_BOUND);
    let decoded = require_complete_reply(&bytes, /*request_id*/ 1, &profile)?;
    assert_eq!(decoded.ledger, response.ledger);
    assert_eq!(decoded.publication, response.publication);

    assert!(require_complete_reply(&bytes[..bytes.len() - 1], /*request_id*/ 1, &profile).is_err());
    assert!(
        require_complete_reply(
            &bytes,
            /*request_id*/ 1,
            &Digest32::of_bytes(b"another bounded recipient").to_string(),
        )
        .is_err()
    );

    // Trailing whitespace is valid JSON: only the outer byte bound is exceeded.
    let mut oversized = bytes.clone();
    oversized.resize(TASK_RESPONSE_BOUND + 1, b' ');
    assert!(serde_json::from_slice::<HistoricalTaskReadResponseV1>(&oversized).is_ok());
    assert!(require_complete_reply(&oversized, /*request_id*/ 1, &profile).is_err());

    // Child mutations are untrusted negative inputs. Their rejection is not
    // asserted to have only one possible semantic cause.
    for (child_name, field, bound) in [
        (
            "ledger",
            "ledger_image_bytes",
            RootHistoricalLedgerReadDataV1::JSON_BOUND,
        ),
        (
            "publication",
            "result",
            RootHistoricalTaskPublicationDataV1::JSON_BOUND,
        ),
    ] {
        let mut changed = serde_json::to_value(&baseline)?;
        changed[child_name][field] = serde_json::json!("");
        let fixed = serde_json::to_vec(&changed[child_name])?.len();
        assert!(fixed <= bound);
        let characters = (bound + 1 - fixed).div_ceil(4) * 4;
        changed[child_name][field] = serde_json::json!("A".repeat(characters));
        assert!(serde_json::to_vec(&changed[child_name])?.len() > bound);
        let bytes = serde_json::to_vec(&changed)?;
        assert!(bytes.len() <= TASK_RESPONSE_BOUND);
        assert!(serde_json::from_slice::<HistoricalTaskReadResponseV1>(&bytes).is_ok());
        assert!(require_complete_reply(&bytes, /*request_id*/ 1, &profile).is_err());
    }

    // The original publication constructor must still reject an oversized
    // component after the Source/Cell construction has actually completed.
    let error =
        crate::circuit_task::publication_data_fixture_with_observation(&vec![b'x'; 16 * 1024])
            .await
            .err()
            .ok_or_else(|| anyhow::anyhow!("oversized publication fixture was accepted"))?;
    assert_eq!(
        error.to_string(),
        "publication DTO constructor rejected fixture"
    );
    Ok(())
}

#[tokio::test]
async fn task_envelope_matches_actual_serializer_and_other_operations_keep_original_bound()
-> anyhow::Result<()> {
    let profile = Digest32::of_bytes(b"actual serialized envelope").to_string();
    let (publication, ledger, _, _) = crate::circuit_task::publication_data_fixture().await?;
    let child_bytes = serde_json::to_vec(&ledger)?.len() + serde_json::to_vec(&publication)?.len();
    let mut response = task_response_for_codec_test(&profile, ledger, publication);
    // These are the reviewed v1 values. A sequence range or field change must
    // explicitly update this compatibility review as well as the arithmetic.
    assert_eq!(MAX_READS, 64);
    assert_eq!(TASK_RESPONSE_ENVELOPE_BOUND, 261);
    let mut observed_maximum = 0;
    for request_id in 1..=MAX_READS {
        response.request_id = request_id;
        let bytes = serde_json::to_vec(&response)?;
        let overhead = bytes
            .len()
            .checked_sub(child_bytes)
            .ok_or_else(|| anyhow::anyhow!("serialized component lengths exceed reply"))?;
        assert!(overhead <= TASK_RESPONSE_ENVELOPE_BOUND);
        observed_maximum = observed_maximum.max(overhead);
        require_complete_reply(&bytes, request_id, &profile)?;
    }
    assert_eq!(observed_maximum, TASK_RESPONSE_ENVELOPE_BOUND);
    assert_eq!(
        TASK_RESPONSE_BOUND,
        RootHistoricalLedgerReadDataV1::JSON_BOUND
            + RootHistoricalTaskPublicationDataV1::JSON_BOUND
            + observed_maximum
    );
    assert_eq!(
        HistoricalReadOperationV1::Task.response_bound(),
        TASK_RESPONSE_BOUND
    );
    for operation in [
        HistoricalReadOperationV1::LearningTrust,
        HistoricalReadOperationV1::PostAFrozenLearning,
        HistoricalReadOperationV1::AcceptCompletedLearning,
        HistoricalReadOperationV1::CaptureCompletedHistory,
        HistoricalReadOperationV1::ReadCompletedHistory,
    ] {
        assert_eq!(operation.response_bound(), WIRE_BOUND);
        assert_eq!(operation.response_bound(), 16_384);
    }
    Ok(())
}
