use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use crate::AutomationStore;
use crate::CircuitCommandV2;
use crate::CircuitComputationClaimV2;
use crate::CircuitComputationInputV1;
use crate::CircuitEventV2;
use crate::CircuitLeaseClaimV2;
use crate::TaskFlowError;
use crate::circuit_runtime_tests::fence;

use super::claim;
use super::pending;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn input() -> CircuitComputationInputV1 {
    CircuitComputationInputV1::new(
        "native-request-fixture.v1",
        b"{\"original_clock\":12,\"input\":[0,255,7]}".to_vec(),
    )
    .expect("bounded original request bytes")
}

#[derive(Debug, Eq, PartialEq)]
struct Cut {
    run: serde_json::Value,
    events: Vec<String>,
    inputs: Vec<(i64, String, Vec<u8>)>,
}

impl Cut {
    async fn read(store: &AutomationStore) -> TestResult<Self> {
        Ok(Self {
            run: serde_json::to_value(store.bounded_circuit_run("run-1").await?)?,
            events: sqlx::query_scalar("SELECT event_json FROM circuit_v2_events ORDER BY seq")
                .fetch_all(store.taskflow_pool())
                .await?,
            inputs: sqlx::query_as(
                "SELECT activation_id, schema_id, input_bytes
                 FROM circuit_v2_computation_inputs ORDER BY activation_id",
            )
            .fetch_all(store.taskflow_pool())
            .await?,
        })
    }
}

#[tokio::test]
async fn original_input_survives_lost_claim_response_reopen_and_owner_takeover() -> TestResult {
    let (_directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "claim-original-bytes");
    let original = input();
    let token = store
        .claim_circuit_computation_with_input(&request, &original)
        .await?;
    assert!(!token.reconciliation_only());
    assert_eq!(token.input(), Some(&original));
    assert_eq!(
        token.execution_request_digest(),
        Some(&request.execution_request_digest)
    );
    let before = Cut::read(&store).await?;
    assert_eq!(
        before.inputs,
        vec![(
            i64::try_from(request.activation_id)?,
            original.schema().into(),
            original.bytes().to_vec()
        )]
    );
    drop(token); // Claim committed; no worker received the request.
    let root = store.path().parent().expect("root").to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let store = AutomationStore::open_root(root, owner).await?;
    let recovered = store
        .recover_circuit_computation(
            "run-1",
            request.activation_id,
            &request.fence,
            /*now_ms*/ 13,
        )
        .await?;
    assert!(recovered.reconciliation_only());
    assert_eq!(recovered.input(), Some(&original));
    assert_eq!(Cut::read(&store).await?, before);
    let repeated = store
        .claim_circuit_computation_with_input(&request, &original)
        .await?;
    assert!(repeated.reconciliation_only());
    assert_eq!(repeated.input(), Some(&original));
    assert_eq!(Cut::read(&store).await?, before);
    store
        .claim_bounded_circuit_run(&CircuitLeaseClaimV2 {
            run_id: "run-1".into(),
            command_id: "successor".into(),
            fence: fence(/*generation*/ 2),
            expected_revision: recovered.observed_revision(),
            now_ms: 110,
            lease_duration_ms: 100,
        })
        .await?;
    assert!(matches!(
        store
            .recover_circuit_computation(
                "run-1",
                request.activation_id,
                &request.fence,
                /*now_ms*/ 111
            )
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    let successor = store
        .recover_circuit_computation(
            "run-1",
            request.activation_id,
            &fence(/*generation*/ 2),
            /*now_ms*/ 111,
        )
        .await?;
    assert!(successor.reconciliation_only());
    assert_eq!(successor.input(), Some(&original));
    assert_eq!(
        successor.execution_request_digest(),
        Some(&request.execution_request_digest)
    );
    let run = store.bounded_circuit_run("run-1").await?.expect("run");
    assert_eq!(
        (
            run.budget().spent(),
            run.budget().reserved(),
            run.unresolved()
        ),
        (0, 5, 1)
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn changed_bytes_schema_or_late_input_cannot_rebind_a_claim() -> TestResult {
    for retain_original in [false, true] {
        let (_directory, store, dispatched) = pending().await;
        let request = claim(&dispatched, "fixed-claim");
        let original = input();
        let token = if retain_original {
            store
                .claim_circuit_computation_with_input(&request, &original)
                .await?
        } else {
            store.claim_circuit_computation(&request).await?
        };
        let before = Cut::read(&store).await?;
        let retry = CircuitComputationClaimV2 {
            command_id: "new-command-same-operation".into(),
            expected_revision: token.observed_revision(),
            now_ms: 13,
            ..request.clone()
        };
        let changed_bytes = CircuitComputationInputV1::new(original.schema(), b"changed".to_vec())?;
        let changed_schema =
            CircuitComputationInputV1::new("other-schema.v1", original.bytes().to_vec())?;
        for changed in [&changed_bytes, &changed_schema] {
            assert!(matches!(
                store
                    .claim_circuit_computation_with_input(&retry, changed)
                    .await,
                Err(TaskFlowError::Conflict(_))
            ));
            assert_eq!(Cut::read(&store).await?, before);
        }
        if !retain_original {
            assert!(matches!(
                store
                    .claim_circuit_computation_with_input(&retry, &original)
                    .await,
                Err(TaskFlowError::Conflict(_))
            ));
            assert_eq!(Cut::read(&store).await?, before);
        }
        let legacy_readback = store.claim_circuit_computation(&retry).await?;
        assert!(legacy_readback.reconciliation_only());
        assert_eq!(
            legacy_readback.input(),
            retain_original.then_some(&original)
        );
        assert_eq!(Cut::read(&store).await?, before);
        store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn claim_failure_rolls_back_input_and_original_reservation_together() -> TestResult {
    let (_directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "transaction-cut");
    let before = Cut::read(&store).await?;
    let stale = CircuitComputationClaimV2 {
        expected_revision: 0,
        ..request.clone()
    };
    assert!(matches!(
        store
            .claim_circuit_computation_with_input(&stale, &input())
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
    assert_eq!(Cut::read(&store).await?, before);
    sqlx::query("CREATE TRIGGER reject_input_claim BEFORE INSERT ON circuit_v2_events WHEN NEW.seq = 2 BEGIN SELECT RAISE(ABORT, 'injected claim append failure'); END")
        .execute(store.taskflow_pool()).await?;
    assert!(
        store
            .claim_circuit_computation_with_input(&request, &input())
            .await
            .is_err()
    );
    assert_eq!(Cut::read(&store).await?, before);
    sqlx::query("DROP TRIGGER reject_input_claim")
        .execute(store.taskflow_pool())
        .await?;
    let token = store
        .claim_circuit_computation_with_input(&request, &input())
        .await?;
    assert!(!token.reconciliation_only());
    assert_eq!(token.input(), Some(&input()));
    assert_eq!(Cut::read(&store).await?.inputs.len(), 1);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn missing_or_modified_input_never_yields_a_recovery_token() -> TestResult {
    for corruption in ["bytes", "schema", "missing", "orphan"] {
        let (_directory, store, dispatched) = pending().await;
        let request = claim(&dispatched, "before-corruption");
        if corruption == "orphan" {
            store.claim_circuit_computation(&request).await?;
            sqlx::query("INSERT INTO circuit_v2_computation_inputs VALUES (?, 'run-1', ?, 'injected.v1', X'01')")
                .bind(store.owner_agent_id().as_str()).bind(i64::try_from(request.activation_id)?)
                .execute(store.taskflow_pool()).await?;
        } else {
            store
                .claim_circuit_computation_with_input(&request, &input())
                .await?;
            assert!(
                sqlx::query("UPDATE circuit_v2_computation_inputs SET input_bytes = X'01'")
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            assert!(
                sqlx::query("DELETE FROM circuit_v2_computation_inputs")
                    .execute(store.taskflow_pool())
                    .await
                    .is_err()
            );
            match corruption {
                "bytes" | "schema" => {
                    sqlx::query("DROP TRIGGER circuit_v2_input_no_update")
                        .execute(store.taskflow_pool())
                        .await?;
                    let sql = if corruption == "bytes" {
                        "UPDATE circuit_v2_computation_inputs SET input_bytes = X'01'"
                    } else {
                        "UPDATE circuit_v2_computation_inputs SET schema_id = 'changed.v1'"
                    };
                    sqlx::query(sql).execute(store.taskflow_pool()).await?;
                }
                "missing" => {
                    sqlx::query("DROP TRIGGER circuit_v2_input_no_delete")
                        .execute(store.taskflow_pool())
                        .await?;
                    sqlx::query("DELETE FROM circuit_v2_computation_inputs")
                        .execute(store.taskflow_pool())
                        .await?;
                }
                _ => unreachable!(),
            }
        }
        assert!(
            matches!(
                store
                    .recover_circuit_computation(
                        "run-1",
                        request.activation_id,
                        &request.fence,
                        /*now_ms*/ 13
                    )
                    .await,
                Err(TaskFlowError::Corrupt(_))
            ),
            "{corruption}"
        );
        let retry = CircuitComputationClaimV2 {
            command_id: "recovery-attempt".into(),
            expected_revision: 2,
            now_ms: 13,
            ..request
        };
        assert!(
            matches!(
                store
                    .claim_circuit_computation_with_input(&retry, &input())
                    .await,
                Err(TaskFlowError::Corrupt(_))
            ),
            "{corruption}"
        );
        assert_eq!(
            store
                .bounded_circuit_run("run-1")
                .await?
                .expect("run")
                .budget()
                .reserved(),
            5
        );
        store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn owner_clock_lease_and_cancel_rejections_leave_no_input_record() -> TestResult {
    let (_directory, store, dispatched) = pending().await;
    let request = claim(&dispatched, "preflight");
    let before = Cut::read(&store).await?;
    for mutation in ["owner", "generation", "expired", "regression"] {
        let mut changed = request.clone();
        match mutation {
            "owner" => {
                changed.fence.owner_agent_id =
                    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?
            }
            "generation" => changed.fence = fence(/*generation*/ 2),
            "expired" => changed.now_ms = 110,
            "regression" => changed.now_ms = 10,
            _ => unreachable!(),
        }
        assert!(matches!(
            store
                .claim_circuit_computation_with_input(&changed, &input())
                .await,
            Err(TaskFlowError::StaleFence)
        ));
        assert_eq!(Cut::read(&store).await?, before);
    }
    let cancelled = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "cancel-before-claim".into(),
            fence: request.fence.clone(),
            expected_revision: dispatched.run.revision(),
            now_ms: 12,
            event: CircuitEventV2::Cancel,
        })
        .await?;
    let cancelled_request = CircuitComputationClaimV2 {
        expected_revision: cancelled.run.revision(),
        now_ms: 13,
        ..request
    };
    let before = Cut::read(&store).await?;
    assert!(matches!(
        store
            .claim_circuit_computation_with_input(&cancelled_request, &input())
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
    assert_eq!(Cut::read(&store).await?, before);
    let readback = store.claim_circuit_computation(&cancelled_request).await?;
    assert!(readback.reconciliation_only());
    assert!(readback.input().is_none());
    assert_eq!(Cut::read(&store).await?, before);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn concurrent_input_claims_retain_one_original_and_issue_one_execution() -> TestResult {
    let (_directory, store, dispatched) = pending().await;
    let other = AutomationStore::open_root(
        store.path().parent().expect("root").to_path_buf(),
        store.owner_agent_id().clone(),
    )
    .await?;
    let left = claim(&dispatched, "left");
    let right = claim(&dispatched, "right");
    let original = input();
    let (left, right) = tokio::join!(
        store.claim_circuit_computation_with_input(&left, &original),
        other.claim_circuit_computation_with_input(&right, &original)
    );
    let left = left?;
    let right = right?;
    assert_eq!(
        usize::from(!left.reconciliation_only()) + usize::from(!right.reconciliation_only()),
        1
    );
    assert_eq!(left.input(), Some(&original));
    assert_eq!(right.input(), Some(&original));
    assert_eq!(Cut::read(&store).await?.inputs.len(), 1);
    assert_eq!(
        store
            .bounded_circuit_run("run-1")
            .await?
            .expect("run")
            .revision(),
        2
    );
    other.close().await;
    store.close().await;
    Ok(())
}
