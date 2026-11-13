//! Real Initial producer, canonical Automation trace and private UDS. These
//! component checks use explicit engineering keys, not ordinary Root or B
//! qualification, and never fabricate the producer's pending count.

use codex_hepta_agent_protocol::ObjectiveAdmissionOutcome;
use codex_hepta_agent_protocol::ObjectiveAdmissionQuery;
use codex_hepta_agent_protocol::Q24OriginalInitialTaskCompletionV1;
use codex_hepta_agent_protocol::Q24OriginalInitialTaskProgressV1;
use codex_hepta_automation::CircuitExitV2;
use pretty_assertions::assert_eq;

use super::*;

fn original_owner_bytes(f: &Fixture) -> anyhow::Result<Vec<Vec<u8>>> {
    let mut bytes = f.task_bytes()?;
    bytes.extend(f.learning_bytes()?);
    bytes.push(fs::read(
        f.session
            .runtime
            .identity
            .home_root
            .join("objective-run-start-v1/journal.bin"),
    )?);
    Ok(bytes)
}

#[tokio::test]
async fn original_initial_progress_reads_actual_success_without_resubmission_or_outcome()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "initial-progress-real-success",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let before = original_owner_bytes(&f)?;
    let store = f.session.runtime.state.circuit_task_store()?;
    let trace = store
        .bounded_circuit_committed_trace(&f.session.request.body.run_id)
        .await?
        .expect("actual executed Initial trace");
    assert_eq!(trace.run().outcome(), Some(CircuitExitV2::Succeeded));
    assert_eq!(trace.run().unresolved(), 0);
    let ObjectiveAdmissionOutcome::Published { publication } = control
        .client
        .objective_admission(ObjectiveAdmissionQuery {
            request: f.session.request.clone(),
            anchor: None,
        })
        .await?
    else {
        anyhow::bail!("actual original RunStart publication required");
    };
    let observation = control.client.original_q24_task_observation().await?;
    let expected = Q24OriginalInitialTaskProgressV1::Completed {
        data: Box::new(Q24OriginalInitialTaskCompletionV1 {
            admission: *publication,
            observation,
            circuit_revision: trace.run().revision(),
            circuit_history_digest: trace.history_digest().as_str().to_owned(),
        }),
    };
    for _ in 0..2 {
        assert_eq!(
            control
                .client
                .original_q24_initial_task_progress(f.session.request.clone())
                .await?,
            expected
        );
    }
    let wire = serde_json::to_value(AgentdPayload::Q24OriginalInitialTaskProgress(expected))?;
    assert_eq!(wire["type"], "q24_original_initial_task_progress");
    assert_eq!(wire["status"], "completed");
    let mut extra = wire;
    extra["data"]["inferred_success"] = serde_json::json!(true);
    assert!(serde_json::from_value::<AgentdPayload>(extra).is_err());
    assert_eq!(original_owner_bytes(&f)?, before);
    assert_eq!(
        store
            .bounded_circuit_committed_trace(&f.session.request.body.run_id)
            .await?,
        Some(trace)
    );
    assert!(matches!(
        f.producer.readback()?,
        Status::AwaitingOutcome { .. }
    ));
    f.no_outbox().await?;
    control.stop().await?;
    f.session.stop().await
}

#[tokio::test]
async fn original_initial_progress_rejects_changed_exact_request_and_withdrawn_source()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "initial-progress-exact-request",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let control = Control::open(&mut f).await?;
    let request = serde_json::to_value(&f.session.request)?;
    let before = original_owner_bytes(&f)?;
    for path in [
        "/issuer_id",
        "/key_epoch",
        "/message_id",
        "/sequence",
        "/expires_at_ms",
        "/signature_hex",
        "/body/spawn_generation",
        "/body/run_id",
        "/body/objective_revision",
        "/body/source_envelope_json",
        "/body/runtime_body_digest",
        "/body/preference_state_digest",
        "/body/model_tuple_digest",
        "/body/prompt_registry_digest",
        "/body/artifact_set_digest",
        "/body/authority_epoch",
    ] {
        let mut changed = request.clone();
        let field = changed.pointer_mut(path).expect("actual request field");
        *field = match field {
            serde_json::Value::Number(value) => serde_json::json!(value.as_u64().unwrap() + 1),
            serde_json::Value::String(value) => serde_json::json!(format!("{value}x")),
            _ => anyhow::bail!("unexpected original request field {path}"),
        };
        assert!(
            control
                .client
                .original_q24_initial_task_progress(serde_json::from_value(changed)?)
                .await
                .is_err(),
            "changed request {path} must fail, not become InFlight"
        );
        assert_eq!(original_owner_bytes(&f)?, before);
    }
    assert!(matches!(
        control
            .client
            .original_q24_initial_task_progress(f.session.request.clone())
            .await?,
        Q24OriginalInitialTaskProgressV1::Completed { .. }
    ));
    f.session
        .source
        .withdraw_for_dataset_test(&f.publication.original_record().snapshot.run_id)?;
    let withdrawn = original_owner_bytes(&f)?;
    assert!(
        control
            .client
            .original_q24_initial_task_progress(f.session.request.clone())
            .await
            .is_err()
    );
    assert_eq!(original_owner_bytes(&f)?, withdrawn);
    control.stop().await?;
    f.session.stop().await
}

#[tokio::test]
async fn original_initial_progress_requires_installed_current_producer() -> anyhow::Result<()> {
    for automatic in [false, true] {
        let mut f = Fixture::new(
            "initial-progress-current-owner",
            /*lifetime*/ 600,
            automatic,
        )
        .await?;
        let control = Control::open(&mut f).await?;
        if automatic {
            control
                .client
                .original_q24_initial_task_progress(f.session.request.clone())
                .await?;
            f.session.runtime.state.mark_fenced();
        }
        let before = original_owner_bytes(&f)?;
        assert!(
            control
                .client
                .original_q24_initial_task_progress(f.session.request.clone())
                .await
                .is_err()
        );
        assert_eq!(original_owner_bytes(&f)?, before);
        control.stop().await?;
        f.session.stop().await?;
    }
    Ok(())
}

#[test]
fn original_initial_progress_pending_wire_is_strict_data_only() -> anyhow::Result<()> {
    // Wire validation alone does not establish any actual work in flight.
    let pending = serde_json::json!({
        "type": "q24_original_initial_task_progress", "status": "in_flight"
    });
    assert_eq!(
        serde_json::from_value::<AgentdPayload>(pending.clone())?,
        AgentdPayload::Q24OriginalInitialTaskProgress(
            Q24OriginalInitialTaskProgressV1::InFlight {}
        )
    );
    for (field, value) in [
        ("data", serde_json::json!({})),
        ("retry", serde_json::json!(true)),
        ("status", serde_json::json!("unknown")),
    ] {
        let mut changed = pending.clone();
        changed[field] = value;
        assert!(serde_json::from_value::<AgentdPayload>(changed).is_err());
    }
    Ok(())
}
