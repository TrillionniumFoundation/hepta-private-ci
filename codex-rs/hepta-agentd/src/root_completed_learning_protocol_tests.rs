use pretty_assertions::assert_eq;
use serde_json::json;

use super::*;

fn completed() -> CompletedLearningHistoryResponseV1 {
    CompletedLearningHistoryResponseV1 {
        schema: 1,
        purpose: READ_COMPLETED_PURPOSE.into(),
        request_id: 3,
        profile: "11".repeat(32),
        data_cut: "22".repeat(32),
        completion: OriginalQ24CompletedHistoryDataV1 {
            schema: 1,
            identity_digest: "33".repeat(32),
            root_profile: "11".repeat(32),
            initial: "44".repeat(32),
            frozen_scope: "55".repeat(32),
            terminal_head: "66".repeat(32),
            acceptance: "77".repeat(32),
            current_head: "88".repeat(32),
            successor_record: "99".repeat(32),
            successor_cut: "aa".repeat(32),
        },
    }
}

#[test]
fn completed_history_replies_require_the_requested_phase_and_whole_shape() -> anyhow::Result<()> {
    let response = completed();
    let original = serde_json::to_vec(&response)?;
    assert_eq!(
        require_completed_history_reply(
            &original,
            response.request_id,
            &response.profile,
            HistoricalReadOperationV1::ReadCompletedHistory,
        )?,
        response
    );
    assert!(
        require_completed_history_reply(
            &original,
            response.request_id,
            &response.profile,
            HistoricalReadOperationV1::CaptureCompletedHistory,
        )
        .is_err()
    );
    for operation in [
        HistoricalReadOperationV1::AcceptCompletedLearning,
        HistoricalReadOperationV1::PostAFrozenLearning,
        HistoricalReadOperationV1::Task,
        HistoricalReadOperationV1::LearningTrust,
    ] {
        assert!(
            require_completed_history_reply(
                &original,
                response.request_id,
                &response.profile,
                operation,
            )
            .is_err()
        );
    }
    for (field, value) in [
        ("schema", json!(2)),
        ("purpose", json!(ACCEPT_COMPLETED_PURPOSE)),
        ("request_id", json!(4)),
        ("profile", json!("bb".repeat(32))),
        ("data_cut", json!("00".repeat(32))),
        ("receipt_is_authority", json!(true)),
    ] {
        let mut changed = serde_json::to_value(&response)?;
        changed[field] = value;
        assert!(
            require_completed_history_reply(
                &serde_json::to_vec(&changed)?,
                response.request_id,
                &response.profile,
                HistoricalReadOperationV1::ReadCompletedHistory,
            )
            .is_err(),
            "accepted changed {field}"
        );
    }
    let mut changed = serde_json::to_value(&response)?;
    changed["completion"]["root_profile"] = json!("bb".repeat(32));
    assert!(
        require_completed_history_reply(
            &serde_json::to_vec(&changed)?,
            response.request_id,
            &response.profile,
            HistoricalReadOperationV1::ReadCompletedHistory,
        )
        .is_err()
    );
    for field in [
        "completion",
        "data_cut",
        "profile",
        "request_id",
        "purpose",
        "schema",
    ] {
        let mut changed = serde_json::to_value(&response)?;
        let object = changed
            .as_object_mut()
            .ok_or_else(|| anyhow::anyhow!("response object"))?;
        object.remove(field);
        assert!(
            require_completed_history_reply(
                &serde_json::to_vec(&changed)?,
                response.request_id,
                &response.profile,
                HistoricalReadOperationV1::ReadCompletedHistory,
            )
            .is_err(),
            "accepted absent {field}"
        );
    }
    Ok(())
}

#[test]
fn first_acceptance_data_cannot_supply_a_completed_successor_reply() -> anyhow::Result<()> {
    let history = completed();
    let response = CompletedLearningAcceptanceResponseV1 {
        schema: 1,
        purpose: ACCEPT_COMPLETED_PURPOSE.into(),
        request_id: history.request_id,
        profile: history.profile,
        data_cut: history.data_cut,
        initial: history.completion.initial,
        frozen_scope: history.completion.frozen_scope,
        terminal_head: history.completion.terminal_head,
        acceptance: history.completion.acceptance,
    };
    let bytes = serde_json::to_vec(&response)?;
    assert_eq!(
        require_completed_acceptance_reply(&bytes, response.request_id, &response.profile)?,
        response
    );
    for field in ["initial", "frozen_scope", "terminal_head", "acceptance"] {
        let mut changed = serde_json::to_value(&response)?;
        changed[field] = json!("00".repeat(32));
        assert!(
            require_completed_acceptance_reply(
                &serde_json::to_vec(&changed)?,
                response.request_id,
                &response.profile,
            )
            .is_err()
        );
    }
    let mut changed = serde_json::to_value(&response)?;
    changed["purpose"] = json!(READ_COMPLETED_PURPOSE);
    assert!(
        require_completed_history_reply(
            &serde_json::to_vec(&changed)?,
            response.request_id,
            &response.profile,
            HistoricalReadOperationV1::ReadCompletedHistory,
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn completed_history_has_no_new_payload_budget_or_implicit_capture_mode() -> anyhow::Result<()> {
    let response = completed();
    let bytes = serde_json::to_vec(&response)?;
    for request_id in [0, MAX_READS + 1] {
        assert!(
            require_completed_history_reply(
                &bytes,
                request_id,
                &response.profile,
                HistoricalReadOperationV1::ReadCompletedHistory,
            )
            .is_err()
        );
    }
    for bytes in [Vec::new(), vec![b' '; WIRE_BOUND + 1]] {
        assert!(
            require_completed_history_reply(
                &bytes,
                response.request_id,
                &response.profile,
                HistoricalReadOperationV1::ReadCompletedHistory,
            )
            .is_err()
        );
    }
    for value in [
        json!(true),
        json!(null),
        json!("recover"),
        json!({"read_finalized": true}),
    ] {
        assert!(serde_json::from_value::<CompletedHistoryModeV1>(value).is_err());
    }
    let request = crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1 {
        schema: 1,
        purpose: READ_COMPLETED_PURPOSE.into(),
        request_id: response.request_id,
        profile: response.profile,
    };
    let mut changed = serde_json::to_value(request)?;
    changed["acceptance"] = json!("77".repeat(32));
    assert!(
        serde_json::from_value::<
            crate::root_historical_task_read_protocol::HistoricalTaskReadRequestV1,
        >(changed)
        .is_err()
    );
    Ok(())
}
