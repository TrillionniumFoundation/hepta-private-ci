use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn unavailable_history_preserves_cursor_and_allows_other_inbox_recovery() -> anyhow::Result<()>
{
    let temp = TempDir::new()?;
    let agent = agent_id();
    let layout = layout(&temp, &agent);
    let store = open_bound_store(&layout).await?;
    let fake = FakeRuntimeBridge::new(agent.clone());
    let runtime = MatrixRuntime::new(store, fake.clone());
    let mut turns = Vec::new();
    for (event, turn) in [("$budget-first", "turn-1"), ("$budget-second", "turn-2")] {
        let event = event_id(event);
        runtime
            .store()
            .ingest_inbox(&text_inbox(
                event.clone(),
                br#"{"msgtype":"m.text","body":"offline completion"}"#,
            ))
            .await?;
        runtime.process_event(&event, /*now_ms*/ 20).await?;
        let client = client_user_message_id(&agent, &room_id(), &event);
        fake.admit(&client, turn);
        if turn == "turn-1" {
            let MatrixDispatchOutcome::Admitted { dispatch } =
                runtime.process_event(&event, /*now_ms*/ 25).await?
            else {
                panic!("expected admission");
            };
            runtime
                .store()
                .advance_turn_recovery_cursor(&dispatch, /*expected*/ None, Some("0"))
                .await?;
        }
        turns.push(persisted_turn(
            turn,
            TurnStatus::Completed,
            terminal_items(&client),
        ));
    }
    fake.set_persisted_turns(turns);
    fake.state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .history_refusals = 1;
    let recovered = runtime.recover_pending(/*limit*/ 10, /*now_ms*/ 40).await?;
    let [
        MatrixDispatchOutcome::Admitted { dispatch },
        MatrixDispatchOutcome::Completed { .. },
    ] = recovered.outcomes.as_slice()
    else {
        panic!(
            "only the unavailable dispatch must remain admitted: {:?}",
            recovered.outcomes
        );
    };
    assert_eq!(
        runtime.store().turn_recovery_cursor(dispatch).await?,
        Some("0".to_string())
    );
    let outbox = runtime.store().pending_outbox(/*limit*/ 10).await?;
    assert_eq!(
        outbox
            .iter()
            .filter(|row| row.kind == OutboxKind::Terminal)
            .count(),
        1
    );
    // A later complete observation recovers the pending dispatch without a new admission.
    let saved_dispatch = dispatch.clone();
    runtime.store().close().await;
    drop(runtime);
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened.turn_recovery_cursor(&saved_dispatch).await?,
        Some("0".to_string())
    );
    let runtime = MatrixRuntime::new(reopened, fake.clone());
    let before = fake.admissions();
    let recovered = runtime.recover_pending(/*limit*/ 10, /*now_ms*/ 50).await?;
    assert!(matches!(
        recovered.outcomes.as_slice(),
        [MatrixDispatchOutcome::Completed { .. }]
    ));
    assert_eq!(fake.admissions(), before);
    assert_eq!(
        fake.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .history_requests
            .last()
            .map(|(_, cursor)| cursor.clone()),
        Some(Some("0".to_string()))
    );
    assert_eq!(
        runtime
            .store()
            .pending_outbox(/*limit*/ 10)
            .await?
            .iter()
            .filter(|row| row.kind == OutboxKind::Terminal)
            .count(),
        2
    );
    runtime.store().close().await;
    Ok(())
}
