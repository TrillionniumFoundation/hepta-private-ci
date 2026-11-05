use super::*;
use crate::ClientRequest;
use crate::ClientRequestSerializationScope;
use crate::ExperimentalApi;
use crate::JSONRPCRequest;
use crate::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn observed_termination_requires_a_positive_u32_budget() -> anyhow::Result<()> {
    for invalid in [
        json!(null),
        json!(0),
        json!(-1),
        json!(0.5),
        json!(4_294_967_296_u64),
    ] {
        let request: JSONRPCRequest = serde_json::from_value(json!({
            "id": 7,
            "method": "thread/backgroundTerminals/terminateObserved",
            "params": {
                "threadId": "thr_123",
                "processId": "42",
                "observationTimeoutMs": invalid
            }
        }))?;
        assert!(ClientRequest::try_from(request).is_err());
    }
    let missing: JSONRPCRequest = serde_json::from_value(json!({
        "id": 7,
        "method": "thread/backgroundTerminals/terminateObserved",
        "params": {"threadId": "thr_123", "processId": "42"}
    }))?;
    assert!(ClientRequest::try_from(missing).is_err());
    Ok(())
}

#[test]
fn observed_termination_keeps_experimental_thread_serialization() -> anyhow::Result<()> {
    let request = ClientRequest::ThreadBackgroundTerminalsTerminateObserved {
        request_id: RequestId::Integer(7),
        params: ThreadBackgroundTerminalsTerminateObservedParams {
            thread_id: "thr_123".to_string(),
            process_id: "42".to_string(),
            observation_timeout_ms: 1,
        },
    };
    assert_eq!(
        request.experimental_reason(),
        Some("thread/backgroundTerminals/terminateObserved")
    );
    assert!(matches!(
        request.serialization_scope(),
        Some(ClientRequestSerializationScope::Thread { thread_id })
            if thread_id == "thr_123"
    ));
    let wire = serde_json::to_value(&request)?;
    assert_eq!(
        wire,
        json!({
            "id": 7,
            "method": "thread/backgroundTerminals/terminateObserved",
            "params": {"threadId": "thr_123", "processId": "42", "observationTimeoutMs": 1}
        })
    );
    let parsed = ClientRequest::try_from(serde_json::from_value::<JSONRPCRequest>(wire)?)?;
    assert!(matches!(
        parsed,
        ClientRequest::ThreadBackgroundTerminalsTerminateObserved { .. }
    ));
    Ok(())
}

#[test]
fn not_confirmed_is_a_distinct_closed_wire_status() -> anyhow::Result<()> {
    let response = ThreadBackgroundTerminalsTerminateObservedResponse {
        status: ThreadBackgroundTerminalsTerminateObservedStatus::NotConfirmed,
    };
    assert_eq!(
        serde_json::to_value(response)?,
        json!({"status": "notConfirmed"})
    );
    assert!(
        serde_json::from_value::<ThreadBackgroundTerminalsTerminateObservedResponse>(
            json!({"status": "closed"})
        )
        .is_err()
    );
    Ok(())
}
