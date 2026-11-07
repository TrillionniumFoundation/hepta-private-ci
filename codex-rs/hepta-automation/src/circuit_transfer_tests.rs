//! Synthetic receipt bytes exercise the actual AutomationStore transaction and
//! owner fences. These are not measured Generation or model qualification data.

use pretty_assertions::assert_eq;

use super::claim;
use super::pending;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::fence;
use crate::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

#[derive(Debug, Eq, PartialEq)]
struct Cut {
    run: serde_json::Value,
    events: Vec<String>,
    inputs: Vec<(i64, String, Vec<u8>)>,
    transfers: Vec<(i64, String, Vec<u8>, Vec<u8>)>,
}

impl Cut {
    async fn read(store: &AutomationStore) -> TestResult<Self> {
        Ok(Self {
            run: serde_json::to_value(store.bounded_circuit_run("run-1").await?)?,
            events: sqlx::query_scalar("SELECT event_json FROM circuit_v2_events ORDER BY seq")
                .fetch_all(store.taskflow_pool()).await?,
            inputs: sqlx::query_as("SELECT activation_id, schema_id, input_bytes FROM circuit_v2_computation_inputs ORDER BY activation_id")
                .fetch_all(store.taskflow_pool()).await?,
            transfers: sqlx::query_as("SELECT activation_id, schema_id, receipt_bytes, output_bytes FROM circuit_v2_computation_transfers ORDER BY activation_id")
                .fetch_all(store.taskflow_pool()).await?,
        })
    }
}

async fn prepared(
    output: &[u8],
) -> TestResult<(
    tempfile::TempDir,
    AutomationStore,
    CircuitCommandV2,
    CircuitComputationTransferV1,
)> {
    let (directory, store, dispatched) = pending().await;
    let input =
        CircuitComputationInputV1::new("step-fixture.v1", b"original full step bytes".to_vec())?;
    let token = store
        .claim_circuit_computation_with_input(&claim(&dispatched, "claim"), &input)
        .await?;
    let transfer = CircuitComputationTransferV1::new(
        "receipt-fixture.v1",
        br#"{"cost":[{"wall_micros":3,"cpu_micros":null}],"original_intent":"fixture"}"#.to_vec(),
        output.to_vec(),
    )?;
    let mut complete = completion(&dispatched.dispatches[0], &["done"], "result");
    complete.receipt_digest = transfer.digest()?;
    complete.output_digest = transfer.output_digest();
    let command = CircuitCommandV2 {
        run_id: "run-1".into(),
        command_id: "complete-transfer".into(),
        fence: fence(/*generation*/ 1),
        expected_revision: token.observed_revision(),
        now_ms: 13,
        event: CircuitEventV2::Complete {
            completion: complete,
        },
    };
    Ok((directory, store, command, transfer))
}

#[tokio::test]
async fn exact_transfer_survives_lost_completion_ack_and_terminal_cold_reopen() -> TestResult {
    let (_directory, store, command, transfer) = prepared(b"\0committed output\xff\n").await?;
    assert_eq!(
        store
            .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
            .await?,
        None
    );
    let completed = store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    assert_eq!(
        (
            completed.run.budget().spent(),
            completed.run.budget().reserved(),
            completed.run.unresolved()
        ),
        (3, 0, 0)
    );
    let finished = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "exit".into(),
            fence: command.fence.clone(),
            expected_revision: completed.run.revision(),
            now_ms: 14,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await?;
    assert_eq!(finished.run.outcome(), Some(CircuitExitV2::Succeeded));
    let before = Cut::read(&store).await?;
    let root = store.path().parent().expect("root").to_path_buf();
    let agent = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let store = AutomationStore::open_root(root, agent).await?;
    assert_eq!(
        store
            .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
            .await?,
        Some(transfer.clone())
    );
    assert_eq!(
        store
            .complete_circuit_computation_with_transfer(&command, &transfer)
            .await?,
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: finished.run,
            dispatches: vec![],
        }
    );
    assert!(
        store
            .recover_circuit_computation(
                "run-1",
                /*activation_id*/ 1,
                &command.fence,
                /*now_ms*/ 15
            )
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    assert_eq!(
        before.transfers,
        vec![(
            1,
            transfer.schema().into(),
            transfer.receipt_bytes().to_vec(),
            transfer.output_bytes().to_vec()
        )]
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn concurrent_completion_retries_commit_one_transfer_and_one_original_charge() -> TestResult {
    let (_directory, store, command, transfer) = prepared(b"one transfer").await?;
    let other = AutomationStore::open_root(
        store.path().parent().expect("root").to_path_buf(),
        store.owner_agent_id().clone(),
    )
    .await?;
    let (left, right) = tokio::join!(
        store.complete_circuit_computation_with_transfer(&command, &transfer),
        other.complete_circuit_computation_with_transfer(&command, &transfer),
    );
    let left = left?;
    let right = right?;
    assert_eq!(
        usize::from(left.status == CircuitCommandStatusV2::Applied)
            + usize::from(right.status == CircuitCommandStatusV2::Applied),
        1
    );
    assert_eq!(left.run, right.run);
    assert_eq!(
        (left.run.budget().spent(), left.run.budget().reserved()),
        (3, 0)
    );
    let cut = Cut::read(&store).await?;
    assert_eq!(cut.transfers.len(), 1);
    assert_eq!(cut.events.len(), 4);
    assert_eq!(
        store
            .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
            .await?,
        Some(transfer)
    );
    store.close().await;
    other.close().await;
    Ok(())
}

#[tokio::test]
async fn completion_append_failure_rolls_back_transfer_and_keeps_original_reservation() -> TestResult
{
    let (_directory, store, command, transfer) = prepared(b"owned").await?;
    let before = Cut::read(&store).await?;
    sqlx::query("CREATE TRIGGER reject_transfer_completion BEFORE INSERT ON circuit_v2_events WHEN NEW.seq = 3 BEGIN SELECT RAISE(ABORT, 'injected completion append failure'); END")
        .execute(store.taskflow_pool()).await?;
    assert!(
        store
            .complete_circuit_computation_with_transfer(&command, &transfer)
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    assert_eq!(
        store
            .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
            .await?,
        None
    );
    sqlx::query("DROP TRIGGER reject_transfer_completion")
        .execute(store.taskflow_pool())
        .await?;
    let completed = store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    assert_eq!(
        (
            completed.run.budget().spent(),
            completed.run.budget().reserved()
        ),
        (3, 0)
    );
    assert_eq!(Cut::read(&store).await?.transfers.len(), 1);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn changed_transfer_or_completion_binding_never_changes_history_or_cost() -> TestResult {
    let (_directory, store, command, transfer) = prepared(b"owned").await?;
    let before = Cut::read(&store).await?;
    for changed in [
        CircuitComputationTransferV1::new(
            "changed.v1",
            transfer.receipt_bytes().to_vec(),
            transfer.output_bytes().to_vec(),
        )?,
        CircuitComputationTransferV1::new(
            transfer.schema(),
            b"different cost".to_vec(),
            transfer.output_bytes().to_vec(),
        )?,
        CircuitComputationTransferV1::new(
            transfer.schema(),
            transfer.receipt_bytes().to_vec(),
            b"different output".to_vec(),
        )?,
    ] {
        assert!(
            store
                .complete_circuit_computation_with_transfer(&command, &changed)
                .await
                .is_err()
        );
        assert_eq!(Cut::read(&store).await?, before);
    }
    let mut changed = command.clone();
    changed.expected_revision = 0;
    assert!(
        store
            .complete_circuit_computation_with_transfer(&changed, &transfer)
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    let settled = Cut::read(&store).await?;
    changed = command.clone();
    changed.command_id = "different-completion-command".into();
    assert!(
        store
            .complete_circuit_computation_with_transfer(&changed, &transfer)
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, settled);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn distinct_owner_reconciles_original_claim_after_cancel_without_reconsuming_budget()
-> TestResult {
    let (_directory, store, mut command, transfer) = prepared(b"original after takeover").await?;
    let original_owner = command.fence.clone();
    let run = store.bounded_circuit_run("run-1").await?.expect("run");
    let cancelled = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "cancel".into(),
            fence: original_owner.clone(),
            expected_revision: run.revision(),
            now_ms: 13,
            event: CircuitEventV2::Cancel,
        })
        .await?;
    assert_eq!(
        (
            cancelled.run.budget().spent(),
            cancelled.run.budget().reserved()
        ),
        (0, 5)
    );
    let successor_owner = TaskFlowFence::new(
        store.owner_agent_id().clone(),
        "distinct-successor-process",
        /*owner_epoch*/ 2,
        /*generation*/ 2,
        "distinct-successor-token",
    )?;
    assert_eq!(
        successor_owner.owner_agent_id,
        original_owner.owner_agent_id
    );
    assert_ne!(successor_owner.owner_id, original_owner.owner_id);
    assert_ne!(successor_owner.fencing_token, original_owner.fencing_token);
    assert!(successor_owner.owner_epoch > original_owner.owner_epoch);
    assert!(successor_owner.generation > original_owner.generation);
    let successor = store
        .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
            run_id: "run-1".into(),
            command_id: "takeover".into(),
            fence: successor_owner.clone(),
            expected_revision: cancelled.run.revision(),
            now_ms: 110,
            lease_duration_ms: 100,
        })
        .await?;
    let CircuitEventV2::Complete { completion } = command.event else {
        panic!("original completion")
    };
    command.event = CircuitEventV2::Reconcile { completion };
    command.expected_revision = successor.run.revision();
    command.now_ms = 111;
    let before = Cut::read(&store).await?;
    assert_eq!(
        store
            .complete_circuit_computation_with_transfer(&command, &transfer)
            .await,
        Err(TaskFlowError::StaleFence)
    );
    assert_eq!(Cut::read(&store).await?, before);
    command.fence = successor_owner;
    let settled = store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    assert_eq!(
        (
            settled.run.budget().spent(),
            settled.run.budget().reserved(),
            settled.run.unresolved()
        ),
        (3, 0, 0)
    );
    assert_eq!(
        settled.run.stop_reason(),
        Some(CircuitStopReasonV2::Cancelled)
    );
    assert_eq!(
        store
            .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
            .await?,
        Some(transfer)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn missing_tampered_or_oversized_transfer_is_not_recoverable_evidence() -> TestResult {
    for corruption in ["missing", "receipt", "empty-output-oversize", "orphan"] {
        let output = if corruption == "empty-output-oversize" {
            b"".as_slice()
        } else {
            b"owned".as_slice()
        };
        let (_directory, store, command, transfer) = prepared(output).await?;
        if corruption == "orphan" {
            sqlx::query("INSERT INTO circuit_v2_computation_transfers VALUES (?, 'run-1', 1, 'injected.v1', X'01', X'02')")
                .bind(store.owner_agent_id().as_str()).execute(store.taskflow_pool()).await?;
        } else {
            store
                .complete_circuit_computation_with_transfer(&command, &transfer)
                .await?;
            assert!(
                sqlx::query("UPDATE circuit_v2_computation_transfers SET receipt_bytes = X'02'")
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            assert!(
                sqlx::query("DELETE FROM circuit_v2_computation_transfers")
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            if corruption == "missing" {
                sqlx::query("DROP TRIGGER circuit_v2_transfer_no_delete")
                    .execute(store.taskflow_pool())
                    .await?;
                sqlx::query("DELETE FROM circuit_v2_computation_transfers")
                    .execute(store.taskflow_pool())
                    .await?;
            } else {
                sqlx::query("DROP TRIGGER circuit_v2_transfer_no_update")
                    .execute(store.taskflow_pool())
                    .await?;
                if corruption == "receipt" {
                    sqlx::query(
                        "UPDATE circuit_v2_computation_transfers SET receipt_bytes = X'02'",
                    )
                    .execute(store.taskflow_pool())
                    .await?;
                } else {
                    let mut connection = store.taskflow_pool().acquire().await?;
                    sqlx::query("PRAGMA ignore_check_constraints = ON")
                        .execute(&mut *connection)
                        .await?;
                    sqlx::query("UPDATE circuit_v2_computation_transfers SET output_bytes = zeroblob(65537)").execute(&mut *connection).await?;
                    sqlx::query("PRAGMA ignore_check_constraints = OFF")
                        .execute(&mut *connection)
                        .await?;
                }
            }
        }
        let before = Cut::read(&store).await?;
        assert!(matches!(
            store
                .bounded_circuit_transfer("run-1", /*activation_id*/ 1)
                .await,
            Err(TaskFlowError::Corrupt(_))
        ));
        assert!(matches!(
            store
                .complete_circuit_computation_with_transfer(&command, &transfer)
                .await,
            Err(TaskFlowError::Corrupt(_))
        ));
        assert_eq!(Cut::read(&store).await?, before);
        store.close().await;
    }
    Ok(())
}
