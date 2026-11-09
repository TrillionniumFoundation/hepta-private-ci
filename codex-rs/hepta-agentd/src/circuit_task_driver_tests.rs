//! Native Circuit/Cell integration with controlled inference receipts. These
//! tests qualify ownership and recovery, not real serving or learning quality.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitComputationAdmissionV2;
use codex_hepta_automation::CircuitDispatchV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::CircuitStopReasonV2;
use codex_hepta_contracts::AgentId;
use codex_hepta_neuron::CellPartitionOwnerV1;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::circuit_cell::tests::configuration;
use crate::circuit_cell::tests::support::Encoder;
use crate::circuit_cell::tests::support::Model;
use crate::circuit_cell::tests::support::checked;
use crate::circuit_cell::tests::support::d;
use crate::circuit_cell::tests::support::input;
use crate::circuit_cell::tests::support::scope;
use crate::circuit_cell_operation_id_v1;
use crate::circuit_cell_scope_digest_v1;

#[derive(Default)]
struct Inputs {
    retained: BTreeMap<u64, CellStepInputV1>,
}

impl CircuitTaskInputProviderV1 for Inputs {
    fn resolve(
        &mut self,
        _request: &CircuitTaskRequestV1,
        dispatch: &CircuitDispatchV2,
        _completed: &BTreeMap<u64, CircuitCellExecutionV1>,
        mode: CircuitTaskInputModeV1,
    ) -> Result<CellStepInputV1, Error> {
        if let Some(input) = self.retained.get(&dispatch.activation_id) {
            return Ok(input.clone());
        }
        if mode == CircuitTaskInputModeV1::Readback {
            return Err(Error::ReconciliationRequired);
        }
        let mut input = input(&dispatch.run_id);
        input.operation_id = circuit_cell_operation_id_v1(dispatch)?;
        self.retained.insert(dispatch.activation_id, input.clone());
        Ok(input)
    }
}

type Driver = CircuitTaskDriverV1<CellPartitionOwnerV1, Model, Encoder, Inputs>;

async fn fixture(
    definition: BoundedCircuitDefinitionV2,
    bindings: Vec<CircuitCellBindingV1>,
) -> (
    tempfile::TempDir,
    Driver,
    CircuitTaskRequestV1,
    Arc<AtomicUsize>,
) {
    let directory = tempfile::tempdir().expect("private original owners");
    let agent = checked(AgentId::parse(scope("run-1").agent_id.as_str()));
    let layout = checked(HeptaFleetRoot::parse(
        checked(directory.path().canonicalize()).join("fleet"),
    ))
        .layout()
        .agent(&agent);
    let store = checked(AutomationStore::open(&layout).await);
    let fence = checked(TaskFlowFence::new(
        agent,
        "circuit-task-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "task-fence",
    ));
    let mut state = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 8, /*max_receipts_per_partition*/ 8,
    ));
    for binding in &bindings {
        let mut partition = scope("run-1");
        partition.cell_id = binding.cell.cell_id.clone();
        checked(state.admit(
            partition,
            &binding.cell,
            d("frontier"),
            /*writer_epoch*/ 1,
        ));
    }
    let request = CircuitTaskRequestV1 {
        start: CircuitStartV2 {
            run_id: "run-1".into(),
            scope_digest: checked(circuit_cell_scope_digest_v1(&scope("run-1"))),
            input_digest: Sha256Digest::for_bytes(&input("run-1").observation),
            created_at_ms: 10,
            lease_duration_ms: 2_000,
        },
        objective_digest: d("objective"),
        deadline_ms: 1_010,
    };
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = Arc::clone(&model.calls);
    let cells = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        state,
        model,
        Encoder,
    );
    (
        directory,
        CircuitTaskDriverV1 {
            store,
            fence,
            cells,
            inputs: Inputs::default(),
        },
        request,
        calls,
    )
}

fn time() -> CircuitCellTimeV1 {
    CircuitCellTimeV1 {
        circuit_millis: 20,
        cell_micros: 20,
    }
}

async fn claim_without_delivery(
    driver: &mut Driver,
    request: &CircuitTaskRequestV1,
) -> (CircuitComputationAdmissionV2, CellStepInputV1) {
    let created = checked(
        driver
            .store
            .create_bounded_circuit_run(
                driver.cells.registry().definition(),
                &request.start,
                &driver.fence,
            )
            .await,
    );
    let advanced = checked(
        driver
            .store
            .apply_bounded_circuit_command(&CircuitCommandV2 {
                run_id: request.start.run_id.clone(),
                command_id: "original-advance".into(),
                fence: driver.fence.clone(),
                expected_revision: created.run.revision(),
                now_ms: 20,
                event: CircuitEventV2::Advance { quantum: 1 },
            })
            .await,
    );
    let dispatch = &advanced.dispatches[0];
    let input = checked(driver.inputs.resolve(
        request,
        dispatch,
        &BTreeMap::new(),
        CircuitTaskInputModeV1::Prepare,
    ));
    let binding = checked(driver.cells.registry().bind_input(dispatch, &input));
    let digest = checked(canonical_cell_step_request_digest_v1(&binding.cell, &input));
    let admission = checked(
        driver
            .store
            .claim_circuit_computation(&CircuitComputationClaimV2 {
                run_id: request.start.run_id.clone(),
                activation_id: dispatch.activation_id,
                command_id: "original-claim".into(),
                fence: driver.fence.clone(),
                expected_revision: advanced.run.revision(),
                now_ms: 20,
                execution_request_digest: checked(Sha256Digest::parse(digest.to_string())),
            })
            .await,
    );
    (admission, input)
}

#[tokio::test]
async fn task_reaches_durable_terminal_and_replays_the_exact_result() {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let first = checked(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await,
    );
    assert_eq!(
        first.trace().run().outcome(),
        Some(CircuitExitV2::Succeeded)
    );
    assert_eq!(first.trace().run().unresolved(), 0);
    assert_eq!(first.executions().len(), 1);
    assert_eq!(
        first.trace().completions(),
        &first
            .executions()
            .iter()
            .map(|(id, execution)| (*id, execution.completion.clone()))
            .collect::<BTreeMap<_, _>>()
    );
    let retry = checked(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await,
    );
    let readback = checked(
        driver
            .execute(&request, CircuitTaskModeV1::Readback, || Ok(time()))
            .await,
    );
    assert_eq!((retry, readback), (first.clone(), first));
    // The original state still has one step; an exact task retry cannot add one.
    let snapshot = checked(driver.cells.state_owner().snapshot(&scope("run-1")));
    assert_eq!((snapshot.revision, calls.load(Ordering::SeqCst)), (1, 1));
    driver.store.close().await;
}

#[tokio::test]
async fn lost_claim_ack_cannot_become_a_fresh_cell_dispatch() {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let (admission, _input) = claim_without_delivery(&mut driver, &request).await;
    drop(admission);
    assert_eq!(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await,
        Err(Error::Cell(CircuitCellErrorV1::ReconciliationRequired))
    );
    let run = checked(driver.store.bounded_circuit_run("run-1").await)
        .expect("original durable reservation");
    assert_eq!((run.unresolved(), run.budget().reserved()), (1, 2_000));
    let snapshot = checked(driver.cells.state_owner().snapshot(&scope("run-1")));
    assert_eq!((snapshot.revision, calls.load(Ordering::SeqCst)), (0, 0));
    driver.store.close().await;
}

#[tokio::test]
async fn lost_circuit_completion_ack_reads_the_original_committed_cell_result() {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let (admission, input) = claim_without_delivery(&mut driver, &request).await;
    let execution = checked(driver.cells.execute(admission, input, time));
    let receipt = checked(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await,
    );
    assert_eq!(
        receipt.trace().run().outcome(),
        Some(CircuitExitV2::Succeeded)
    );
    assert_eq!(
        receipt.executions().values().collect::<Vec<_>>(),
        vec![&execution]
    );
    let snapshot = checked(driver.cells.state_owner().snapshot(&scope("run-1")));
    assert_eq!((snapshot.revision, calls.load(Ordering::SeqCst)), (1, 1));
    driver.store.close().await;
}

#[tokio::test]
async fn delayed_feedback_waits_without_appending_empty_scheduling_events() {
    let (mut definition, bindings) = configuration();
    definition.programs[0].edges[0].feedback_delay_ms = Some(30);
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let started = Instant::now();
    let receipt = checked(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || {
                Ok(CircuitCellTimeV1 {
                    circuit_millis: 20 + started.elapsed().as_millis() as u64,
                    cell_micros: 20,
                })
            })
            .await,
    );
    assert_eq!(
        receipt.trace().run().outcome(),
        Some(CircuitExitV2::Succeeded)
    );
    assert_eq!(receipt.trace().run().revision(), 4);
    assert!(started.elapsed().as_millis() >= 30);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    driver.store.close().await;
}

#[tokio::test]
async fn elapsed_task_deadline_never_creates_a_run_or_contacts_a_cell() {
    let (definition, bindings) = configuration();
    let (_directory, mut driver, mut request, calls) = fixture(definition, bindings).await;
    request.deadline_ms = 20;
    assert_eq!(
        driver
            .execute(&request, CircuitTaskModeV1::Drive, || Ok(time()))
            .await,
        Err(Error::DeadlineExceeded)
    );
    assert_eq!(
        checked(driver.store.bounded_circuit_run("run-1").await),
        None
    );
    let snapshot = checked(driver.cells.state_owner().snapshot(&scope("run-1")));
    assert_eq!((snapshot.revision, calls.load(Ordering::SeqCst)), (0, 0));
    driver.store.close().await;
}

#[tokio::test]
async fn circuit_deadline_wakes_before_a_later_feedback_activation() {
    let (mut definition, bindings) = configuration();
    definition.limits.max_elapsed_ms = 30;
    definition.programs[0].edges[0].feedback_delay_ms = Some(30);
    let (_directory, mut driver, request, calls) = fixture(definition, bindings).await;
    let clock = Arc::new(AtomicU64::new(20));
    let store = driver.store.clone();
    let advance_clock = async {
        loop {
            if checked(store.bounded_circuit_committed_trace("run-1").await)
                .is_some_and(|trace| !trace.completions().is_empty())
            {
                // The real completion has scheduled feedback for t=50. Only
                // the Circuit deadline at t=40 is reached; t=50 never arrives.
                clock.store(40, Ordering::SeqCst);
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    };
    let drive = driver.execute(&request, CircuitTaskModeV1::Drive, || {
        Ok(CircuitCellTimeV1 {
            circuit_millis: clock.load(Ordering::SeqCst),
            cell_micros: 20,
        })
    });
    let (result, ()) = tokio::time::timeout(Duration::from_secs(2), async {
        tokio::join!(drive, advance_clock)
    })
    .await
    .expect("the task must wake at its Circuit deadline");
    let receipt = checked(result);
    assert_eq!(
        receipt.trace().run().stop_reason(),
        Some(CircuitStopReasonV2::Deadline)
    );
    assert_eq!(
        receipt.trace().run().outcome(),
        Some(CircuitExitV2::Abstained)
    );
    assert_eq!(
        (
            receipt.trace().run().revision(),
            calls.load(Ordering::SeqCst)
        ),
        (4, 1)
    );
    driver.store.close().await;
}
