use codex_hepta_contracts::Sha256Digest;

use crate::CircuitEdgeV1;
use crate::CircuitNodeRoleV1;
use crate::CircuitNodeV1;
use crate::NeuralCircuitCandidateV1;

use super::*;

fn digest(label: &str) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_bytes())
}

fn event() -> CircuitEventIngressV1 {
    CircuitEventIngressV1::new("event-1", digest("payload"), None).expect("event")
}

struct RouteTo {
    next: String,
    feedbacks_remaining: u16,
}

impl CircuitDecisionCellV1 for RouteTo {
    fn decide(
        &mut self,
        request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        if self.feedbacks_remaining > 0 {
            self.feedbacks_remaining -= 1;
            return Ok(CircuitDecisionV1::Feedback {
                feedback_digest: digest(&format!("feedback-{}", request.feedback_round)),
                cost_units: 1,
            });
        }
        Ok(CircuitDecisionV1::Route {
            next_node: self.next.clone(),
            cost_units: 2,
            decision_digest: digest("route"),
        })
    }
}

struct ReadyOrgan;

impl CircuitOrganPortV1 for ReadyOrgan {
    fn call(
        &mut self,
        request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        Ok(CircuitOrganReceiptV1 {
            output_digest: digest(&format!("organ:{}", request.node_id)),
            cost_units: 3,
        })
    }
}

struct ReadyWait;

impl CircuitWaitJoinPortV1 for ReadyWait {
    fn wait(
        &mut self,
        request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        Ok(CircuitWaitReceiptV1 {
            state: CircuitWaitStateV1::Ready,
            observation_digest: digest(&format!("wait:{}", request.node_id)),
            cost_units: 1,
        })
    }
}

fn vertical_slice() -> NeuralCircuitCandidateV1 {
    let mut organ = CircuitNodeV1::new("organ", CircuitNodeRoleV1::OrganCall);
    organ.capability = Some("memory.retrieval".to_string());
    let mut wait = CircuitNodeV1::new("join", CircuitNodeRoleV1::WaitJoin);
    wait.wait_timeout_ms = Some(1_000);
    NeuralCircuitCandidateV1::new(
        "vertical-slice",
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
            organ,
            wait,
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "decide"),
            CircuitEdgeV1::new("decide", "organ"),
            CircuitEdgeV1::new("decide", "failure"),
            CircuitEdgeV1::new("organ", "join"),
            CircuitEdgeV1::new("join", "success"),
        ],
        vec!["memory.retrieval".to_string()],
        digest("route-policy"),
        digest("parameters"),
        digest("resources"),
    )
    .expect("circuit")
}

fn run_terminal(profile: &CircuitRuntimeProfileV1) -> CircuitTerminalReceiptV1 {
    let candidate = vertical_slice();
    let mut decision = RouteTo {
        next: "organ".to_string(),
        feedbacks_remaining: 1,
    };
    let mut organ = ReadyOrgan;
    let mut wait = ReadyWait;
    let outcome = run_neural_circuit_v1(
        &candidate,
        &event(),
        profile,
        &mut decision,
        &mut organ,
        &mut wait,
        &NeverCancelled,
    )
    .expect("runtime");
    let CircuitRuntimeOutcomeV1::Terminal(receipt) = outcome else {
        panic!("expected terminal receipt");
    };
    receipt
}

#[test]
fn vertical_slice_records_choice_organ_wait_and_terminal_receipt() {
    let receipt = run_terminal(&CircuitRuntimeProfileV1::default());
    assert_eq!(receipt.state, CircuitTerminalStateV1::Succeeded);
    assert_eq!(receipt.terminal_node_id, "success");
    assert_eq!(receipt.trace.recorded_choices.len(), 2);
    assert_eq!(receipt.trace.observation_digests.len(), 2);
    assert_eq!(receipt.trace.consumed_cost_units, 7);
}

#[test]
fn terminal_receipt_binds_the_exact_runtime_profile() {
    let baseline = run_terminal(&CircuitRuntimeProfileV1::default());
    let constrained = run_terminal(&CircuitRuntimeProfileV1 {
        max_steps: 64,
        max_depth: 64,
        max_feedback_rounds: 4,
        cost_budget_units: 1_000,
    });
    assert_ne!(
        baseline.trace.runtime_profile_digest,
        constrained.trace.runtime_profile_digest
    );
    assert_ne!(baseline.trace.trace_digest, constrained.trace.trace_digest);
    assert_ne!(baseline.receipt_digest, constrained.receipt_digest);
}

#[test]
fn forged_event_digest_is_rejected_before_runtime_port_contact() {
    let candidate = vertical_slice();
    let mut ingress = event();
    ingress.event_id = "event-tampered".to_string();
    let mut decision = RouteTo {
        next: "organ".to_string(),
        feedbacks_remaining: 0,
    };
    let mut organ = ReadyOrgan;
    let mut wait = ReadyWait;
    let error = run_neural_circuit_v1(
        &candidate,
        &ingress,
        &CircuitRuntimeProfileV1::default(),
        &mut decision,
        &mut organ,
        &mut wait,
        &NeverCancelled,
    )
    .expect_err("tampered ingress must fail closed");
    assert!(matches!(
        error,
        NeuralCircuitRuntimeError::Invalid(message) if message.contains("event_digest")
    ));
}

#[test]
fn feedback_is_bounded_without_adding_a_graph_cycle() {
    let candidate = vertical_slice();
    let mut decision = RouteTo {
        next: "organ".to_string(),
        feedbacks_remaining: u16::MAX,
    };
    let mut organ = ReadyOrgan;
    let mut wait = ReadyWait;
    let profile = CircuitRuntimeProfileV1 {
        max_feedback_rounds: 2,
        ..CircuitRuntimeProfileV1::default()
    };
    assert_eq!(
        run_neural_circuit_v1(
            &candidate,
            &event(),
            &profile,
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .expect_err("bounded feedback"),
        NeuralCircuitRuntimeError::FeedbackBudgetExhausted
    );
}

struct AlwaysCancelled;

impl CircuitCancellationV1 for AlwaysCancelled {
    fn is_cancelled(&self) -> bool {
        true
    }
}

#[test]
fn cancellation_produces_a_terminal_receipt_before_port_contact() {
    let candidate = vertical_slice();
    let mut decision = RouteTo {
        next: "organ".to_string(),
        feedbacks_remaining: 0,
    };
    let mut organ = ReadyOrgan;
    let mut wait = ReadyWait;
    let outcome = run_neural_circuit_v1(
        &candidate,
        &event(),
        &CircuitRuntimeProfileV1::default(),
        &mut decision,
        &mut organ,
        &mut wait,
        &AlwaysCancelled,
    )
    .expect("cancelled");
    let CircuitRuntimeOutcomeV1::Terminal(receipt) = outcome else {
        panic!("expected terminal receipt");
    };
    assert_eq!(receipt.state, CircuitTerminalStateV1::Cancelled);
    assert_eq!(receipt.trace.steps, 0);
}

#[test]
fn effect_is_returned_to_the_existing_authorized_boundary() {
    let candidate = NeuralCircuitCandidateV1::new(
        "effect-boundary",
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::effect("effect", "network.http", "circuit/{run}/effect"),
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "effect"),
            CircuitEdgeV1::new("effect", "success"),
            CircuitEdgeV1::new("effect", "failure"),
        ],
        vec!["network.http".to_string()],
        digest("route-policy"),
        digest("parameters"),
        digest("resources"),
    )
    .expect("circuit");
    let mut decision = RouteTo {
        next: "success".to_string(),
        feedbacks_remaining: 0,
    };
    let mut organ = ReadyOrgan;
    let mut wait = ReadyWait;
    let outcome = run_neural_circuit_v1(
        &candidate,
        &event(),
        &CircuitRuntimeProfileV1::default(),
        &mut decision,
        &mut organ,
        &mut wait,
        &NeverCancelled,
    )
    .expect("runtime");
    let CircuitRuntimeOutcomeV1::EffectPending(boundary) = outcome else {
        panic!("expected effect boundary");
    };
    assert_eq!(boundary.capability, "network.http");
    assert_eq!(boundary.node_id, "effect");
}

#[test]
fn deterministic_route_fuzz_never_escapes_admitted_edges() {
    for seed in 0_u16..256 {
        let candidate = vertical_slice();
        let mut decision = RouteTo {
            next: if seed % 2 == 0 {
                "organ".to_string()
            } else {
                "failure".to_string()
            },
            feedbacks_remaining: seed % 3,
        };
        let mut organ = ReadyOrgan;
        let mut wait = ReadyWait;
        let outcome = run_neural_circuit_v1(
            &candidate,
            &event(),
            &CircuitRuntimeProfileV1::default(),
            &mut decision,
            &mut organ,
            &mut wait,
            &NeverCancelled,
        )
        .expect("admitted route");
        assert!(matches!(outcome, CircuitRuntimeOutcomeV1::Terminal(_)));
    }
}
