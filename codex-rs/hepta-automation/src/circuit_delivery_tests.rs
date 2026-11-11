//! Real store leases and rollback, with the parent's synthetic receipt fixture.
//! This does not assert a Generation ACK, worker run, or Supervisor takeover.

use pretty_assertions::assert_eq;

use super::Cut;
use super::TestResult;
use super::prepared;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_state::CircuitWriterV2;
use crate::*;

async fn terminal() -> TestResult<(
    tempfile::TempDir,
    AutomationStore,
    CircuitRunV2,
    CircuitComputationTransferV1,
)> {
    let (directory, store, command, transfer) = prepared(b"original durable output\0\xff").await?;
    let completed = store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    let finished = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "exit".into(),
            fence: command.fence,
            expected_revision: completed.run.revision(),
            now_ms: 14,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await?;
    assert_eq!(finished.run.outcome(), Some(CircuitExitV2::Succeeded));
    Ok((directory, store, finished.run, transfer))
}

fn takeover(run: &CircuitRunV2) -> TestResult<CircuitLeaseClaimV2> {
    Ok(CircuitLeaseClaimV2 {
        run_id: run.run_id().into(),
        command_id: "delivery-owner-b".into(),
        fence: TaskFlowFence::new(
            fence(/*generation*/ 1).owner_agent_id,
            "distinct-delivery-owner",
            /*owner_epoch*/ 2,
            /*generation*/ 2,
            "delivery-token-b",
        )?,
        expected_revision: run.revision(),
        now_ms: 110,
        lease_duration_ms: 100,
    })
}

#[tokio::test]
async fn terminal_cold_reopen_replaces_delivery_writer_without_reopening_computation() -> TestResult
{
    let (_directory, store, finished, transfer) = terminal().await?;
    let before = Cut::read(&store).await?;
    let observation = store
        .observe_circuit_delivery("run-1", /*activation_id*/ 1)
        .await?
        .expect("retained transfer");
    assert_eq!(observation.transfer(), &transfer);
    assert_eq!(observation.input().bytes(), b"original full step bytes");
    assert_eq!(
        observation.execution_request_digest(),
        &digest("exact-cell-input-with-original-clock")
    );
    assert_eq!(observation.dispatch().activation_id, 1);
    assert_eq!(Cut::read(&store).await?, before);
    let root = store.path().parent().expect("root").to_path_buf();
    let agent = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let store = AutomationStore::open_root(root, agent).await?;
    assert_eq!(
        store
            .observe_circuit_delivery("run-1", /*activation_id*/ 1)
            .await?,
        Some(observation.clone())
    );
    let claim = takeover(&finished)?;
    assert!(store.claim_bounded_circuit_run(&claim).await.is_err());
    assert!(
        store
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &claim.fence,
                /*now_ms*/ 110
            )
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    let claimed = store
        .claim_circuit_delivery_owner(&claim, /*activation_id*/ 1, &transfer.digest()?)
        .await?;
    let mut expected = finished.clone();
    expected.writer = CircuitWriterV2::new(&claim.fence, /*expires_at_ms*/ 210)?;
    expected.revision += 1;
    expected.last_observed_ms = 110;
    assert_eq!(
        claimed,
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::Applied,
            run: expected.clone(),
            dispatches: vec![]
        }
    );
    let after = Cut::read(&store).await?;
    assert_eq!(
        (&after.inputs, &after.transfers),
        (&before.inputs, &before.transfers)
    );
    assert_eq!(after.events.len(), before.events.len() + 1);
    let admitted = store
        .recover_circuit_delivery(
            "run-1",
            /*activation_id*/ 1,
            &claim.fence,
            /*now_ms*/ 111,
        )
        .await?;
    assert_eq!(admitted.fence(), &claim.fence);
    assert_eq!(
        (admitted.observed_at_ms(), admitted.lease_expires_at_ms()),
        (111, 210)
    );
    assert_eq!(admitted.observation().transfer(), &transfer);
    assert_eq!(admitted.observation().input(), observation.input());
    assert_ne!(
        admitted.observation().checkpoint(),
        observation.checkpoint()
    );
    assert!(matches!(
        store
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &fence(/*generation*/ 1),
                /*now_ms*/ 111
            )
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    assert!(
        store
            .recover_circuit_computation(
                "run-1",
                /*activation_id*/ 1,
                &claim.fence,
                /*now_ms*/ 111
            )
            .await
            .is_err()
    );
    assert_eq!(
        store
            .claim_circuit_delivery_owner(&claim, /*activation_id*/ 1, &transfer.digest()?)
            .await?,
        CircuitCommandReceiptV2 {
            status: CircuitCommandStatusV2::AlreadyApplied,
            run: expected,
            dispatches: vec![]
        }
    );
    assert_eq!(Cut::read(&store).await?, after);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn delivery_lease_preserves_original_fence_clock_and_duration_rejections() -> TestResult {
    let (_directory, store, finished, transfer) = terminal().await?;
    let original = takeover(&finished)?;
    let before = Cut::read(&store).await?;
    let mut variants = vec![];
    let mut changed = original.clone();
    changed.now_ms = 109;
    variants.push(changed);
    let mut changed = original.clone();
    changed.now_ms = 13;
    variants.push(changed);
    let mut changed = original.clone();
    changed.lease_duration_ms = 0;
    variants.push(changed);
    let mut changed = original.clone();
    changed.lease_duration_ms = 3_600_001;
    variants.push(changed);
    let mut changed = original.clone();
    changed.now_ms = u64::MAX;
    variants.push(changed);
    let mut changed = original.clone();
    changed.fence.generation = 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.fence.owner_epoch = 0;
    variants.push(changed);
    let mut changed = original.clone();
    changed.expected_revision -= 1;
    variants.push(changed);
    let mut changed = original.clone();
    changed.fence.owner_agent_id =
        codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
    variants.push(changed);
    for claim in variants {
        assert!(
            store
                .claim_circuit_delivery_owner(&claim, /*activation_id*/ 1, &transfer.digest()?)
                .await
                .is_err()
        );
        assert_eq!(Cut::read(&store).await?, before);
    }
    assert!(
        store
            .claim_circuit_delivery_owner(
                &original,
                /*activation_id*/ 1,
                &digest("changed transfer")
            )
            .await
            .is_err()
    );
    assert!(
        store
            .claim_circuit_delivery_owner(&original, /*activation_id*/ 2, &transfer.digest()?)
            .await
            .is_err()
    );
    assert!(
        store
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &fence(/*generation*/ 1),
                /*now_ms*/ 110
            )
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn uncompleted_or_nonterminal_work_never_uses_terminal_delivery_takeover() -> TestResult {
    let (_directory, store, command, transfer) = prepared(b"output").await?;
    let before = Cut::read(&store).await?;
    assert_eq!(
        store
            .observe_circuit_delivery("run-1", /*activation_id*/ 1)
            .await?,
        None
    );
    assert!(
        store
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &command.fence,
                /*now_ms*/ 13
            )
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    let complete = store
        .complete_circuit_computation_with_transfer(&command, &transfer)
        .await?;
    assert_eq!(complete.run.outcome(), None);
    let before = Cut::read(&store).await?;
    assert!(
        store
            .claim_circuit_delivery_owner(
                &takeover(&complete.run)?,
                /*activation_id*/ 1,
                &transfer.digest()?
            )
            .await
            .is_err()
    );
    // Delivery under the still-live ordinary writer is allowed; minting it is read-only.
    let token = store
        .recover_circuit_delivery(
            "run-1",
            /*activation_id*/ 1,
            &command.fence,
            /*now_ms*/ 14,
        )
        .await?;
    assert_eq!(token.observation().transfer(), &transfer);
    assert_eq!(Cut::read(&store).await?, before);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn concurrent_terminal_delivery_takeovers_choose_one_full_owner_identity() -> TestResult {
    let (_directory, store, finished, transfer) = terminal().await?;
    let other = AutomationStore::open_root(
        store.path().parent().expect("root").to_path_buf(),
        store.owner_agent_id().clone(),
    )
    .await?;
    let left = takeover(&finished)?;
    let mut right = left.clone();
    right.command_id = "delivery-owner-c".into();
    right.fence.owner_id = "different-racing-process".into();
    right.fence.fencing_token = "delivery-token-c".into();
    let transfer_digest = transfer.digest()?;
    let before = Cut::read(&store).await?;
    let (a, b) = tokio::join!(
        store.claim_circuit_delivery_owner(&left, /*activation_id*/ 1, &transfer_digest),
        other.claim_circuit_delivery_owner(&right, /*activation_id*/ 1, &transfer_digest)
    );
    let (winner, loser) = match (a, b) {
        (Ok(receipt), Err(_)) => {
            assert_eq!(receipt.status, CircuitCommandStatusV2::Applied);
            (&left, &right)
        }
        (Err(_), Ok(receipt)) => {
            assert_eq!(receipt.status, CircuitCommandStatusV2::Applied);
            (&right, &left)
        }
        pair => panic!("exactly one owner must win: {pair:?}"),
    };
    let token = store
        .recover_circuit_delivery(
            "run-1",
            /*activation_id*/ 1,
            &winner.fence,
            /*now_ms*/ 111,
        )
        .await?;
    assert_eq!(token.fence(), &winner.fence);
    assert!(matches!(
        other
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &loser.fence,
                /*now_ms*/ 111
            )
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    let after = Cut::read(&store).await?;
    assert_eq!(
        (&after.inputs, &after.transfers),
        (&before.inputs, &before.transfers)
    );
    assert_eq!(after.events.len(), before.events.len() + 1);
    assert_eq!(
        store
            .bounded_circuit_run("run-1")
            .await?
            .expect("run")
            .budget(),
        finished.budget()
    );
    other.close().await;
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn delivery_append_failure_and_missing_original_input_never_change_owner() -> TestResult {
    let (_directory, store, finished, transfer) = terminal().await?;
    let claim = takeover(&finished)?;
    let before = Cut::read(&store).await?;
    sqlx::query("CREATE TRIGGER delivery_append_fault BEFORE INSERT ON circuit_v2_events WHEN NEW.seq = 5 BEGIN SELECT RAISE(ABORT, 'test interruption'); END").execute(store.taskflow_pool()).await?;
    assert!(
        store
            .claim_circuit_delivery_owner(&claim, /*activation_id*/ 1, &transfer.digest()?)
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    sqlx::query("DROP TRIGGER delivery_append_fault")
        .execute(store.taskflow_pool())
        .await?;
    // Corruption is injected only after proving the ordinary immutable guard.
    assert!(
        sqlx::query("DELETE FROM circuit_v2_computation_inputs")
            .execute(store.taskflow_pool())
            .await
            .is_err()
    );
    sqlx::query("DROP TRIGGER circuit_v2_input_no_delete")
        .execute(store.taskflow_pool())
        .await?;
    sqlx::query("DELETE FROM circuit_v2_computation_inputs")
        .execute(store.taskflow_pool())
        .await?;
    let corrupt = Cut::read(&store).await?;
    assert!(matches!(
        store
            .observe_circuit_delivery("run-1", /*activation_id*/ 1)
            .await,
        Err(TaskFlowError::Corrupt(_))
    ));
    assert!(
        store
            .recover_circuit_delivery(
                "run-1",
                /*activation_id*/ 1,
                &fence(/*generation*/ 1),
                /*now_ms*/ 15
            )
            .await
            .is_err()
    );
    assert!(
        store
            .claim_circuit_delivery_owner(&claim, /*activation_id*/ 1, &transfer.digest()?)
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, corrupt);
    store.close().await;
    Ok(())
}
