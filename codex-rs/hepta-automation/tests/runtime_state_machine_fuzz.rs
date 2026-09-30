#![allow(
    clippy::expect_used,
    reason = "deterministic state-machine fuzzing requires explicit fixture context"
)]

use std::cell::Cell;

use codex_hepta_automation::CircuitCancellationV1;
use codex_hepta_automation::CircuitChoiceKindV1;
use codex_hepta_automation::CircuitDecisionCellV1;
use codex_hepta_automation::CircuitDecisionRequestV1;
use codex_hepta_automation::CircuitDecisionV1;
use codex_hepta_automation::CircuitEdgeV1;
use codex_hepta_automation::CircuitEventIngressV1;
use codex_hepta_automation::CircuitNodeRoleV1;
use codex_hepta_automation::CircuitNodeV1;
use codex_hepta_automation::CircuitOrganPortV1;
use codex_hepta_automation::CircuitOrganReceiptV1;
use codex_hepta_automation::CircuitOrganRequestV1;
use codex_hepta_automation::CircuitRuntimeOutcomeV1;
use codex_hepta_automation::CircuitRuntimeProfileV1;
use codex_hepta_automation::CircuitWaitJoinPortV1;
use codex_hepta_automation::CircuitWaitReceiptV1;
use codex_hepta_automation::CircuitWaitRequestV1;
use codex_hepta_automation::CircuitWaitStateV1;
use codex_hepta_automation::NeuralCircuitCandidateV1;
use codex_hepta_automation::NeuralCircuitRuntimeError;
use codex_hepta_automation::run_neural_circuit_v1;
use codex_hepta_contracts::Sha256Digest;

fn digest(label: impl AsRef<[u8]>) -> Sha256Digest {
    Sha256Digest::for_bytes(label.as_ref())
}

fn xorshift64(mut value: u64) -> u64 {
    value ^= value << 13;
    value ^= value >> 7;
    value ^= value << 17;
    value
}

fn candidate() -> NeuralCircuitCandidateV1 {
    let mut organ = CircuitNodeV1::new("organ", CircuitNodeRoleV1::OrganCall);
    organ.capability = Some("memory.retrieval".to_string());
    let mut wait = CircuitNodeV1::new("join", CircuitNodeRoleV1::WaitJoin);
    wait.wait_timeout_ms = Some(1_000);
    NeuralCircuitCandidateV1::new(
        "state-machine-fuzz",
        1,
        None,
        "observe",
        vec![
            CircuitNodeV1::new("observe", CircuitNodeRoleV1::Observe),
            CircuitNodeV1::new("decide", CircuitNodeRoleV1::Decide),
            organ,
            wait,
            CircuitNodeV1::effect("effect", "network.http", "fuzz/{run}/effect"),
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure),
        ],
        vec![
            CircuitEdgeV1::new("observe", "decide"),
            CircuitEdgeV1::new("decide", "organ"),
            CircuitEdgeV1::new("decide", "join"),
            CircuitEdgeV1::new("decide", "effect"),
            CircuitEdgeV1::new("decide", "failure"),
            CircuitEdgeV1::new("organ", "join"),
            CircuitEdgeV1::new("join", "success"),
            CircuitEdgeV1::new("effect", "success"),
            CircuitEdgeV1::new("effect", "failure"),
        ],
        vec!["memory.retrieval".to_string(), "network.http".to_string()],
        digest("fuzz-route-policy"),
        digest("fuzz-parameters"),
        digest("fuzz-resources"),
    )
    .expect("state-machine candidate")
}

fn profile(seed: u64) -> CircuitRuntimeProfileV1 {
    CircuitRuntimeProfileV1 {
        max_steps: 2 + u32::try_from(seed % 16).expect("bounded steps"),
        max_depth: 1 + u16::try_from((seed >> 4) % 8).expect("bounded depth"),
        max_feedback_rounds: u16::try_from((seed >> 8) % 5).expect("bounded feedback"),
        cost_budget_units: 1 + ((seed >> 16) % 20),
    }
}

struct FuzzDecision {
    seed: u64,
    feedbacks_remaining: u16,
    calls: u32,
}

impl CircuitDecisionCellV1 for FuzzDecision {
    fn decide(
        &mut self,
        request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError> {
        self.calls = self.calls.saturating_add(1);
        if self.feedbacks_remaining > 0 {
            self.feedbacks_remaining -= 1;
            return Ok(CircuitDecisionV1::Feedback {
                feedback_digest: digest(format!(
                    "feedback:{}:{}:{}",
                    self.seed, request.feedback_round, self.calls
                )),
                cost_units: 1 + (self.seed % 3),
            });
        }
        let next_node = match (self.seed >> 20) % 4 {
            0 => "organ",
            1 => "join",
            2 => "effect",
            _ => "failure",
        };
        Ok(CircuitDecisionV1::Route {
            next_node: next_node.to_string(),
            cost_units: 1 + ((self.seed >> 24) % 3),
            decision_digest: digest(format!("route:{}:{next_node}", self.seed)),
        })
    }
}

struct FuzzOrgan {
    seed: u64,
}

impl CircuitOrganPortV1 for FuzzOrgan {
    fn call(
        &mut self,
        request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError> {
        Ok(CircuitOrganReceiptV1 {
            output_digest: digest(format!("organ:{}:{}", self.seed, request.node_id)),
            cost_units: 1 + ((self.seed >> 28) % 4),
        })
    }
}

struct FuzzWait {
    seed: u64,
}

impl CircuitWaitJoinPortV1 for FuzzWait {
    fn wait(
        &mut self,
        request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError> {
        Ok(CircuitWaitReceiptV1 {
            state: if (self.seed >> 32) & 1 == 0 {
                CircuitWaitStateV1::Ready
            } else {
                CircuitWaitStateV1::Pending
            },
            observation_digest: digest(format!("wait:{}:{}", self.seed, request.node_id)),
            cost_units: (self.seed >> 33) % 3,
        })
    }
}

struct CancelAfter {
    checks: Cell<u32>,
    threshold: u32,
}

impl CircuitCancellationV1 for CancelAfter {
    fn is_cancelled(&self) -> bool {
        let checks = self.checks.get();
        self.checks.set(checks.saturating_add(1));
        checks >= self.threshold
    }
}

fn execute(seed: u64) -> Result<CircuitRuntimeOutcomeV1, NeuralCircuitRuntimeError> {
    let mutated = xorshift64(seed.wrapping_add(0x9e37_79b9_7f4a_7c15));
    let event = CircuitEventIngressV1::new(
        format!("event-{seed}"),
        digest(format!("payload-{mutated}")),
        if mutated & 1 == 0 {
            Some(digest(format!("parent-{seed}")))
        } else {
            None
        },
    )
    .expect("event");
    let mut decision = FuzzDecision {
        seed: mutated,
        feedbacks_remaining: u16::try_from((mutated >> 12) % 7).expect("bounded feedback plan"),
        calls: 0,
    };
    let mut organ = FuzzOrgan { seed: mutated };
    let mut wait = FuzzWait { seed: mutated };
    let cancellation = CancelAfter {
        checks: Cell::new(0),
        threshold: u32::try_from((mutated >> 36) % 12).expect("bounded cancellation"),
    };
    run_neural_circuit_v1(
        &candidate(),
        &event,
        &profile(mutated),
        &mut decision,
        &mut organ,
        &mut wait,
        &cancellation,
    )
}

#[test]
fn deterministic_state_machine_fuzz_preserves_runtime_invariants() {
    for seed in 0_u64..4_096 {
        let mutated = xorshift64(seed.wrapping_add(0x9e37_79b9_7f4a_7c15));
        let limits = profile(mutated);
        let first = execute(seed);
        let second = execute(seed);
        assert_eq!(first, second, "seed {seed} is not replay deterministic");

        match first {
            Ok(CircuitRuntimeOutcomeV1::Terminal(receipt)) => {
                assert!(receipt.trace.steps <= limits.max_steps);
                assert!(receipt.trace.depth <= limits.max_depth);
                assert!(receipt.trace.consumed_cost_units <= limits.cost_budget_units);
                for choice in &receipt.trace.recorded_choices {
                    match choice.kind {
                        CircuitChoiceKindV1::Route => assert!(matches!(
                            choice.selected_node.as_str(),
                            "organ" | "join" | "effect" | "failure"
                        )),
                        CircuitChoiceKindV1::Feedback => {
                            assert_eq!(choice.selected_node, "decide")
                        }
                    }
                }
                assert_eq!(receipt.receipt_digest.as_str().len(), 64);
            }
            Ok(CircuitRuntimeOutcomeV1::WaitPending(boundary)) => {
                assert_eq!(boundary.node_id, "join");
                assert!(boundary.trace.steps <= limits.max_steps);
                assert!(boundary.trace.depth <= limits.max_depth);
                assert!(boundary.trace.consumed_cost_units <= limits.cost_budget_units);
                assert_eq!(boundary.boundary_digest.as_str().len(), 64);
            }
            Ok(CircuitRuntimeOutcomeV1::EffectPending(boundary)) => {
                assert_eq!(boundary.node_id, "effect");
                assert_eq!(boundary.capability, "network.http");
                assert!(boundary.trace.steps <= limits.max_steps);
                assert!(boundary.trace.depth <= limits.max_depth);
                assert!(boundary.trace.consumed_cost_units <= limits.cost_budget_units);
                assert_eq!(boundary.boundary_digest.as_str().len(), 64);
            }
            Err(
                NeuralCircuitRuntimeError::CostBudgetExhausted
                | NeuralCircuitRuntimeError::StepBudgetExhausted
                | NeuralCircuitRuntimeError::DepthBudgetExhausted
                | NeuralCircuitRuntimeError::FeedbackBudgetExhausted,
            ) => {}
            Err(error) => panic!("seed {seed} reached an unexpected state: {error}"),
        }
    }
}
