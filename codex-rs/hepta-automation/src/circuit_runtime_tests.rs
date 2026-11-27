use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use crate::*;

pub(super) fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

pub(super) fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
        "circuit-owner",
        /*owner_epoch*/ 1,
        generation,
        format!("fence-{generation}"),
    )
    .expect("fence")
}

fn node(id: &str, kind: CircuitNodeKindV2) -> CircuitNodeV2 {
    CircuitNodeV2 {
        node_id: id.to_string(),
        input_schema: digest("vector-v1"),
        output_schema: digest("vector-v1"),
        kind,
    }
}

fn edge(id: &str, from: &str, to: &str) -> CircuitEdgeV2 {
    CircuitEdgeV2 {
        edge_id: id.to_string(),
        from: from.to_string(),
        to: to.to_string(),
        feedback_delay_ms: None,
    }
}

pub(super) fn definition() -> BoundedCircuitDefinitionV2 {
    BoundedCircuitDefinitionV2 {
        profile: CircuitProfileV2::BoundedFeedbackV2,
        circuit_id: "bounded-retrieval".to_string(),
        version: 1,
        predecessor_digest: None,
        entry_program: "root".to_string(),
        parameter_bundle_digest: digest("bundle-v1"),
        route_policy_digest: digest("route-v1"),
        limits: CircuitLimitsV2 {
            max_rounds: 3,
            max_activations: 64,
            max_frontier: 16,
            max_events: 128,
            max_causal_depth: 32,
            max_child_depth: 4,
            max_quantum: 16,
            max_no_progress: 3,
            max_elapsed_ms: 1_000,
            work_budget: 100,
        },
        programs: vec![CircuitProgramV2 {
            program_id: "root".to_string(),
            entry_node: "decide".to_string(),
            fallback_node: "failure".to_string(),
            nodes: vec![
                node("decide", CircuitNodeKindV2::Decide { max_work: 5 }),
                node(
                    "success",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Succeeded,
                    },
                ),
                node(
                    "failure",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Failed,
                    },
                ),
            ],
            edges: vec![
                CircuitEdgeV2 {
                    feedback_delay_ms: Some(10),
                    ..edge("again", "decide", "decide")
                },
                edge("done", "decide", "success"),
            ],
        }],
    }
}

pub(super) fn start() -> CircuitStartV2 {
    CircuitStartV2 {
        run_id: "run-1".to_string(),
        scope_digest: digest("principal-and-source-frontier"),
        input_digest: digest("input"),
        created_at_ms: 10,
        lease_duration_ms: 100,
    }
}

pub(super) fn completion(
    dispatch: &CircuitDispatchV2,
    selected: &[&str],
    label: &str,
) -> CircuitCompletionV2 {
    CircuitCompletionV2 {
        activation_id: dispatch.activation_id,
        invocation_digest: dispatch.invocation_digest.clone(),
        output_digest: digest(label),
        receipt_digest: digest(&format!("receipt-{label}")),
        actual_work: 3,
        outcome: CircuitExitV2::Succeeded,
        selected_edges: selected.iter().map(|v| (*v).to_string()).collect(),
    }
}

fn advance(
    run: &CircuitRunV2,
    definition: &BoundedCircuitDefinitionV2,
    now_ms: u64,
) -> (CircuitRunV2, Vec<CircuitDispatchV2>) {
    run.reduce(definition, &CircuitEventV2::Advance { quantum: 16 }, now_ms)
        .expect("advance")
}

#[test]
fn delayed_feedback_reactivates_with_finite_causality_and_preserves_actual_cost() {
    let definition = definition();
    let mut run =
        CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("prepare");
    for round in 0..3 {
        let now = 10 + u64::from(round) * 11;
        let (active, dispatches) = advance(&run, &definition, now);
        assert_eq!(dispatches.len(), 1);
        assert_eq!(dispatches[0].round, round);
        let (completed, _) = active
            .reduce(
                &definition,
                &CircuitEventV2::Complete {
                    completion: completion(&dispatches[0], &["again"], &format!("result-{round}")),
                },
                now + 1,
            )
            .expect("complete");
        run = completed;
        if round != 2 {
            let (waiting, dispatches) = advance(&run, &definition, now + 10);
            assert!(
                dispatches.is_empty(),
                "feedback may not fire before its delay"
            );
            run = waiting;
        }
    }
    assert_eq!(
        (
            run.outcome(),
            run.stop_reason(),
            run.budget().spent(),
            run.budget().reserved()
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::RoundLimit),
            9,
            0
        )
    );
    assert!(
        run.activations()
            .values()
            .all(|a| a.causal_parents.iter().all(|p| *p < a.activation_id))
    );
    assert_eq!(
        run.activations()
            .values()
            .map(|a| a.causal_depth)
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
}

#[test]
fn profile_rejects_same_round_cycles_zero_delay_and_implicit_schema_conversion() {
    let original = definition();
    for delay in [None, Some(0)] {
        let mut invalid = original.clone();
        invalid.programs[0].edges[0].feedback_delay_ms = delay;
        assert!(invalid.validate().is_err());
    }
    let mut mismatch = original.clone();
    mismatch.programs[0].nodes[1].input_schema = digest("different-vector-shape");
    assert!(mismatch.validate().is_err());
    let mut future_profile = serde_json::to_value(original).expect("json");
    future_profile["profile"] = serde_json::json!("unbounded_feedback_v3");
    assert!(serde_json::from_value::<BoundedCircuitDefinitionV2>(future_profile).is_err());
}

#[test]
fn v1_cycle_validation_remains_an_independent_compatibility_gate() {
    let result = NeuralCircuitCandidateV1::new(
        "legacy-loop",
        /*version*/ 1,
        /*predecessor_digest*/ None,
        CircuitProgramV1 {
            entry_node: "work".to_string(),
            nodes: vec![
                CircuitNodeV1::new("work", CircuitNodeRoleV1::Decide),
                CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
                CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
            ],
            edges: vec![
                CircuitEdgeV1::new("work", "work"),
                CircuitEdgeV1::new("work", "success"),
                CircuitEdgeV1::new("work", "failure"),
            ],
            capability_set: vec![],
        },
        digest("route"),
        digest("bundle"),
        digest("resources"),
    );
    assert!(result.is_err());
    definition()
        .validate()
        .expect("explicit V2 feedback profile");
}

pub(super) fn join_definition(mode: CircuitJoinV2) -> BoundedCircuitDefinitionV2 {
    let mut definition = definition();
    let program = &mut definition.programs[0];
    program.entry_node = "fork".to_string();
    program.nodes = vec![
        node("fork", CircuitNodeKindV2::Compute { max_work: 1 }),
        node("left", CircuitNodeKindV2::Compute { max_work: 4 }),
        node("right", CircuitNodeKindV2::Compute { max_work: 4 }),
        node(
            "join",
            CircuitNodeKindV2::Join {
                mode,
                timeout_ms: 50,
            },
        ),
        node(
            "success",
            CircuitNodeKindV2::Exit {
                outcome: CircuitExitV2::Succeeded,
            },
        ),
        node(
            "failure",
            CircuitNodeKindV2::Exit {
                outcome: CircuitExitV2::Failed,
            },
        ),
    ];
    program.nodes[3].output_schema = circuit_join_output_schema_v2();
    program.nodes[4].input_schema = circuit_join_output_schema_v2();
    program.nodes[4].output_schema = circuit_join_output_schema_v2();
    program.edges = vec![
        edge("fork-left", "fork", "left"),
        edge("fork-right", "fork", "right"),
        edge("left-join", "left", "join"),
        edge("right-join", "right", "join"),
        edge("joined", "join", "success"),
    ];
    definition
}

fn fork(definition: &BoundedCircuitDefinitionV2) -> (CircuitRunV2, Vec<CircuitDispatchV2>) {
    let run = CircuitRunV2::prepare(definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, definition, /*now_ms*/ 10);
    let mut completed = completion(&work[0], &["fork-left", "fork-right"], "fork-result");
    completed.actual_work = 1;
    let (run, _) = run
        .reduce(
            definition,
            &CircuitEventV2::Complete {
                completion: completed,
            },
            /*now_ms*/ 11,
        )
        .expect("fork completion");
    advance(&run, definition, /*now_ms*/ 12)
}

#[test]
fn any_join_cancels_surplus_but_retains_unknown_work_until_exact_reconciliation() {
    let definition = join_definition(CircuitJoinV2::Any);
    let (run, work) = fork(&definition);
    assert_eq!(work.len(), 2);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::MarkIndeterminate {
                activation_id: work[1].activation_id,
                observation_digest: digest("lost-provider-ack"),
            },
            /*now_ms*/ 13,
        )
        .expect("unknown");
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["left-join"], "left"),
            },
            /*now_ms*/ 14,
        )
        .expect("left completed");
    let (run, dispatches) = advance(&run, &definition, /*now_ms*/ 15);
    assert!(dispatches.is_empty());
    assert_eq!(
        (run.outcome(), run.unresolved(), run.budget().reserved()),
        (None, 1, 4)
    );
    assert!(run.activations()[&work[1].activation_id].cancel_requested);
    let join = run
        .activations()
        .values()
        .find(|a| a.node_id == "join")
        .expect("join")
        .clone();
    let mut terminal = completion(&work[1], &[], "right-failed");
    terminal.outcome = CircuitExitV2::Failed;
    terminal.actual_work = 1;
    let (run, dispatches) = run
        .reduce(
            &definition,
            &CircuitEventV2::Reconcile {
                completion: terminal,
            },
            /*now_ms*/ 16,
        )
        .expect("reconcile original work");
    assert!(dispatches.is_empty());
    assert_eq!(
        (run.outcome(), run.budget().spent(), run.budget().reserved()),
        (Some(CircuitExitV2::Succeeded), 5, 0)
    );
    assert_eq!(
        run.activations().values().find(|a| a.node_id == "join"),
        Some(&join)
    );
}

#[test]
fn all_join_times_out_without_refunding_in_flight_work() {
    let definition = join_definition(CircuitJoinV2::All);
    let (run, work) = fork(&definition);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["left-join"], "left"),
            },
            /*now_ms*/ 13,
        )
        .expect("one branch");
    let (run, _) = advance(&run, &definition, /*now_ms*/ 63);
    assert_eq!(
        (run.stop_reason(), run.outcome(), run.budget().reserved()),
        (Some(CircuitStopReasonV2::JoinTimeout), None, 4)
    );
    let mut terminal = completion(&work[1], &[], "cancelled-right");
    terminal.outcome = CircuitExitV2::Abstained;
    terminal.actual_work = 0;
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: terminal,
            },
            /*now_ms*/ 64,
        )
        .expect("actual no-work observation");
    assert_eq!(
        (run.outcome(), run.budget().spent()),
        (Some(CircuitExitV2::Failed), 4)
    );
}

#[test]
fn quorum_requires_its_declared_count_and_freezes_arrival_order() {
    let definition = join_definition(CircuitJoinV2::Quorum { required: 2 });
    let (run, work) = fork(&definition);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[1], &["right-join"], "right"),
            },
            /*now_ms*/ 13,
        )
        .expect("right first");
    assert!(
        run.activations()
            .values()
            .any(|a| a.node_id == "join" && a.status == CircuitActivationStatusV2::Joining)
    );
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["left-join"], "left"),
            },
            /*now_ms*/ 14,
        )
        .expect("left second");
    let (run, _) = advance(&run, &definition, /*now_ms*/ 15);
    assert_eq!(run.outcome(), Some(CircuitExitV2::Succeeded));
    assert_eq!(
        run.activations()
            .values()
            .find(|a| a.node_id == "join")
            .expect("join")
            .causal_parents,
        vec![work[1].activation_id, work[0].activation_id]
    );
}

#[test]
fn cancelled_before_dispatch_is_refunded_without_creating_unknown_work() {
    let mut definition = join_definition(CircuitJoinV2::All);
    definition.limits.work_budget = 5;
    let (run, work) = fork(&definition);
    assert!(
        work.is_empty(),
        "the quantum must not hand out its cancelled first dispatch"
    );
    assert_eq!(
        (
            run.stop_reason(),
            run.outcome(),
            run.unresolved(),
            run.budget().spent(),
            run.budget().reserved()
        ),
        (
            Some(CircuitStopReasonV2::WorkBudget),
            Some(CircuitExitV2::Failed),
            0,
            1,
            0
        )
    );
}

#[test]
fn future_feedback_cannot_win_a_join_before_its_declared_delivery_time() {
    let mut definition = join_definition(CircuitJoinV2::Any);
    definition.programs[0].edges[2].feedback_delay_ms = Some(10);
    assert!(
        definition.validate().is_err(),
        "this profile requires a computation boundary before the join"
    );
}

fn child_definition(reservation: u64) -> BoundedCircuitDefinitionV2 {
    let mut definition = definition();
    let mut child = definition.programs[0].clone();
    child.program_id = "child".to_string();
    let parent = &mut definition.programs[0];
    parent.entry_node = "call".to_string();
    parent.nodes[0] = node(
        "call",
        CircuitNodeKindV2::Subcircuit {
            program: "child".to_string(),
            max_work: reservation,
        },
    );
    parent.edges = vec![edge("returned", "call", "success")];
    definition.programs.push(child);
    definition
}

#[test]
fn child_work_is_reserved_before_entry_and_charged_exactly_once_to_the_parent() {
    let definition = child_definition(/*reservation*/ 12);
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    assert_eq!(
        (
            run.budget().reserved(),
            work.len(),
            work[0].program_id.as_str()
        ),
        (12, 1, "child")
    );
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["done"], "child-result"),
            },
            /*now_ms*/ 11,
        )
        .expect("child output");
    let (run, _) = advance(&run, &definition, /*now_ms*/ 12);
    assert_eq!(
        (run.outcome(), run.budget().spent(), run.budget().reserved()),
        (Some(CircuitExitV2::Succeeded), 3, 0)
    );
    let child = run
        .instances
        .values()
        .find(|i| i.program_id == "child")
        .expect("child instance");
    assert_eq!((child.budget.spent(), child.returned), (3, true));
    let exit = run
        .activations()
        .values()
        .find(|a| a.instance_id == 0 && a.node_id == "success")
        .expect("parent exit");
    assert_eq!(
        exit.causal_depth, 4,
        "parent continuation retains child depth"
    );
}

#[test]
fn child_cannot_borrow_unreserved_parent_capacity() {
    let definition = child_definition(/*reservation*/ 4);
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    assert!(work.is_empty());
    assert_eq!(
        (
            run.stop_reason(),
            run.outcome(),
            run.budget().spent(),
            run.budget().reserved()
        ),
        (
            Some(CircuitStopReasonV2::WorkBudget),
            Some(CircuitExitV2::Failed),
            0,
            0
        )
    );
}

#[test]
fn rejected_receipts_leave_original_state_and_reservation_unchanged() {
    let definition = definition();
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    for changed in ["invocation", "route"] {
        let mut receipt = completion(&work[0], &["done"], "output");
        match changed {
            "invocation" => receipt.invocation_digest = digest("other-scope"),
            "route" => receipt.selected_edges = vec!["undeclared-edge".to_string()],
            _ => unreachable!(),
        }
        assert!(
            run.reduce(
                &definition,
                &CircuitEventV2::Complete {
                    completion: receipt
                },
                /*now_ms*/ 11
            )
            .is_err()
        );
        assert_eq!(
            (
                run.budget().spent(),
                run.budget().reserved(),
                run.unresolved()
            ),
            (0, 5, 1)
        );
    }
    let mut changed = definition.clone();
    changed.parameter_bundle_digest = digest("other-bundle");
    assert!(
        run.reduce(
            &changed,
            &CircuitEventV2::Advance { quantum: 1 },
            /*now_ms*/ 11
        )
        .is_err()
    );
    assert!(
        run.reduce(&definition, &CircuitEventV2::Cancel, /*now_ms*/ 9)
            .is_err()
    );
}

#[test]
fn no_progress_and_deadline_stop_admission_without_claiming_unknown_success() {
    let mut definition = definition();
    definition.limits.max_rounds = 10;
    definition.limits.max_no_progress = 1;
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["again"], "same-output"),
            },
            /*now_ms*/ 11,
        )
        .expect("first result");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 21);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["again"], "same-output"),
            },
            /*now_ms*/ 22,
        )
        .expect("no-progress result");
    assert_eq!(
        (run.stop_reason(), run.outcome()),
        (
            Some(CircuitStopReasonV2::NoProgress),
            Some(CircuitExitV2::Failed)
        )
    );
    let run =
        CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("second run");
    let (run, _) = advance(&run, &definition, /*now_ms*/ 10);
    let (run, work) = advance(&run, &definition, /*now_ms*/ 1_010);
    assert!(work.is_empty());
    assert_eq!(
        (run.stop_reason(), run.outcome(), run.budget().reserved()),
        (Some(CircuitStopReasonV2::Deadline), None, 5)
    );
}

#[test]
fn shared_subprogram_dag_has_bounded_validation_and_exact_longest_depth() {
    let mut definition = definition();
    definition.programs.clear();
    definition.entry_program = "p0".to_string();
    definition.limits.max_child_depth = 15;
    for level in 0..16 {
        let nodes = if level == 15 {
            vec![
                node(
                    "success",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Succeeded,
                    },
                ),
                node(
                    "failure",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Failed,
                    },
                ),
            ]
        } else {
            vec![
                node(
                    "a",
                    CircuitNodeKindV2::Subcircuit {
                        program: format!("p{}", level + 1),
                        max_work: 5,
                    },
                ),
                node(
                    "b",
                    CircuitNodeKindV2::Subcircuit {
                        program: format!("p{}", level + 1),
                        max_work: 5,
                    },
                ),
                node(
                    "success",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Succeeded,
                    },
                ),
                node(
                    "failure",
                    CircuitNodeKindV2::Exit {
                        outcome: CircuitExitV2::Failed,
                    },
                ),
            ]
        };
        definition.programs.push(CircuitProgramV2 {
            program_id: format!("p{level}"),
            entry_node: if level == 15 { "success" } else { "a" }.to_string(),
            fallback_node: "failure".to_string(),
            nodes,
            edges: if level == 15 {
                vec![]
            } else {
                vec![edge("a-b", "a", "b"), edge("b-success", "b", "success")]
            },
        });
    }
    definition
        .validate()
        .expect("shared DAG is visited by node/edge, not by 32768 call paths");
    definition.limits.max_child_depth = 14;
    assert!(definition.validate().is_err());
    definition.limits.max_child_depth = 16;
    definition.programs[15].nodes[0].kind = CircuitNodeKindV2::Subcircuit {
        program: "p0".to_string(),
        max_work: 5,
    };
    definition.programs[15]
        .edges
        .push(edge("recursive-exit", "success", "failure"));
    assert!(definition.validate().is_err());
}

#[test]
fn observed_work_overrun_is_charged_in_full_and_stops_admission() {
    let mut definition = definition();
    definition.limits.work_budget = 5;
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    let mut receipt = completion(&work[0], &["done"], "overrun");
    receipt.actual_work = 7;
    let (run, dispatched) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: receipt,
            },
            /*now_ms*/ 11,
        )
        .expect("record known physical work even beyond reservation");
    assert!(dispatched.is_empty());
    assert_eq!(
        (
            run.outcome(),
            run.stop_reason(),
            run.budget().spent(),
            run.budget().available(),
            run.budget().reserved()
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::WorkBudget),
            7,
            0,
            0
        )
    );
}

#[test]
fn overrun_does_not_refund_another_branches_unknown_work() {
    let mut definition = join_definition(CircuitJoinV2::All);
    definition.limits.work_budget = 9;
    let (run, work) = fork(&definition);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::MarkIndeterminate {
                activation_id: work[1].activation_id,
                observation_digest: digest("unknown-right"),
            },
            /*now_ms*/ 13,
        )
        .expect("unknown");
    let mut left = completion(&work[0], &["left-join"], "left-overrun");
    left.actual_work = 6;
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete { completion: left },
            /*now_ms*/ 14,
        )
        .expect("full overrun charge");
    assert_eq!(
        (
            run.outcome(),
            run.unresolved(),
            run.budget().spent(),
            run.budget().reserved(),
            run.budget().available()
        ),
        (None, 1, 7, 4, 0)
    );
    let mut right = completion(&work[1], &[], "right-final");
    right.outcome = CircuitExitV2::Abstained;
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Reconcile { completion: right },
            /*now_ms*/ 15,
        )
        .expect("settle the original unknown invocation");
    assert_eq!(
        (
            run.outcome(),
            run.budget().spent(),
            run.budget().reserved(),
            run.budget().available()
        ),
        (Some(CircuitExitV2::Failed), 10, 0, 0)
    );
}

#[test]
fn child_overrun_debt_propagates_to_every_parent_without_double_charging() {
    let mut definition = child_definition(/*reservation*/ 5);
    definition.limits.work_budget = 5;
    let mut leaf = definition.programs[1].clone();
    leaf.program_id = "leaf".to_string();
    definition.programs[1].nodes[0].kind = CircuitNodeKindV2::Subcircuit {
        program: "leaf".to_string(),
        max_work: 5,
    };
    definition.programs[1]
        .edges
        .retain(|edge| edge.edge_id == "done");
    definition.programs.push(leaf);
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, work) = advance(&run, &definition, /*now_ms*/ 10);
    assert_eq!(work[0].program_id, "leaf");
    let mut actual = completion(&work[0], &["done"], "leaf-overrun");
    actual.actual_work = 8;
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete { completion: actual },
            /*now_ms*/ 11,
        )
        .expect("parent reservations are settled using actual child work");
    assert_eq!(
        (
            run.outcome(),
            run.stop_reason(),
            run.budget().spent(),
            run.budget().available()
        ),
        (
            Some(CircuitExitV2::Failed),
            Some(CircuitStopReasonV2::WorkBudget),
            8,
            0
        )
    );
    assert!(
        run.instances
            .values()
            .all(|instance| instance.budget.spent() == 8
                && instance.budget.reserved() == 0
                && instance.returned)
    );
}

#[test]
fn distinct_cells_in_a_feedback_loop_are_checked_for_progress_independently() {
    let mut definition = definition();
    definition.limits.max_no_progress = 1;
    let program = &mut definition.programs[0];
    program.nodes.push(node(
        "other-cell",
        CircuitNodeKindV2::Compute { max_work: 5 },
    ));
    program.edges = vec![
        edge("next", "decide", "other-cell"),
        CircuitEdgeV2 {
            feedback_delay_ms: Some(10),
            ..edge("again", "other-cell", "decide")
        },
        edge("done", "decide", "success"),
    ];
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, first) = advance(&run, &definition, /*now_ms*/ 10);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&first[0], &["next"], "cell-a-stable"),
            },
            /*now_ms*/ 11,
        )
        .expect("A");
    let (run, second) = advance(&run, &definition, /*now_ms*/ 12);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&second[0], &["again"], "cell-b-different-but-stable"),
            },
            /*now_ms*/ 13,
        )
        .expect("B");
    let (run, reactivated) = advance(&run, &definition, /*now_ms*/ 23);
    assert_eq!(reactivated[0].node_id, first[0].node_id);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&reactivated[0], &["next"], "cell-a-stable"),
            },
            /*now_ms*/ 24,
        )
        .expect("same A result is no progress despite intervening B");
    assert_eq!(
        (run.stop_reason(), run.outcome(), run.budget().spent()),
        (
            Some(CircuitStopReasonV2::NoProgress),
            Some(CircuitExitV2::Failed),
            9
        )
    );
}

#[test]
fn joins_require_the_reference_schema_and_export_the_exact_frozen_bytes() {
    let definition = join_definition(CircuitJoinV2::All);
    let mut mismatched = definition.clone();
    mismatched.programs[0].nodes[3].output_schema = digest("vector-v1");
    mismatched.programs[0].nodes[4].input_schema = digest("vector-v1");
    mismatched.programs[0].nodes[4].output_schema = digest("vector-v1");
    assert!(
        mismatched.validate().is_err(),
        "an internally consistent edge still needs the explicit join schema"
    );
    let (run, work) = fork(&definition);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[1], &["right-join"], "right-result"),
            },
            /*now_ms*/ 13,
        )
        .expect("right arrival");
    let waiting = run
        .activations()
        .values()
        .find(|a| a.node_id == "join")
        .expect("join slot")
        .activation_id;
    assert!(run.join_output_bytes(waiting).is_err());
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&work[0], &["left-join"], "left-result"),
            },
            /*now_ms*/ 14,
        )
        .expect("left arrival");
    assert!(
        run.join_output_bytes(waiting).is_err(),
        "a ready join has not committed output yet"
    );
    let (run, _) = advance(&run, &definition, /*now_ms*/ 15);
    let bytes = run
        .join_output_bytes(waiting)
        .expect("frozen reference envelope");
    let envelope: CircuitJoinEnvelopeV2 = serde_json::from_slice(&bytes).expect("public wire type");
    assert_eq!(
        envelope.causal_parents,
        vec![work[1].activation_id, work[0].activation_id]
    );
    assert_eq!(
        envelope.arrival_input_digests,
        vec![digest("right-result"), digest("left-result")]
    );
    assert_eq!(
        envelope.canonical_bytes().expect("canonical round trip"),
        bytes
    );
    let successor = run
        .activations()
        .values()
        .find(|a| a.node_id == "success")
        .expect("successor");
    assert_eq!(successor.input_digest, Sha256Digest::for_bytes(&bytes));
    assert!(
        run.join_output_bytes(work[0].activation_id).is_err(),
        "ordinary computation is not a join"
    );
}

#[test]
fn returning_subcircuits_preserve_parent_node_progress_across_child_instances() {
    let mut definition = child_definition(/*reservation*/ 12);
    definition.limits.max_no_progress = 1;
    let parent = &mut definition.programs[0];
    parent
        .nodes
        .push(node("gate", CircuitNodeKindV2::Decide { max_work: 5 }));
    parent.edges = vec![
        edge("returned", "call", "gate"),
        CircuitEdgeV2 {
            feedback_delay_ms: Some(10),
            ..edge("again", "gate", "call")
        },
        edge("done", "gate", "success"),
    ];
    let run = CircuitRunV2::prepare(&definition, &start(), &fence(/*generation*/ 1)).expect("run");
    let (run, child) = advance(&run, &definition, /*now_ms*/ 10);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&child[0], &["done"], "stable-child-result"),
            },
            /*now_ms*/ 11,
        )
        .expect("first child result");
    let (run, gate) = advance(&run, &definition, /*now_ms*/ 12);
    assert_eq!(gate[0].node_id, "gate");
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&gate[0], &["again"], "first-parent-gate"),
            },
            /*now_ms*/ 13,
        )
        .expect("another child invocation");
    let (run, child) = advance(&run, &definition, /*now_ms*/ 23);
    let (run, _) = run
        .reduce(
            &definition,
            &CircuitEventV2::Complete {
                completion: completion(&child[0], &["done"], "stable-child-result"),
            },
            /*now_ms*/ 24,
        )
        .expect("same output from a new child instance");
    let (run, dispatches) = advance(&run, &definition, /*now_ms*/ 25);
    assert!(dispatches.is_empty());
    assert_eq!(
        (
            run.stop_reason(),
            run.outcome(),
            run.budget().spent(),
            run.budget().reserved()
        ),
        (
            Some(CircuitStopReasonV2::NoProgress),
            Some(CircuitExitV2::Failed),
            9,
            0
        )
    );
}
