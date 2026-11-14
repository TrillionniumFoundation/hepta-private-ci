//! Real original SQLite reservation after a real elapsed outer budget. Uses
//! the existing explicit fixture owner, without inventing a human/Core proof.
use super::*;
use crate::calculator_deadline::Deadline;
use crate::notes_literal_adapter::prepare_desktop_operation_before;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn elapsed_desktop_budget_cannot_refresh_before_either_original_reservation()
-> Result<(), Box<dyn Error>> {
    let NotesHostFixture {
        directory: _directory,
        config,
        host,
        issuer,
        primary_device,
        ..
    } = notes_host_fixture().await?;
    let writer = host.writer();
    let initial = writer.recovery_anchor().await?;
    let end = Deadline::after(Duration::from_millis(1))?;
    tokio::time::sleep(Duration::from_millis(5)).await;
    assert!(end.remaining().is_err());
    assert!(end.capped(Duration::from_secs(30)).is_err());
    let subject = codex_hepta_types::StableId::new(config.identity().agent_id.as_str())?;
    let generation = codex_hepta_types::Generation::new(1)?;
    let notes = NotesTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 1,
        incarnation: "2".repeat(32),
    };
    let payload = serde_json::json!({"schema_version":1,"action":"replace_note","operation_id":"desktop.expired.notes",
        "destination_id":notes.destination_id(),"target":notes,"expected_revision":0,"text":"过期不得排队"}).to_string();
    let operation = notes_operation_intent(&notes, &payload, subject.clone(), generation)?;
    assert!(
        prepare_desktop_operation_before(&writer, operation, NOTES_REPLACE_TOPIC_V1, payload, end)
            .await
            .is_err()
    );
    let calculator = codex_hepta_memory::CalculatorTargetIdentity {
        session_instance: "1".repeat(32),
        task_id: 2,
        incarnation: "3".repeat(32),
    };
    let payload = serde_json::json!({"schema_version":1,"action":"evaluate","operation_id":"desktop.expired.calculator",
        "destination_id":calculator.destination_id(),"target":calculator,"expected_revision":0,
        "left":"12","operator":"add","right":"30"}).to_string();
    let operation = codex_hepta_memory::calculator_operation_intent(
        &calculator,
        &payload,
        subject,
        generation,
    )?;
    assert!(
        prepare_desktop_operation_before(
            &writer,
            operation,
            codex_hepta_memory::CALCULATOR_EVALUATE_TOPIC_V1,
            payload,
            end
        )
        .await
        .is_err()
    );
    for run in ["desktop.expired.notes", "desktop.expired.calculator"] {
        assert!(writer.retained_operation(run).await?.is_none());
    }
    assert_eq!(writer.recovery_anchor().await?, initial);
    assert_eq!(issuer.requests.load(Ordering::SeqCst), 0);
    assert_eq!(primary_device.installs.load(Ordering::SeqCst), 0);
    Ok(())
}
