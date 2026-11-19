use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tokio::sync::Mutex;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

struct ObservationOnlyTarget {
    observation: ProductionTerminalObservation,
    request: Mutex<Option<ProductionDispatchRequest>>,
}

impl ProductionOutboxTarget for ObservationOnlyTarget {
    fn dispatch<'a>(&'a self, _request: ProductionDispatchRequest) -> ProductionDispatchFuture<'a> {
        panic!("terminal reconciliation must never redispatch");
    }
}

impl crate::FinalUseProductionOutboxTarget for ObservationOnlyTarget {
    fn destination_id(&self) -> &str {
        COGNITIVE_SOURCE_DESTINATION_V1
    }

    fn observe_terminal<'a>(
        &'a self,
        request: &'a ProductionDispatchRequest,
    ) -> ProductionTerminalObservationFuture<'a> {
        Box::pin(async move {
            *self.request.lock().await = Some(request.clone());
            self.observation.clone()
        })
    }
}

pub(super) fn expected_journal(request: &ProductionDispatchRequest, observation: Value) -> Value {
    json!({
        "schema_version": 1,
        "namespace": "production_terminal_observation",
        "lease_id": request.lease_id,
        "operation_id": request.occurrence_key,
        "destination_id": request.operation_destination_id,
        "operation_semantic_sha256": request.operation_semantic_sha256,
        "payload_sha256": request.payload_sha256,
        "operation_digest": request.operation_digest,
        "observation": observation,
    })
}

pub(super) async fn retained_journal(
    store: &CognitiveStore,
    operation_id: &str,
) -> TestResult<Value> {
    let (payload, digest): (String, String) = sqlx::query_as(
        "SELECT payload_json, payload_sha256 FROM cognitive_local_events
         WHERE occurrence_key = ?
           AND event_kind IN ('reconcile_committed', 'reconcile_rejected')",
    )
    .bind(operation_id)
    .fetch_one(&store.pool)
    .await?;
    assert_eq!(Sha256Digest::for_bytes(payload.as_bytes()).as_str(), digest);
    Ok(serde_json::from_str(&payload)?)
}

async fn indeterminate_writer(
    temp: &TempDir,
    operation_id: &str,
) -> TestResult<(CognitiveStore, ProductionDurableWriter)> {
    let store = store(temp).await;
    let owner = store.owner_agent_id().clone();
    let writer = ProductionDurableWriter::open(
        store.clone(),
        production_authority(owner.clone()),
        &AllowVerifier,
        "production:terminal-observation",
        1,
    )
    .await?;
    let (draft, payload) = source_payload(operation_id, b"original immutable request");
    writer
        .prepare_operation(
            operation(&owner, operation_id, &payload, &draft, None),
            COGNITIVE_SOURCE_TOPIC_V1,
            payload,
        )
        .await?;
    writer.mark_indeterminate(operation_id, "ack lost").await?;
    Ok((store, writer))
}

#[tokio::test]
async fn terminal_reconciliation_retains_rejection_reason_and_exact_request_binding() -> TestResult
{
    for (observation, expected) in [
        (
            ProductionTerminalObservation::NotApplied {
                reason: "destination revision/CAS mismatch".to_string(),
            },
            json!({"disposition": "not_applied", "reason": "destination revision/CAS mismatch"}),
        ),
        (
            ProductionTerminalObservation::Quarantined {
                reason: "destination proof belongs to another payload".to_string(),
            },
            json!({"disposition": "quarantined", "reason": "destination proof belongs to another payload"}),
        ),
    ] {
        let temp = TempDir::new()?;
        let operation_id = "operation:terminal-rejection";
        let (store, writer) = indeterminate_writer(&temp, operation_id).await?;
        let target = ObservationOnlyTarget {
            observation,
            request: Mutex::new(None),
        };
        assert_eq!(writer.reconcile_target_batch(&target, 1).await?, 1);
        let request = target
            .request
            .lock()
            .await
            .clone()
            .ok_or("missing request")?;
        let expected = expected_journal(&request, expected);
        assert_eq!(retained_journal(&store, operation_id).await?, expected);
        assert_eq!(
            writer.status(operation_id).await?,
            LocalOutcomeState::Rejected
        );

        // A conflicting later observation cannot overwrite the original
        // terminal proof or cause another target entry.
        let conflicting = ObservationOnlyTarget {
            observation: ProductionTerminalObservation::Applied {
                receipt: "different later receipt".to_string(),
            },
            request: Mutex::new(None),
        };
        assert_eq!(writer.reconcile_target_batch(&conflicting, 1).await?, 0);
        assert_eq!(retained_journal(&store, operation_id).await?, expected);
    }
    Ok(())
}

#[tokio::test]
async fn invalid_terminal_observation_cannot_publish_a_bare_terminal_flag() -> TestResult {
    let temp = TempDir::new()?;
    let operation_id = "operation:invalid-terminal-observation";
    let (store, writer) = indeterminate_writer(&temp, operation_id).await?;
    let original_events: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events")
        .fetch_one(&store.pool)
        .await?;
    for receipt in [
        String::new(),
        "\0".to_string(),
        "x".repeat(65_537),
        // The input itself fits, but JSON escaping exceeds the original
        // complete-event limit. This must fail before publishing terminality.
        "\n".repeat(32_768) + "receipt",
    ] {
        let target = ObservationOnlyTarget {
            observation: ProductionTerminalObservation::Applied { receipt },
            request: Mutex::new(None),
        };
        assert!(writer.reconcile_target_batch(&target, 1).await.is_err());
        assert_eq!(
            writer.status(operation_id).await?,
            LocalOutcomeState::Indeterminate
        );
        let events: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events")
            .fetch_one(&store.pool)
            .await?;
        assert_eq!(events, original_events);
    }
    let unavailable = ObservationOnlyTarget {
        observation: ProductionTerminalObservation::Unavailable {
            reason: "observer disconnected".to_string(),
        },
        request: Mutex::new(None),
    };
    assert_eq!(writer.reconcile_target_batch(&unavailable, 1).await?, 0);
    assert_eq!(
        writer.status(operation_id).await?,
        LocalOutcomeState::Indeterminate
    );
    Ok(())
}
