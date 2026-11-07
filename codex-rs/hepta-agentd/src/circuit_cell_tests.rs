use std::sync::atomic::Ordering;

use codex_hepta_automation::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::*;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::CircuitCellRouteV1;
use crate::circuit_cell_operation_id_v1;
use crate::circuit_cell_output_schema_v1;
use crate::circuit_cell_route_policy_digest_v1;
use crate::circuit_cell_scope_digest_v1;

#[path = "circuit_cell_test_support.rs"]
mod support;
use support::Encoder;
use support::Model;
use support::checked;
use support::d;
use support::definition as cell_definition;
use support::id;
use support::input;
use support::scope;

fn fence() -> TaskFlowFence {
    checked(TaskFlowFence::new(
        checked(AgentId::parse(scope("run-1").agent_id.as_str())),
        "circuit-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "fence-1",
    ))
}

fn configuration() -> (BoundedCircuitDefinitionV2, Vec<CircuitCellBindingV1>) {
    let cell = cell_definition();
    let bindings = vec![CircuitCellBindingV1 {
        program_id: "root".to_string(),
        node_id: "decide".to_string(),
        cell: cell.clone(),
        routes: vec![
            CircuitCellRouteV1 {
                candidate_id: id("a"),
                outcome: CircuitExitV2::Succeeded,
                selected_edges: vec!["done".to_string()],
            },
            CircuitCellRouteV1 {
                candidate_id: id("b"),
                outcome: CircuitExitV2::Succeeded,
                selected_edges: vec!["slow".to_string()],
            },
            CircuitCellRouteV1 {
                candidate_id: id("abstain"),
                outcome: CircuitExitV2::Abstained,
                selected_edges: vec![],
            },
        ],
    }];
    let schema = circuit_cell_output_schema_v1();
    let definition = BoundedCircuitDefinitionV2 {
        profile: CircuitProfileV2::BoundedFeedbackV2,
        circuit_id: "native-cell".to_string(),
        version: 1,
        predecessor_digest: None,
        entry_program: "root".to_string(),
        parameter_bundle_digest: checked(Sha256Digest::parse(cell.bundle_digest.to_string())),
        route_policy_digest: checked(circuit_cell_route_policy_digest_v1(&bindings)),
        limits: CircuitLimitsV2 {
            max_rounds: 3,
            max_activations: 16,
            max_frontier: 8,
            max_events: 64,
            max_causal_depth: 16,
            max_child_depth: 2,
            max_quantum: 8,
            max_no_progress: 3,
            max_elapsed_ms: 1_000,
            work_budget: 4_000,
        },
        programs: vec![CircuitProgramV2 {
            program_id: "root".to_string(),
            entry_node: "decide".to_string(),
            fallback_node: "fallback".to_string(),
            nodes: vec![
                CircuitNodeV2 {
                    node_id: "decide".to_string(),
                    input_schema: Sha256Digest::for_bytes(b"raw"),
                    output_schema: schema.clone(),
                    kind: CircuitNodeKindV2::Decide { max_work: 2_000 },
                },
                CircuitNodeV2 {
                    node_id: "success".to_string(),
                    input_schema: schema.clone(),
                    output_schema: schema.clone(),
                    kind: CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Succeeded,
                    },
                },
                CircuitNodeV2 {
                    node_id: "fallback".to_string(),
                    input_schema: schema.clone(),
                    output_schema: schema,
                    kind: CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Abstained,
                    },
                },
            ],
            edges: vec![
                CircuitEdgeV2 {
                    edge_id: "done".to_string(),
                    from: "decide".to_string(),
                    to: "success".to_string(),
                    feedback_delay_ms: None,
                },
                CircuitEdgeV2 {
                    edge_id: "slow".to_string(),
                    from: "decide".to_string(),
                    to: "success".to_string(),
                    feedback_delay_ms: None,
                },
            ],
        }],
    };
    (definition, bindings)
}

async fn create_run(
    definition: &BoundedCircuitDefinitionV2,
) -> (tempfile::TempDir, AutomationStore, CircuitDispatchV2) {
    let directory = tempfile::tempdir().expect("private owner fixture");
    let layout = checked(HeptaFleetRoot::parse(directory.path().join("fleet")))
        .layout()
        .agent(&fence().owner_agent_id);
    let store = checked(AutomationStore::open(&layout).await);
    checked(
        store
            .create_bounded_circuit_run(
                definition,
                &CircuitStartV2 {
                    run_id: "run-1".to_string(),
                    scope_digest: checked(circuit_cell_scope_digest_v1(&scope("run-1"))),
                    input_digest: Sha256Digest::for_bytes(&input("run-1").observation),
                    created_at_ms: 10,
                    lease_duration_ms: 500,
                },
                &fence(),
            )
            .await,
    );
    let advanced = apply(
        &store,
        "advance",
        11,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    assert_eq!(advanced.dispatches.len(), 1);
    (directory, store, advanced.dispatches[0].clone())
}

async fn apply(
    store: &AutomationStore,
    command_id: &str,
    now_ms: u64,
    event: CircuitEventV2,
) -> CircuitCommandReceiptV2 {
    let current = checked(store.bounded_circuit_run("run-1").await).expect("existing run");
    checked(
        store
            .apply_bounded_circuit_command(&CircuitCommandV2 {
                run_id: "run-1".to_string(),
                command_id: command_id.to_string(),
                fence: fence(),
                expected_revision: current.revision(),
                now_ms,
                event,
            })
            .await,
    )
}

fn request(dispatch: &CircuitDispatchV2) -> CellStepInputV1 {
    let mut request = input("run-1");
    request.operation_id = checked(circuit_cell_operation_id_v1(dispatch));
    request
}

async fn claim(
    store: &AutomationStore,
    dispatch: &CircuitDispatchV2,
    definition: &CellDefinitionV1,
    request: &CellStepInputV1,
    now_ms: u64,
) -> CircuitComputationAdmissionV2 {
    let current = checked(store.bounded_circuit_run("run-1").await).expect("existing run");
    checked(
        store
            .claim_circuit_computation(&CircuitComputationClaimV2 {
                run_id: "run-1".to_string(),
                activation_id: dispatch.activation_id,
                command_id: format!("claim-{}", dispatch.activation_id),
                fence: fence(),
                expected_revision: current.revision(),
                now_ms,
                execution_request_digest: checked(Sha256Digest::parse(
                    checked(canonical_cell_step_request_digest_v1(definition, request)).to_string(),
                )),
            })
            .await,
    )
}

fn native_owner(bindings: &[CircuitCellBindingV1]) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(
        /*max_partitions*/ 8, /*max_receipts_per_partition*/ 8,
    ));
    for binding in bindings {
        let mut partition = scope("run-1");
        partition.cell_id = binding.cell.cell_id.clone();
        checked(owner.admit(
            partition,
            &binding.cell,
            d("frontier"),
            /*writer_epoch*/ 1,
        ));
    }
    owner
}

fn time() -> CircuitCellTimeV1 {
    CircuitCellTimeV1 {
        circuit_millis: 20,
        cell_micros: 20,
    }
}

#[tokio::test]
async fn durable_circuit_to_native_cell_and_ack_loss_replay_use_one_model_call() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = model.calls.clone();
    let owner = native_owner(&bindings);
    let registry = checked(CircuitCellRegistryV1::new(definition, bindings));
    let mut runtime = AgentdCircuitCellOwnerV1::new(registry, owner, model, Encoder);
    let executed = checked(runtime.execute(admission, request.clone(), time));
    assert_eq!(
        (
            executed.completion.selected_edges.as_slice(),
            executed.completion.actual_work
        ),
        (["done".to_string()].as_slice(), 20)
    );
    assert_eq!(
        executed.completion.output_digest,
        Sha256Digest::for_bytes(&executed.output)
    );
    assert_eq!(executed.decision.authority, AuthorityPosture::DENY_ALL);
    let mut changed_audit = executed.decision.clone();
    changed_audit.operation_id = id("another-audit-operation");
    changed_audit.cost.queue_age_micros += 1;
    assert_eq!(
        checked(encode_output(&changed_audit)),
        executed.output,
        "audit identity and timing do not manufacture semantic progress"
    );
    assert_ne!(
        checked(encode_receipt(&changed_audit)),
        checked(encode_receipt(&executed.decision)),
        "complete audit encoding still binds operation and cost"
    );
    let readback = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21)
            .await,
    );
    assert!(readback.reconciliation_only());
    let replayed = checked(runtime.execute(readback, request, || CircuitCellTimeV1 {
        circuit_millis: 22,
        cell_micros: 22,
    }));
    assert_eq!(replayed, executed);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let completed = apply(
        &store,
        "complete",
        22,
        CircuitEventV2::Complete {
            completion: replayed.completion,
        },
    )
    .await;
    assert_eq!(
        (
            completed.run.budget().spent(),
            completed.run.budget().reserved()
        ),
        (20, 0)
    );
    let finished = apply(&store, "exit", 23, CircuitEventV2::Advance { quantum: 1 }).await;
    assert_eq!(finished.run.outcome(), Some(CircuitExitV2::Succeeded));
    assert_eq!(
        checked(runtime.state_owner().snapshot(&scope("run-1")))
            .checkpoint
            .expect("committed state")
            .sequence(),
        1
    );
    store.close().await;
}

#[tokio::test]
async fn lost_claim_before_cell_admission_cannot_start_new_work_from_recovery() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    drop(claim(&store, &dispatch, &bindings[0].cell, &request, 13).await);
    let recovered = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21)
            .await,
    );
    let model = Model::new(20, false);
    let calls = model.calls.clone();
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        Encoder,
    );
    assert_eq!(
        runtime.execute(recovered, request, || CircuitCellTimeV1 {
            circuit_millis: 22,
            cell_micros: 22
        }),
        Err(CircuitCellErrorV1::ReconciliationRequired)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let run = checked(store.bounded_circuit_run("run-1").await).expect("run");
    assert_eq!(run.budget().reserved(), 2_000);
    store.close().await;
}

#[tokio::test]
async fn unknown_model_response_recovers_original_output_and_late_cost_without_reexecution() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(20, true);
    let calls = model.calls.clone();
    let reads = model.reads.clone();
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        Encoder,
    );
    assert!(runtime.execute(admission, request.clone(), time).is_err());
    assert!(checked(runtime.state_owner().pending_inference(&scope("run-1"))).is_some());
    apply(
        &store,
        "unknown",
        21,
        CircuitEventV2::MarkIndeterminate {
            activation_id: dispatch.activation_id,
            observation_digest: Sha256Digest::for_bytes(b"lost-response"),
        },
    )
    .await;
    let recovery = checked(
        store
            .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 22)
            .await,
    );
    let result = checked(runtime.execute(recovery, request, || CircuitCellTimeV1 {
        circuit_millis: 23,
        cell_micros: 200,
    }));
    assert_eq!(
        (calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst)),
        (1, 1)
    );
    assert!(result.decision.deadline_exceeded);
    assert_eq!(
        (result.completion.outcome, result.completion.actual_work),
        (CircuitExitV2::Abstained, 20)
    );
    assert!(result.completion.selected_edges.is_empty());
    let completed = apply(
        &store,
        "reconciled",
        24,
        CircuitEventV2::Reconcile {
            completion: result.completion,
        },
    )
    .await;
    assert_eq!(
        (
            completed.run.budget().spent(),
            completed.run.budget().reserved()
        ),
        (20, 0)
    );
    assert!(checked(runtime.state_owner().pending_inference(&scope("run-1"))).is_none());
    store.close().await;
}

#[tokio::test]
async fn changed_principal_source_or_deadline_never_reaches_the_model() {
    for field in ["principal", "frontier", "deadline", "bytes"] {
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch) = create_run(&definition).await;
        let mut request = request(&dispatch);
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        match field {
            "principal" => request.scope.principal_digest = d("other-principal"),
            "frontier" => request.source_frontier = d("other-frontier"),
            "deadline" => request.deadline_micros += 1,
            "bytes" => request.observation.push(0),
            _ => unreachable!(),
        }
        let model = Model::new(20, false);
        let calls = model.calls.clone();
        let owner = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)),
            owner,
            model,
            Encoder,
        );
        assert!(runtime.execute(admission, request, time).is_err());
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert!(checked(runtime.state_owner().pending_inference(&scope("run-1"))).is_none());
        store.close().await;
    }
}

#[tokio::test]
async fn actual_cost_overrun_is_recorded_and_routes_to_budget_fallback() {
    let (definition, bindings) = configuration();
    let (_directory, store, dispatch) = create_run(&definition).await;
    let request = request(&dispatch);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let owner = native_owner(&bindings);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        Model::new(2_500, false),
        Encoder,
    );
    let result = checked(runtime.execute(admission, request, time));
    assert_eq!(
        (result.completion.actual_work, result.completion.outcome),
        (2_500, CircuitExitV2::Abstained)
    );
    let completed = apply(
        &store,
        "overrun",
        22,
        CircuitEventV2::Complete {
            completion: result.completion,
        },
    )
    .await;
    assert_eq!(completed.run.budget().spent(), 2_500);
    assert_eq!(
        completed.run.stop_reason(),
        Some(CircuitStopReasonV2::WorkBudget)
    );
    assert_eq!(completed.run.budget().reserved(), 0);
    store.close().await;
}

#[test]
fn frozen_registry_rejects_bundle_route_schema_and_candidate_drift() {
    for field in ["bundle", "route", "schema", "candidate"] {
        let (mut definition, mut bindings) = configuration();
        match field {
            "bundle" => {
                definition.parameter_bundle_digest = Sha256Digest::for_bytes(b"other-bundle")
            }
            "route" => bindings[0].routes[0].selected_edges = vec!["absent".to_string()],
            "schema" => {
                definition.programs[0].nodes[0].output_schema =
                    Sha256Digest::for_bytes(b"other-schema")
            }
            "candidate" => bindings[0].routes.swap(0, 1),
            _ => unreachable!(),
        }
        assert!(CircuitCellRegistryV1::new(definition, bindings).is_err());
    }
}

#[tokio::test]
async fn two_cells_share_one_model_facility_but_keep_separate_state_and_causal_output() {
    let (mut definition, mut bindings) = configuration();
    let mut first = bindings[0].clone();
    first.node_id = "compute".to_string();
    first.cell.cell_id = id("source-cell");
    for route in &mut first.routes {
        if route.outcome == CircuitExitV2::Succeeded {
            route.selected_edges = vec!["next".to_string()];
        }
    }
    let first_cell = first.cell.clone();
    let second_cell = bindings[0].cell.clone();
    bindings.push(first);
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    let program = &mut definition.programs[0];
    program.entry_node = "compute".to_string();
    program.nodes[0].input_schema = circuit_cell_output_schema_v1();
    program.nodes.push(CircuitNodeV2 {
        node_id: "compute".to_string(),
        input_schema: Sha256Digest::for_bytes(b"raw"),
        output_schema: circuit_cell_output_schema_v1(),
        kind: CircuitNodeKindV2::Compute { max_work: 2_000 },
    });
    program.edges.push(CircuitEdgeV2 {
        edge_id: "next".to_string(),
        from: "compute".to_string(),
        to: "decide".to_string(),
        feedback_delay_ms: None,
    });
    let (_directory, store, dispatch) = create_run(&definition).await;
    let mut first_request = request(&dispatch);
    first_request.scope.cell_id = first_cell.cell_id.clone();
    let admission = claim(&store, &dispatch, &first_cell, &first_request, 13).await;
    let owner = native_owner(&bindings);
    let model = Model::new(20, false);
    let calls = model.calls.clone();
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)),
        owner,
        model,
        Encoder,
    );
    let first_result = checked(runtime.execute(admission, first_request.clone(), time));
    apply(
        &store,
        "first-complete",
        22,
        CircuitEventV2::Complete {
            completion: first_result.completion,
        },
    )
    .await;
    let advanced = apply(
        &store,
        "second-advance",
        23,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    assert_eq!(advanced.dispatches.len(), 1);
    let second_dispatch = &advanced.dispatches[0];
    let mut second_request = request(second_dispatch);
    second_request.observation = first_result.output;
    second_request.monotonic_micros = 30;
    let admission = claim(&store, second_dispatch, &second_cell, &second_request, 24).await;
    let second_result =
        checked(
            runtime.execute(admission, second_request.clone(), || CircuitCellTimeV1 {
                circuit_millis: 25,
                cell_micros: 31,
            }),
        );
    let completed = apply(
        &store,
        "second-complete",
        26,
        CircuitEventV2::Complete {
            completion: second_result.completion,
        },
    )
    .await;
    assert_eq!(
        (calls.load(Ordering::SeqCst), completed.run.budget().spent()),
        (2, 40)
    );
    let first_state = checked(runtime.state_owner().snapshot(&first_request.scope));
    let second_state = checked(runtime.state_owner().snapshot(&second_request.scope));
    assert_eq!(
        first_state
            .checkpoint
            .as_ref()
            .expect("first state")
            .sequence(),
        1
    );
    assert_eq!(
        second_state
            .checkpoint
            .as_ref()
            .expect("second state")
            .sequence(),
        1
    );
    assert_ne!(
        first_state.checkpoint.expect("first").digest(),
        second_state.checkpoint.expect("second").digest()
    );
    store.close().await;
}

#[tokio::test]
async fn either_late_phase_clock_regression_preserves_pending_for_readback() {
    for regress_at in [3, 4] {
        let (definition, bindings) = configuration();
        let (_directory, store, dispatch) = create_run(&definition).await;
        let request = request(&dispatch);
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        let model = Model::new(20, false);
        let calls = model.calls.clone();
        let reads = model.reads.clone();
        let owner = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)),
            owner,
            model,
            Encoder,
        );
        let mut stage = 0;
        let rejected = runtime.execute(admission, request.clone(), || {
            let time = CircuitCellTimeV1 {
                circuit_millis: if stage == regress_at { 19 } else { 20 + stage },
                cell_micros: 20 + stage,
            };
            stage += 1;
            time
        });
        assert_eq!(rejected, Err(CircuitCellErrorV1::ReconciliationRequired));
        assert!(checked(runtime.state_owner().pending_inference(&scope("run-1"))).is_some());
        let recovery = checked(
            store
                .recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 25)
                .await,
        );
        let result = checked(runtime.execute(recovery, request, || CircuitCellTimeV1 {
            circuit_millis: 30,
            cell_micros: 30,
        }));
        assert_eq!(
            (calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst)),
            (1, 1)
        );
        assert_eq!(result.completion.actual_work, 20);
        store.close().await;
    }
}

#[tokio::test]
async fn final_dispatch_gate_rechecks_time_after_durable_cell_admission() {
    for boundary in ["lease", "run", "cell"] {
        let (mut definition, bindings) = configuration();
        if boundary == "run" {
            definition.limits.max_elapsed_ms = 400;
        }
        let (_directory, store, dispatch) = create_run(&definition).await;
        let request = request(&dispatch);
        let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
        let model = Model::new(20, false);
        let calls = model.calls.clone();
        let owner = native_owner(&bindings);
        let mut runtime = AgentdCircuitCellOwnerV1::new(
            checked(CircuitCellRegistryV1::new(definition, bindings)),
            owner,
            model,
            Encoder,
        );
        let mut reads = 0;
        let result = runtime.execute(admission, request, || {
            let expired = reads == 2;
            reads += 1;
            match (expired, boundary) {
                (true, "lease") => CircuitCellTimeV1 {
                    circuit_millis: 600,
                    cell_micros: 21,
                },
                (true, "run") => CircuitCellTimeV1 {
                    circuit_millis: 450,
                    cell_micros: 21,
                },
                (true, "cell") => CircuitCellTimeV1 {
                    circuit_millis: 21,
                    cell_micros: 100,
                },
                _ => time(),
            }
        });
        assert!(result.is_err());
        assert_eq!(
            calls.load(Ordering::SeqCst),
            0,
            "no model contact after durable admission crossed its deadline"
        );
        assert!(
            checked(runtime.state_owner().pending_inference(&scope("run-1"))).is_some(),
            "guard refusal does not mint a second admission"
        );
        store.close().await;
    }
}

#[tokio::test]
async fn all_join_materializes_frozen_reference_bytes_for_the_next_native_cell() {
    let (mut definition, mut bindings) = configuration();
    definition.limits.work_budget = 8_000;
    definition.programs[0].entry_node = "fork".to_string();
    definition.programs[0].nodes[0].input_schema = circuit_join_output_schema_v2();
    for (node, targets) in [
        ("fork", vec![("fork-left", "left"), ("fork-right", "right")]),
        ("left", vec![("left-join", "join")]),
        ("right", vec![("right-join", "join")]),
    ] {
        let mut binding = bindings[0].clone();
        binding.node_id = node.to_string();
        binding.cell.cell_id = id(&format!("cell-{node}"));
        for route in &mut binding.routes {
            if route.outcome == CircuitExitV2::Succeeded {
                route.selected_edges = targets
                    .iter()
                    .map(|(edge, _)| (*edge).to_string())
                    .collect();
            }
        }
        bindings.push(binding);
        definition.programs[0].nodes.push(CircuitNodeV2 {
            node_id: node.to_string(),
            input_schema: if node == "fork" {
                Sha256Digest::for_bytes(b"raw")
            } else {
                circuit_cell_output_schema_v1()
            },
            output_schema: circuit_cell_output_schema_v1(),
            kind: CircuitNodeKindV2::Compute { max_work: 2_000 },
        });
        for (edge, to) in targets {
            definition.programs[0].edges.push(CircuitEdgeV2 {
                edge_id: edge.to_string(),
                from: node.to_string(),
                to: to.to_string(),
                feedback_delay_ms: None,
            });
        }
    }
    definition.programs[0].nodes.push(CircuitNodeV2 {
        node_id: "join".to_string(),
        input_schema: circuit_cell_output_schema_v1(),
        output_schema: circuit_join_output_schema_v2(),
        kind: CircuitNodeKindV2::Join {
            mode: CircuitJoinV2::All,
            timeout_ms: 200,
        },
    });
    definition.programs[0].edges.push(CircuitEdgeV2 {
        edge_id: "joined".to_string(),
        from: "join".to_string(),
        to: "decide".to_string(),
        feedback_delay_ms: None,
    });
    definition.route_policy_digest = checked(circuit_cell_route_policy_digest_v1(&bindings));
    let (_directory, store, dispatch) = create_run(&definition).await;
    let mut fork_request = request(&dispatch);
    fork_request.scope.cell_id = id("cell-fork");
    let admission = claim(&store, &dispatch, &bindings[1].cell, &fork_request, 13).await;
    let owner = native_owner(&bindings);
    let model = Model::new(20, false);
    let calls = model.calls.clone();
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings.clone())),
        owner,
        model,
        Encoder,
    );
    let fork = checked(runtime.execute(admission, fork_request, time));
    apply(
        &store,
        "fork-complete",
        22,
        CircuitEventV2::Complete {
            completion: fork.completion,
        },
    )
    .await;
    let branches = apply(
        &store,
        "branches",
        23,
        CircuitEventV2::Advance { quantum: 2 },
    )
    .await;
    assert_eq!(branches.dispatches.len(), 2);
    for (index, branch) in branches.dispatches.iter().enumerate() {
        let binding = bindings
            .iter()
            .find(|binding| binding.node_id == branch.node_id)
            .expect("branch binding");
        let mut branch_request = request(branch);
        branch_request.scope.cell_id = binding.cell.cell_id.clone();
        branch_request.observation = fork.output.clone();
        branch_request.monotonic_micros = 30;
        let offset = index as u64 * 3;
        let admission = claim(&store, branch, &binding.cell, &branch_request, 24 + offset).await;
        let result = checked(
            runtime.execute(admission, branch_request, || CircuitCellTimeV1 {
                circuit_millis: 25 + offset,
                cell_micros: 40 + offset,
            }),
        );
        apply(
            &store,
            &format!("complete-{}", branch.node_id),
            26 + offset,
            CircuitEventV2::Complete {
                completion: result.completion,
            },
        )
        .await;
    }
    let joined = apply(
        &store,
        "join-and-next",
        30,
        CircuitEventV2::Advance { quantum: 2 },
    )
    .await;
    assert_eq!(joined.dispatches.len(), 1);
    let join = joined
        .run
        .activations()
        .values()
        .find(|activation| activation.node_id == "join")
        .expect("completed join");
    let bytes = checked(
        store
            .bounded_circuit_join_output("run-1", join.activation_id)
            .await,
    );
    let envelope: CircuitJoinEnvelopeV2 = checked(serde_json::from_slice(&bytes));
    assert_eq!(
        (
            envelope.causal_parents.len(),
            envelope.arrival_input_digests.len()
        ),
        (2, 2)
    );
    let next = &joined.dispatches[0];
    assert_eq!(Sha256Digest::for_bytes(&bytes), next.input_digest);
    let mut next_request = request(next);
    next_request.observation = bytes;
    next_request.monotonic_micros = 60;
    let admission = claim(&store, next, &bindings[0].cell, &next_request, 31).await;
    let result = checked(
        runtime.execute(admission, next_request, || CircuitCellTimeV1 {
            circuit_millis: 32,
            cell_micros: 61,
        }),
    );
    let complete = apply(
        &store,
        "joined-cell-complete",
        33,
        CircuitEventV2::Complete {
            completion: result.completion,
        },
    )
    .await;
    assert_eq!(
        (calls.load(Ordering::SeqCst), complete.run.budget().spent()),
        (4, 80)
    );
    let exited = apply(
        &store,
        "joined-exit",
        34,
        CircuitEventV2::Advance { quantum: 1 },
    )
    .await;
    assert_eq!(exited.run.outcome(), Some(CircuitExitV2::Succeeded));
    store.close().await;
}

#[path = "circuit_cell_representation_tests.rs"]
mod representation_tests;
