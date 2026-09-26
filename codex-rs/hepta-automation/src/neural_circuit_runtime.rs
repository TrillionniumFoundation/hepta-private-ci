//! Minimal durable Neural Circuit runtime on the existing TaskFlow owner.
//!
//! This module does not introduce a scheduler, store, authority issuer or
//! provider transport. It compiles one admitted circuit into the existing
//! TaskFlow definition, records DecisionCell/organ/join evidence in the
//! existing durable step outbox, advances the graph with fenced TaskFlow
//! `Wait`/`Resume` events, and hands effect execution to the existing
//! final-use-authorized seam.

#![allow(
    clippy::too_many_arguments,
    reason = "durable circuit boundaries keep every identity and fence explicit"
)]

use std::future::Future;
use std::pin::Pin;

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;

use crate::AuthorizedEffectIntent;
use crate::AutomationStore;
use crate::CircuitCompilationReceiptV1;
use crate::CircuitNodeRoleV1;
use crate::CircuitNodeV1;
use crate::NeuralCircuitCandidateV1;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;

pub const NEURAL_CIRCUIT_RUNTIME_SCHEMA_VERSION: u32 = 1;
pub const MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH: u32 = 256;
pub const MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS: u32 = 32;
const MAX_RUNTIME_TEXT_BYTES: usize = 128;

pub type NeuralCircuitDecisionFuture<'a> =
    Pin<Box<dyn Future<Output = Result<NeuralCircuitDecisionV1, TaskFlowError>> + Send + 'a>>;
pub type NeuralCircuitOrganFuture<'a> = Pin<
    Box<dyn Future<Output = Result<NeuralCircuitOrganObservationV1, TaskFlowError>> + Send + 'a>,
>;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitRuntimeBudgetV1 {
    pub max_depth: u32,
    pub max_feedback_rounds: u32,
}

impl NeuralCircuitRuntimeBudgetV1 {
    pub fn new(max_depth: u32, max_feedback_rounds: u32) -> Result<Self, TaskFlowError> {
        if max_depth == 0
            || max_depth > MAX_NEURAL_CIRCUIT_RUNTIME_DEPTH
            || max_feedback_rounds > MAX_NEURAL_CIRCUIT_FEEDBACK_ROUNDS
        {
            return Err(invalid(
                "neural circuit runtime budget is outside the bounded limit",
            ));
        }
        Ok(Self {
            max_depth,
            max_feedback_rounds,
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitIngressV1 {
    pub activation_id: String,
    pub thread_id: String,
    pub input_digest: Sha256Digest,
}

impl NeuralCircuitIngressV1 {
    pub fn new(
        activation_id: impl Into<String>,
        thread_id: impl Into<String>,
        input_digest: Sha256Digest,
    ) -> Result<Self, TaskFlowError> {
        let ingress = Self {
            activation_id: activation_id.into(),
            thread_id: thread_id.into(),
            input_digest,
        };
        validate_text(&ingress.activation_id, "activation_id")?;
        validate_text(&ingress.thread_id, "thread_id")?;
        validate_digest(&ingress.input_digest, "input digest")?;
        Ok(ingress)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitActivationReceiptV1 {
    pub run_id: String,
    pub circuit_id: String,
    pub circuit_version: u32,
    pub circuit_digest: Sha256Digest,
    pub taskflow_definition_digest: Sha256Digest,
    pub ingress: NeuralCircuitIngressV1,
    pub budget: NeuralCircuitRuntimeBudgetV1,
    pub binding_digest: Sha256Digest,
    pub compilation: CircuitCompilationReceiptV1,
    pub run: TaskFlowRun,
    pub authority_granted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitDecisionRequestV1 {
    pub run_id: String,
    pub node_id: String,
    pub round: u32,
    pub candidates: Vec<String>,
    pub input_digest: Sha256Digest,
    pub route_policy_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub resource_profile_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NeuralCircuitDecisionV1 {
    Route { selected_node: String },
    Feedback,
}

pub trait NeuralCircuitDecisionCellV1: Send + Sync {
    fn decide(&self, request: NeuralCircuitDecisionRequestV1) -> NeuralCircuitDecisionFuture<'_>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NeuralCircuitDecisionProgressV1 {
    Routed {
        selected_node: String,
        round: u32,
        choice_digest: Sha256Digest,
        replayed: bool,
        run: TaskFlowRun,
    },
    Feedback {
        round: u32,
        choice_digest: Sha256Digest,
        replayed: bool,
    },
    FeedbackBudgetExhausted {
        round: u32,
        terminal: NeuralCircuitTerminalReceiptV1,
    },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitOrganRequestV1 {
    pub run_id: String,
    pub node_id: String,
    pub capability: Option<String>,
    pub input_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitOrganObservationV1 {
    pub output_digest: Sha256Digest,
}

pub trait NeuralCircuitOrganPortV1: Send + Sync {
    fn invoke(&self, request: NeuralCircuitOrganRequestV1) -> NeuralCircuitOrganFuture<'_>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitOrganReceiptV1 {
    pub node_id: String,
    pub output_digest: Sha256Digest,
    pub replayed: bool,
    pub run: TaskFlowRun,
    pub authority_granted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitWaitReceiptV1 {
    pub wait_node: String,
    pub resume_node: String,
    pub wait_token: String,
    pub run: TaskFlowRun,
    pub authority_granted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitEffectHandoffV1 {
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub capability: String,
    pub idempotency_key: String,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
    pub authority_granted: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NeuralCircuitTerminalReceiptV1 {
    pub run_id: String,
    pub state: TaskFlowRunState,
    pub current_node: String,
    pub state_digest: Sha256Digest,
    pub revision: u64,
    pub terminal_receipt_digest: Sha256Digest,
    pub authority_granted: bool,
}

impl AutomationStore {
    /// Compile, register, create, claim and start one activation on the existing
    /// TaskFlow owner. Reopening the same activation with changed input/budget
    /// conflicts through the immutable run binding.
    pub async fn admit_neural_circuit_activation_v1(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        ingress: &NeuralCircuitIngressV1,
        budget: NeuralCircuitRuntimeBudgetV1,
        fence: &TaskFlowFence,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<NeuralCircuitActivationReceiptV1, TaskFlowError> {
        candidate.validate()?;
        validate_text(&ingress.activation_id, "activation_id")?;
        validate_text(&ingress.thread_id, "thread_id")?;
        validate_digest(&ingress.input_digest, "input digest")?;
        let (definition, compilation) = candidate.compile_taskflow()?;
        self.register_taskflow_definition(&definition, fence, now_ms)
            .await?;

        let run_id = format!(
            "circuit:{}:{}",
            candidate.circuit_digest.as_str(),
            ingress.activation_id
        );
        validate_text(&run_id, "circuit run id")?;
        let binding_digest = circuit_binding_digest(candidate, ingress, budget)?;
        let thread_binding = format!("circuit-ingress:{}", binding_digest.as_str());
        let run = self
            .create_taskflow_run(
                &run_id,
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                thread_binding,
                now_ms,
            )
            .await?;
        let mut run = self
            .claim_taskflow_run(&run.run_id, fence, now_ms, lease_duration_ms)
            .await?;
        if run.state == TaskFlowRunState::Queued {
            let command = TaskFlowCommand::new(
                &run.run_id,
                circuit_command_id("start", &run.run_id, run.revision)?,
                fence.clone(),
                run.revision,
                TaskFlowTransition::Start,
                now_ms,
            )?;
            self.apply_taskflow_command(&command).await?;
            run = required_run(self, &run.run_id).await?;
        }
        if !matches!(
            run.state,
            TaskFlowRunState::Running
                | TaskFlowRunState::Waiting
                | TaskFlowRunState::Succeeded
                | TaskFlowRunState::Failed
                | TaskFlowRunState::Cancelled
                | TaskFlowRunState::Indeterminate
        ) {
            return Err(TaskFlowError::Conflict(
                "circuit activation did not reach an admitted TaskFlow state".to_string(),
            ));
        }
        Ok(NeuralCircuitActivationReceiptV1 {
            run_id,
            circuit_id: candidate.circuit_id.clone(),
            circuit_version: candidate.version,
            circuit_digest: candidate.circuit_digest.clone(),
            taskflow_definition_digest: definition.definition_digest().clone(),
            ingress: ingress.clone(),
            budget,
            binding_digest,
            compilation,
            run,
            authority_granted: false,
        })
    }

    /// Invoke or replay one DecisionCell. A durable step receipt is checked
    /// before the cell is called, so recovery never re-infers a recorded route.
    pub async fn advance_neural_circuit_decision_v1<C: NeuralCircuitDecisionCellV1>(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        decision_node: &str,
        cell: &C,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<NeuralCircuitDecisionProgressV1, TaskFlowError> {
        let mut run = validate_activation(self, candidate, activation).await?;
        let node = circuit_node(candidate, decision_node)?;
        if node.role != CircuitNodeRoleV1::Decide {
            return Err(invalid("decision runtime requires a Decide node"));
        }
        let candidates = outgoing(candidate, decision_node)?;
        if candidates.is_empty() {
            return Err(TaskFlowError::Corrupt(
                "decision node has no admitted route".to_string(),
            ));
        }
        for round in 1..=activation.budget.max_feedback_rounds.saturating_add(1) {
            let request = NeuralCircuitDecisionRequestV1 {
                run_id: activation.run_id.clone(),
                node_id: decision_node.to_string(),
                round,
                candidates: candidates.clone(),
                input_digest: activation.ingress.input_digest.clone(),
                route_policy_digest: candidate.route_policy_digest.clone(),
                parameter_bundle_digest: candidate.parameter_bundle_digest.clone(),
                resource_profile_digest: candidate.resource_profile_digest.clone(),
            };
            let intent_digest =
                canonical_digest("hepta.neural-circuit.decision-request.v1", &request)?;
            if let Some(existing) = self
                .read_taskflow_step(&activation.run_id, decision_node, round, fence)
                .await?
            {
                let choice = reconstruct_decision(
                    candidate,
                    activation,
                    decision_node,
                    round,
                    &candidates,
                    &existing,
                )?;
                match choice {
                    NeuralCircuitDecisionV1::Feedback => {
                        if round > activation.budget.max_feedback_rounds {
                            let terminal = self
                                .cancel_neural_circuit_activation_v1(
                                    activation,
                                    fence,
                                    "neural_circuit_feedback_budget_exhausted",
                                    now_ms,
                                )
                                .await?;
                            return Ok(NeuralCircuitDecisionProgressV1::FeedbackBudgetExhausted {
                                round,
                                terminal,
                            });
                        }
                        // A recovered feedback receipt is history, not a new
                        // response. Continue to the first missing bounded round
                        // instead of re-invoking or getting stuck on the same cell.
                        continue;
                    }
                    NeuralCircuitDecisionV1::Route { selected_node } => {
                        if run.current_node == decision_node {
                            ensure_depth(self, activation).await?;
                            run = advance_edge(
                                self,
                                candidate,
                                &run,
                                decision_node,
                                &selected_node,
                                fence,
                                now_ms,
                            )
                            .await?;
                        } else if run.current_node != selected_node {
                            return Err(TaskFlowError::Conflict(
                                "recorded decision does not match current circuit frontier"
                                    .to_string(),
                            ));
                        }
                        return Ok(NeuralCircuitDecisionProgressV1::Routed {
                            selected_node,
                            round,
                            choice_digest: required_receipt_digest(&existing)?,
                            replayed: true,
                            run,
                        });
                    }
                }
            }

            if run.current_node != decision_node || run.state != TaskFlowRunState::Running {
                return Err(TaskFlowError::Conflict(
                    "decision node is not the active circuit frontier".to_string(),
                ));
            }
            let choice = cell.decide(request).await?;
            let choice_digest =
                decision_choice_digest(candidate, activation, decision_node, round, &choice)?;
            record_local_step(
                self,
                &activation.run_id,
                decision_node,
                round,
                fence,
                &intent_digest,
                &choice_digest,
                &choice_digest,
                now_ms,
            )
            .await?;
            match choice {
                NeuralCircuitDecisionV1::Feedback => {
                    if round > activation.budget.max_feedback_rounds {
                        let terminal = self
                            .cancel_neural_circuit_activation_v1(
                                activation,
                                fence,
                                "neural_circuit_feedback_budget_exhausted",
                                now_ms,
                            )
                            .await?;
                        return Ok(NeuralCircuitDecisionProgressV1::FeedbackBudgetExhausted {
                            round,
                            terminal,
                        });
                    }
                    return Ok(NeuralCircuitDecisionProgressV1::Feedback {
                        round,
                        choice_digest,
                        replayed: false,
                    });
                }
                NeuralCircuitDecisionV1::Route { selected_node } => {
                    if !candidates
                        .iter()
                        .any(|candidate| candidate == &selected_node)
                    {
                        return Err(invalid("DecisionCell selected a non-admitted route"));
                    }
                    ensure_depth(self, activation).await?;
                    run = advance_edge(
                        self,
                        candidate,
                        &run,
                        decision_node,
                        &selected_node,
                        fence,
                        now_ms,
                    )
                    .await?;
                    return Ok(NeuralCircuitDecisionProgressV1::Routed {
                        selected_node,
                        round,
                        choice_digest,
                        replayed: false,
                        run,
                    });
                }
            }
        }
        Err(TaskFlowError::Corrupt(
            "bounded decision loop exited without progress".to_string(),
        ))
    }

    /// Invoke a typed Observe/TransformGuard/OrganCall port and durably record
    /// its receipt before moving to the single admitted successor.
    pub async fn advance_neural_circuit_organ_v1<P: NeuralCircuitOrganPortV1>(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        node_id: &str,
        input_digest: &Sha256Digest,
        port: &P,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<NeuralCircuitOrganReceiptV1, TaskFlowError> {
        let mut run = validate_activation(self, candidate, activation).await?;
        let node = circuit_node(candidate, node_id)?;
        if !matches!(
            node.role,
            CircuitNodeRoleV1::Observe
                | CircuitNodeRoleV1::TransformGuard
                | CircuitNodeRoleV1::OrganCall
        ) {
            return Err(invalid(
                "organ runtime requires an observe/guard/organ node",
            ));
        }
        validate_digest(input_digest, "organ input digest")?;
        let target = single_outgoing(candidate, node_id)?;
        let request = NeuralCircuitOrganRequestV1 {
            run_id: activation.run_id.clone(),
            node_id: node_id.to_string(),
            capability: node.capability.clone(),
            input_digest: input_digest.clone(),
        };
        let intent_digest = canonical_digest("hepta.neural-circuit.organ-request.v1", &request)?;
        let existing = self
            .read_taskflow_step(&activation.run_id, node_id, 1, fence)
            .await?;
        let (output_digest, replayed) = if let Some(receipt) = existing {
            if receipt.intent_digest != intent_digest {
                return Err(TaskFlowError::Conflict(
                    "organ receipt is bound to another input".to_string(),
                ));
            }
            (required_receipt_digest(&receipt)?, true)
        } else {
            if run.current_node != node_id || run.state != TaskFlowRunState::Running {
                return Err(TaskFlowError::Conflict(
                    "organ node is not the active circuit frontier".to_string(),
                ));
            }
            let observation = port.invoke(request).await?;
            validate_digest(&observation.output_digest, "organ output digest")?;
            record_local_step(
                self,
                &activation.run_id,
                node_id,
                1,
                fence,
                &intent_digest,
                &observation.output_digest,
                &observation.output_digest,
                now_ms,
            )
            .await?;
            (observation.output_digest, false)
        };
        if run.current_node == node_id {
            ensure_depth(self, activation).await?;
            run = advance_edge(self, candidate, &run, node_id, &target, fence, now_ms).await?;
        } else if run.current_node != target {
            return Err(TaskFlowError::Conflict(
                "organ receipt does not match current circuit frontier".to_string(),
            ));
        }
        Ok(NeuralCircuitOrganReceiptV1 {
            node_id: node_id.to_string(),
            output_digest,
            replayed,
            run,
            authority_granted: false,
        })
    }

    /// Enter a durable join. The TaskFlow wait event moves the projection to the
    /// single successor and retains the opaque wait token until explicit resume.
    pub async fn begin_neural_circuit_wait_v1(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        wait_node: &str,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<NeuralCircuitWaitReceiptV1, TaskFlowError> {
        let run = validate_activation(self, candidate, activation).await?;
        let node = circuit_node(candidate, wait_node)?;
        if node.role != CircuitNodeRoleV1::WaitJoin {
            return Err(invalid("wait runtime requires a WaitJoin node"));
        }
        let target = single_outgoing(candidate, wait_node)?;
        let wait_token = wait_token(activation, wait_node, &target)?;
        if run.state == TaskFlowRunState::Waiting
            && run.current_node == target
            && run.wait_token.as_deref() == Some(wait_token.as_str())
        {
            return Ok(NeuralCircuitWaitReceiptV1 {
                wait_node: wait_node.to_string(),
                resume_node: target,
                wait_token,
                run,
                authority_granted: false,
            });
        }
        if run.state != TaskFlowRunState::Running || run.current_node != wait_node {
            return Err(TaskFlowError::Conflict(
                "wait node is not the active circuit frontier".to_string(),
            ));
        }
        ensure_depth(self, activation).await?;
        let command = TaskFlowCommand::new(
            &run.run_id,
            circuit_command_id("wait", &run.run_id, run.revision)?,
            fence.clone(),
            run.revision,
            TaskFlowTransition::Wait {
                token: wait_token.clone(),
                resume_node: Some(target.clone()),
            },
            now_ms,
        )?;
        self.apply_taskflow_command(&command).await?;
        let run = required_run(self, &run.run_id).await?;
        Ok(NeuralCircuitWaitReceiptV1 {
            wait_node: wait_node.to_string(),
            resume_node: target,
            wait_token,
            run,
            authority_granted: false,
        })
    }

    pub async fn resume_neural_circuit_wait_v1(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        wait: &NeuralCircuitWaitReceiptV1,
        join_receipt_digest: &Sha256Digest,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<TaskFlowRun, TaskFlowError> {
        validate_digest(join_receipt_digest, "join receipt digest")?;
        let run = validate_activation(self, candidate, activation).await?;
        let target = single_outgoing(candidate, &wait.wait_node)?;
        if target != wait.resume_node
            || wait.wait_token != wait_token(activation, &wait.wait_node, &target)?
        {
            return Err(TaskFlowError::Conflict(
                "wait receipt is not bound to this activation".to_string(),
            ));
        }
        if run.state == TaskFlowRunState::Running && run.current_node == target {
            return Ok(run);
        }
        if run.state != TaskFlowRunState::Waiting
            || run.current_node != target
            || run.wait_token.as_deref() != Some(wait.wait_token.as_str())
        {
            return Err(TaskFlowError::Conflict(
                "join token does not match the durable wait frontier".to_string(),
            ));
        }
        let intent_digest = canonical_digest(
            "hepta.neural-circuit.wait-intent.v1",
            &(
                activation.run_id.as_str(),
                wait.wait_node.as_str(),
                target.as_str(),
            ),
        )?;
        record_local_step(
            self,
            &activation.run_id,
            &wait.wait_node,
            1,
            fence,
            &intent_digest,
            join_receipt_digest,
            join_receipt_digest,
            now_ms,
        )
        .await?;
        let command = TaskFlowCommand::new(
            &run.run_id,
            circuit_command_id("resume", &run.run_id, run.revision)?,
            fence.clone(),
            run.revision,
            TaskFlowTransition::Resume {
                token: wait.wait_token.clone(),
            },
            now_ms,
        )?;
        self.apply_taskflow_command(&command).await?;
        required_run(self, &run.run_id).await
    }

    /// Prepare the exact TaskFlow step consumed by the existing Agentd
    /// final-use-authorized effect host. The runtime does not call a provider or
    /// issue a grant. Effect nodes are terminalizing in this first slice.
    pub async fn prepare_neural_circuit_effect_v1(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        intent: &AuthorizedEffectIntent,
        wire_payload: &[u8],
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<NeuralCircuitEffectHandoffV1, TaskFlowError> {
        let run = validate_activation(self, candidate, activation).await?;
        let node = circuit_node(candidate, &intent.step_id)?;
        if node.role != CircuitNodeRoleV1::Effect {
            return Err(invalid("effect handoff requires an Effect node"));
        }
        if run.state != TaskFlowRunState::Running || run.current_node != intent.step_id {
            return Err(TaskFlowError::Conflict(
                "effect node is not the active circuit frontier".to_string(),
            ));
        }
        if intent.run_id != activation.run_id || intent.attempt == 0 {
            return Err(TaskFlowError::Conflict(
                "effect intent is not bound to this activation".to_string(),
            ));
        }
        let capability = node
            .capability
            .clone()
            .ok_or_else(|| TaskFlowError::Corrupt("effect capability is missing".to_string()))?;
        let template = node.idempotency_template.as_deref().ok_or_else(|| {
            TaskFlowError::Corrupt("effect idempotency template is missing".to_string())
        })?;
        let payload_digest = Sha256Digest::for_bytes(wire_payload);
        if payload_digest != intent.payload_digest {
            return Err(invalid("effect wire payload digest does not match intent"));
        }
        let intent_digest = intent
            .digest()
            .map_err(|error| invalid(format!("effect intent digest: {error}")))?;
        let idempotency_key = format!(
            "{}:{}",
            template,
            canonical_digest(
                "hepta.neural-circuit.effect-key.v1",
                &(activation.run_id.as_str(), intent.step_id.as_str()),
            )?
            .as_str()
        );
        let current = self
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, fence)
            .await?;
        if let Some(receipt) = current {
            if receipt.intent_digest != intent_digest || receipt.payload_digest != payload_digest {
                return Err(TaskFlowError::Conflict(
                    "effect step is already bound to another intent".to_string(),
                ));
            }
            if !matches!(
                receipt.state,
                TaskFlowStepState::Claimed
                    | TaskFlowStepState::Recorded
                    | TaskFlowStepState::Reconciled
            ) {
                self.claim_taskflow_step(
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                    fence,
                    &intent_digest,
                    &payload_digest,
                    &circuit_step_command_id(
                        "effect-claim",
                        &intent.run_id,
                        &intent.step_id,
                        intent.attempt,
                    )?,
                    now_ms,
                )
                .await?;
            }
        } else {
            self.prepare_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                fence,
                &intent_digest,
                &payload_digest,
                &circuit_step_command_id(
                    "effect-prepare",
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                )?,
                now_ms,
            )
            .await?;
            self.claim_taskflow_step(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                fence,
                &intent_digest,
                &payload_digest,
                &circuit_step_command_id(
                    "effect-claim",
                    &intent.run_id,
                    &intent.step_id,
                    intent.attempt,
                )?,
                now_ms,
            )
            .await?;
        }
        Ok(NeuralCircuitEffectHandoffV1 {
            run_id: intent.run_id.clone(),
            step_id: intent.step_id.clone(),
            attempt: intent.attempt,
            capability,
            idempotency_key,
            intent_digest,
            payload_digest,
            authority_granted: false,
        })
    }

    pub async fn neural_circuit_terminal_receipt_v1(
        &self,
        activation: &NeuralCircuitActivationReceiptV1,
    ) -> Result<Option<NeuralCircuitTerminalReceiptV1>, TaskFlowError> {
        let run = required_run(self, &activation.run_id).await?;
        if !matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) {
            return Ok(None);
        }
        Ok(Some(terminal_receipt(run)?))
    }

    pub async fn complete_neural_circuit_terminal_v1(
        &self,
        candidate: &NeuralCircuitCandidateV1,
        activation: &NeuralCircuitActivationReceiptV1,
        output_digest: &Sha256Digest,
        fence: &TaskFlowFence,
        now_ms: u64,
    ) -> Result<NeuralCircuitTerminalReceiptV1, TaskFlowError> {
        validate_digest(output_digest, "terminal output digest")?;
        let run = validate_activation(self, candidate, activation).await?;
        let node = circuit_node(candidate, &run.current_node)?;
        let transition = match node.role {
            CircuitNodeRoleV1::ExitSuccess => TaskFlowTransition::Succeed {
                output_digest: output_digest.clone(),
            },
            CircuitNodeRoleV1::ExitFailure => TaskFlowTransition::Fail {
                reason: format!("circuit_terminal:{}", output_digest.as_str()),
            },
            _ => return Err(invalid("current node is not a circuit terminal")),
        };
        let command = TaskFlowCommand::new(
            &run.run_id,
            circuit_command_id("terminal", &run.run_id, run.revision)?,
            fence.clone(),
            run.revision,
            transition,
            now_ms,
        )?;
        self.apply_taskflow_command(&command).await?;
        terminal_receipt(required_run(self, &run.run_id).await?)
    }

    pub async fn cancel_neural_circuit_activation_v1(
        &self,
        activation: &NeuralCircuitActivationReceiptV1,
        fence: &TaskFlowFence,
        reason: &str,
        now_ms: u64,
    ) -> Result<NeuralCircuitTerminalReceiptV1, TaskFlowError> {
        validate_text(reason, "circuit cancellation reason")?;
        let run = required_run(self, &activation.run_id).await?;
        if matches!(
            run.state,
            TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
        ) {
            return terminal_receipt(run);
        }
        let command = TaskFlowCommand::new(
            &run.run_id,
            circuit_command_id("cancel", &run.run_id, run.revision)?,
            fence.clone(),
            run.revision,
            TaskFlowTransition::Cancel {
                reason: reason.to_string(),
            },
            now_ms,
        )?;
        self.apply_taskflow_command(&command).await?;
        terminal_receipt(required_run(self, &run.run_id).await?)
    }
}

async fn validate_activation(
    store: &AutomationStore,
    candidate: &NeuralCircuitCandidateV1,
    activation: &NeuralCircuitActivationReceiptV1,
) -> Result<TaskFlowRun, TaskFlowError> {
    candidate.validate()?;
    let (definition, compilation) = candidate.compile_taskflow()?;
    if activation.circuit_id != candidate.circuit_id
        || activation.circuit_version != candidate.version
        || activation.circuit_digest != candidate.circuit_digest
        || activation.taskflow_definition_digest != *definition.definition_digest()
        || activation.compilation != compilation
        || activation.binding_digest
            != circuit_binding_digest(candidate, &activation.ingress, activation.budget)?
        || activation.authority_granted
    {
        return Err(TaskFlowError::Conflict(
            "circuit activation receipt does not match the admitted definition/input".to_string(),
        ));
    }
    let run = required_run(store, &activation.run_id).await?;
    let expected_thread = format!("circuit-ingress:{}", activation.binding_digest.as_str());
    if run.workflow_id != definition.workflow_id
        || run.workflow_version != definition.version
        || run.definition_digest != *definition.definition_digest()
        || run.thread_id != expected_thread
    {
        return Err(TaskFlowError::Conflict(
            "durable circuit run binding differs from activation receipt".to_string(),
        ));
    }
    Ok(run)
}

async fn ensure_depth(
    store: &AutomationStore,
    activation: &NeuralCircuitActivationReceiptV1,
) -> Result<(), TaskFlowError> {
    let moves: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ? AND transition = 'resumed'",
    )
    .bind(store.owner_agent_id().as_str())
    .bind(&activation.run_id)
    .fetch_one(store.taskflow_pool())
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let moves = u32::try_from(moves)
        .map_err(|_| TaskFlowError::Corrupt("circuit depth count overflow".to_string()))?;
    if moves >= activation.budget.max_depth {
        return Err(TaskFlowError::Conflict(
            "neural circuit depth budget is exhausted".to_string(),
        ));
    }
    Ok(())
}

async fn record_local_step(
    store: &AutomationStore,
    run_id: &str,
    step_id: &str,
    attempt: u32,
    fence: &TaskFlowFence,
    intent_digest: &Sha256Digest,
    payload_digest: &Sha256Digest,
    receipt_digest: &Sha256Digest,
    now_ms: u64,
) -> Result<TaskFlowStepReceipt, TaskFlowError> {
    let mut current = store
        .read_taskflow_step(run_id, step_id, attempt, fence)
        .await?;
    if current.is_none() {
        current = Some(
            store
                .prepare_taskflow_step(
                    run_id,
                    step_id,
                    attempt,
                    fence,
                    intent_digest,
                    payload_digest,
                    &circuit_step_command_id("prepare", run_id, step_id, attempt)?,
                    now_ms,
                )
                .await?
                .receipt,
        );
    }
    let mut current = current
        .ok_or_else(|| TaskFlowError::Corrupt("prepared circuit step disappeared".to_string()))?;
    if current.intent_digest != *intent_digest || current.payload_digest != *payload_digest {
        return Err(TaskFlowError::Conflict(
            "circuit step is bound to different canonical bytes".to_string(),
        ));
    }
    if current.state == TaskFlowStepState::Prepared {
        current = store
            .claim_taskflow_step(
                run_id,
                step_id,
                attempt,
                fence,
                intent_digest,
                payload_digest,
                &circuit_step_command_id("claim", run_id, step_id, attempt)?,
                now_ms,
            )
            .await?
            .receipt;
    }
    if current.state == TaskFlowStepState::Claimed {
        current = store
            .record_taskflow_step(
                run_id,
                step_id,
                attempt,
                fence,
                intent_digest,
                payload_digest,
                &circuit_step_command_id("record", run_id, step_id, attempt)?,
                receipt_digest,
                TaskFlowStepObservation::Succeeded,
                now_ms,
            )
            .await?
            .receipt;
    }
    if !matches!(
        current.state,
        TaskFlowStepState::Recorded | TaskFlowStepState::Reconciled
    ) || current.receipt_digest.as_ref() != Some(receipt_digest)
    {
        return Err(TaskFlowError::Conflict(
            "circuit step did not reach the bound recorded receipt".to_string(),
        ));
    }
    Ok(current)
}

async fn advance_edge(
    store: &AutomationStore,
    candidate: &NeuralCircuitCandidateV1,
    run: &TaskFlowRun,
    from: &str,
    to: &str,
    fence: &TaskFlowFence,
    now_ms: u64,
) -> Result<TaskFlowRun, TaskFlowError> {
    if run.current_node != from || run.state != TaskFlowRunState::Running {
        return Err(TaskFlowError::Conflict(
            "circuit edge source is not the active frontier".to_string(),
        ));
    }
    if !outgoing(candidate, from)?.iter().any(|target| target == to) {
        return Err(invalid("circuit edge target is not admitted"));
    }
    let token = wait_token_for_edge(&run.run_id, from, to, run.revision)?;
    let wait = TaskFlowCommand::new(
        &run.run_id,
        circuit_command_id("advance-wait", &run.run_id, run.revision)?,
        fence.clone(),
        run.revision,
        TaskFlowTransition::Wait {
            token: token.clone(),
            resume_node: Some(to.to_string()),
        },
        now_ms,
    )?;
    let waited = store.apply_taskflow_command(&wait).await?;
    let resume = TaskFlowCommand::new(
        &run.run_id,
        circuit_command_id("advance-resume", &run.run_id, waited.revision)?,
        fence.clone(),
        waited.revision,
        TaskFlowTransition::Resume { token },
        now_ms,
    )?;
    store.apply_taskflow_command(&resume).await?;
    required_run(store, &run.run_id).await
}

fn reconstruct_decision(
    candidate: &NeuralCircuitCandidateV1,
    activation: &NeuralCircuitActivationReceiptV1,
    node_id: &str,
    round: u32,
    candidates: &[String],
    receipt: &TaskFlowStepReceipt,
) -> Result<NeuralCircuitDecisionV1, TaskFlowError> {
    let digest = required_receipt_digest(receipt)?;
    let feedback = NeuralCircuitDecisionV1::Feedback;
    if digest == decision_choice_digest(candidate, activation, node_id, round, &feedback)? {
        return Ok(feedback);
    }
    for target in candidates {
        let route = NeuralCircuitDecisionV1::Route {
            selected_node: target.clone(),
        };
        if digest == decision_choice_digest(candidate, activation, node_id, round, &route)? {
            return Ok(route);
        }
    }
    Err(TaskFlowError::Corrupt(
        "recorded DecisionCell receipt does not match an admitted route".to_string(),
    ))
}

fn decision_choice_digest(
    candidate: &NeuralCircuitCandidateV1,
    activation: &NeuralCircuitActivationReceiptV1,
    node_id: &str,
    round: u32,
    choice: &NeuralCircuitDecisionV1,
) -> Result<Sha256Digest, TaskFlowError> {
    canonical_digest(
        "hepta.neural-circuit.recorded-choice.v1",
        &(
            candidate.circuit_digest.as_str(),
            activation.binding_digest.as_str(),
            activation.run_id.as_str(),
            node_id,
            round,
            choice,
        ),
    )
}

fn circuit_binding_digest(
    candidate: &NeuralCircuitCandidateV1,
    ingress: &NeuralCircuitIngressV1,
    budget: NeuralCircuitRuntimeBudgetV1,
) -> Result<Sha256Digest, TaskFlowError> {
    canonical_digest(
        "hepta.neural-circuit.activation-binding.v1",
        &(
            candidate.circuit_digest.as_str(),
            ingress,
            budget,
            candidate.route_policy_digest.as_str(),
            candidate.parameter_bundle_digest.as_str(),
            candidate.resource_profile_digest.as_str(),
        ),
    )
}

fn circuit_node<'a>(
    candidate: &'a NeuralCircuitCandidateV1,
    node_id: &str,
) -> Result<&'a CircuitNodeV1, TaskFlowError> {
    candidate
        .nodes
        .iter()
        .find(|node| node.node_id == node_id)
        .ok_or_else(|| TaskFlowError::Corrupt("circuit node is missing".to_string()))
}

fn outgoing(
    candidate: &NeuralCircuitCandidateV1,
    node_id: &str,
) -> Result<Vec<String>, TaskFlowError> {
    circuit_node(candidate, node_id)?;
    let mut targets = candidate
        .edges
        .iter()
        .filter(|edge| edge.from == node_id)
        .map(|edge| edge.to.clone())
        .collect::<Vec<_>>();
    targets.sort();
    targets.dedup();
    Ok(targets)
}

fn single_outgoing(
    candidate: &NeuralCircuitCandidateV1,
    node_id: &str,
) -> Result<String, TaskFlowError> {
    let targets = outgoing(candidate, node_id)?;
    match targets.as_slice() {
        [target] => Ok(target.clone()),
        _ => Err(invalid(
            "runtime node requires exactly one admitted successor",
        )),
    }
}

fn wait_token(
    activation: &NeuralCircuitActivationReceiptV1,
    from: &str,
    to: &str,
) -> Result<String, TaskFlowError> {
    Ok(format!(
        "circuit-join:{}",
        canonical_digest(
            "hepta.neural-circuit.wait-token.v1",
            &(activation.binding_digest.as_str(), from, to),
        )?
        .as_str()
    ))
}

fn wait_token_for_edge(
    run_id: &str,
    from: &str,
    to: &str,
    revision: u64,
) -> Result<String, TaskFlowError> {
    Ok(format!(
        "circuit-edge:{}",
        canonical_digest(
            "hepta.neural-circuit.edge-token.v1",
            &(run_id, from, to, revision),
        )?
        .as_str()
    ))
}

fn circuit_command_id(
    operation: &str,
    run_id: &str,
    revision: u64,
) -> Result<String, TaskFlowError> {
    Ok(format!(
        "circuit:{}:{}",
        operation,
        canonical_digest(
            "hepta.neural-circuit.command-id.v1",
            &(operation, run_id, revision),
        )?
        .as_str()
    ))
}

fn circuit_step_command_id(
    operation: &str,
    run_id: &str,
    step_id: &str,
    attempt: u32,
) -> Result<String, TaskFlowError> {
    Ok(format!(
        "circuit-step:{}:{}",
        operation,
        canonical_digest(
            "hepta.neural-circuit.step-command-id.v1",
            &(operation, run_id, step_id, attempt),
        )?
        .as_str()
    ))
}

fn required_receipt_digest(receipt: &TaskFlowStepReceipt) -> Result<Sha256Digest, TaskFlowError> {
    receipt.receipt_digest.clone().ok_or_else(|| {
        TaskFlowError::Corrupt("recorded circuit step has no receipt digest".to_string())
    })
}

async fn required_run(store: &AutomationStore, run_id: &str) -> Result<TaskFlowRun, TaskFlowError> {
    store
        .taskflow_run(run_id)
        .await?
        .ok_or_else(|| TaskFlowError::Corrupt("durable circuit run disappeared".to_string()))
}

fn terminal_receipt(run: TaskFlowRun) -> Result<NeuralCircuitTerminalReceiptV1, TaskFlowError> {
    if !matches!(
        run.state,
        TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
    ) {
        return Err(TaskFlowError::Conflict(
            "circuit run is not terminal".to_string(),
        ));
    }
    let terminal_receipt_digest = canonical_digest(
        "hepta.neural-circuit.terminal-receipt.v1",
        &(
            run.run_id.as_str(),
            run.state,
            run.current_node.as_str(),
            run.state_digest.as_str(),
            run.revision,
        ),
    )?;
    Ok(NeuralCircuitTerminalReceiptV1 {
        run_id: run.run_id,
        state: run.state,
        current_node: run.current_node,
        state_digest: run.state_digest,
        revision: run.revision,
        terminal_receipt_digest,
        authority_granted: false,
    })
}

fn canonical_digest<T: Serialize>(domain: &str, value: &T) -> Result<Sha256Digest, TaskFlowError> {
    let mut bytes = domain.as_bytes().to_vec();
    bytes.push(0);
    bytes.extend_from_slice(
        &serde_json::to_vec(value)
            .map_err(|error| TaskFlowError::Corrupt(format!("circuit digest: {error}")))?,
    );
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn validate_text(value: &str, label: &str) -> Result<(), TaskFlowError> {
    if value.is_empty() || value.len() > MAX_RUNTIME_TEXT_BYTES || value.contains('\0') {
        return Err(invalid(format!("{label} is invalid")));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), TaskFlowError> {
    let value = digest.as_str();
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid(format!("{label} must be lowercase sha256")));
    }
    Ok(())
}

fn invalid(message: impl Into<String>) -> TaskFlowError {
    TaskFlowError::Invalid(message.into())
}
