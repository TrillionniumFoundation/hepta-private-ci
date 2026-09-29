//! Canonical intelligence execution through the long-lived durable Neuron owner.
//!
//! This module is a child of `intelligence_product::runner`, so it can wrap the
//! existing six non-Neuron owner ports without widening their public surface.
//! The compatibility runner remains available for qualification fixtures; named
//! product composition uses the methods defined here.

use super::*;

use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronTickInputV1;
use tokio_util::sync::CancellationToken;

struct NeuronStageAdmission {
    snapshot: CanonicalIntelligenceSnapshotV1,
    authority_file: PathBuf,
    authority_verifier: IntelligenceAuthorityVerifierV1,
    deadline: Instant,
    cancellation: CancellationToken,
}

impl NeuronStageAdmission {
    fn begin_stage(&mut self, budget_micros: u64) -> Result<(), NeuronAdmissionError> {
        let stage_deadline = Instant::now()
            .checked_add(Duration::from_micros(budget_micros))
            .ok_or(NeuronAdmissionError::DeadlineExceeded)?;
        self.deadline = self.deadline.min(stage_deadline);
        Ok(())
    }
}

impl NeuronAdmissionGuard for NeuronStageAdmission {
    fn check(
        &mut self,
        _config: &NeuronRuntimeConfigV1,
        input: &NeuronTickInputV1,
    ) -> Result<(), NeuronAdmissionError> {
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        if input.body_generation != Some(self.snapshot.body_generation().get())
            || input.objective_digest != self.snapshot.objective_digest()
        {
            return Err(NeuronAdmissionError::BindingMismatch);
        }
        // Selection, artifact, calibration and OOD admission is independently
        // enforced by the guard installed on AgentdNeuronOwner. This stage guard
        // supplies current owner, deadline and cancellation fencing.
        let mut oracle = FileBackedFreshnessOracleV1::new(
            self.authority_file.clone(),
            self.authority_verifier.clone(),
        );
        validate_current_snapshot(&self.snapshot, &mut oracle)
            .map_err(|_| NeuronAdmissionError::Revoked)?;
        if self.cancellation.is_cancelled() {
            return Err(NeuronAdmissionError::Cancelled);
        }
        if Instant::now() >= self.deadline {
            return Err(NeuronAdmissionError::DeadlineExceeded);
        }
        Ok(())
    }
}

struct DurableNeuronOwnerPortsV1 {
    inner: AgentdOwnerPortsV1,
    neuron: Option<crate::AgentdNeuronInvocationV1>,
    neuron_admission: NeuronStageAdmission,
}

impl DurableNeuronOwnerPortsV1 {
    fn new(
        inputs: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        neuron: crate::AgentdNeuronInvocationV1,
        neuron_admission: NeuronStageAdmission,
    ) -> Self {
        Self {
            inner: AgentdOwnerPortsV1::new(inputs, evaluation_session),
            neuron: Some(neuron),
            neuron_admission,
        }
    }
}

impl CanonicalOwnerPortsV1 for DurableNeuronOwnerPortsV1 {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.validate_objective(input)
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.evaluate_utility(input)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let invocation = self
            .neuron
            .take()
            .ok_or_else(|| AgentdOwnerPortsV1::reject(input.stage, "neuron invocation reused"))?;
        self.neuron_admission
            .begin_stage(input.budget_micros)
            .map_err(|error| neuron_failure(input.stage, &NeuronRuntimeError::Admission(error)))?;
        let started = Instant::now();
        let result = invocation
            .execute(input, &mut self.neuron_admission)
            .map_err(|error| neuron_failure(input.stage, &error))?;
        AgentdOwnerPortsV1::within_budget(input, started)?;
        if result.signal.authority.grants_any() {
            return Err(AgentdOwnerPortsV1::reject(
                input.stage,
                "neuron authority widening",
            ));
        }
        if result.signal.abstain || result.tick.abstain {
            // The checkpoint/full result is already durable. Quarantine product
            // use without reclassifying it as an unexecuted tick or retrying the
            // model under the same operation identity.
            return Err(CanonicalPortFailureV1 {
                class: CanonicalPortFailureClassV1::Quarantined,
                evidence_digest: Digest32::of_bytes(
                    format!(
                        "hepta.agentd.neuron-committed-not-ready.v1:{:?}:{}",
                        input.stage, result.tick.checkpoint_after
                    )
                    .as_bytes(),
                ),
            });
        }
        let intuition =
            self.inner.intuition_request.as_mut().ok_or_else(|| {
                AgentdOwnerPortsV1::reject(input.stage, "intuition consumer missing")
            })?;
        intuition.state_digest = result.tick.checkpoint_after;
        AgentdOwnerPortsV1::receipt(
            input,
            "neuron.runtime",
            result.tick.checkpoint_after,
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.build_prompt_portfolio(input)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.decide_intuition(input)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.compile_context(input)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.inner.evaluate_candidate(input)
    }
}

fn neuron_failure(stage: CanonicalStageV1, error: &NeuronRuntimeError) -> CanonicalPortFailureV1 {
    let class = match error {
        NeuronRuntimeError::Admission(NeuronAdmissionError::DeadlineExceeded) => {
            CanonicalPortFailureClassV1::TimedOut
        }
        NeuronRuntimeError::Admission(NeuronAdmissionError::Unavailable)
        | NeuronRuntimeError::InvalidCalibration => CanonicalPortFailureClassV1::Unavailable,
        NeuronRuntimeError::WitnessAfterCommit { .. }
        | NeuronRuntimeError::PendingReconciliation
        | NeuronRuntimeError::Operation(codex_hepta_neuron::OperationStoreError::Indeterminate)
        | NeuronRuntimeError::Operation(codex_hepta_neuron::OperationStoreError::Poisoned)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Indeterminate)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Poisoned)
        | NeuronRuntimeError::Model(codex_hepta_neuron::NeuronModelError::Indeterminate) => {
            CanonicalPortFailureClassV1::Indeterminate
        }
        NeuronRuntimeError::CalibrationExpired => CanonicalPortFailureClassV1::Quarantined,
        _ => CanonicalPortFailureClassV1::Rejected,
    };
    CanonicalPortFailureV1 {
        class,
        evidence_digest: Digest32::of_bytes(
            format!("hepta.agentd.neuron-stage.v2:{stage:?}:{error:?}").as_bytes(),
        ),
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    /// Named product entry: all seven canonical owners run against one frozen
    /// snapshot, and the Neuron stage is executed only through the durable
    /// Agentd owner invocation.
    pub async fn prepare_with_durable_neuron(
        &self,
        coordinator: &crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let composition = coordinator.composition().clone();
        self.prepare_for_composition_with_durable_neuron(&composition, request, inputs, neuron)
            .await
    }

    /// Same product entry with an already frozen Agentd composition, avoiding a
    /// run-coordinator lock across model execution.
    pub async fn prepare_for_composition_with_durable_neuron(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let candidate_ids = request
            .legal_candidates
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        let intuition_ids = inputs
            .intuition_request
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>();
        if candidate_ids != intuition_ids {
            return Err(AgentdIntelligenceProductError::CandidateSetMismatch);
        }

        let generation = composition.agentd_generation;
        let mut fence_bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
        fence_bytes.extend_from_slice(composition.agent_id.as_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        fence_bytes.extend_from_slice(&generation.to_be_bytes());
        let fence_digest = Digest32::of_bytes(&fence_bytes).to_string();
        let snapshot = request.snapshot.clone();
        let mut body = b"hepta.agentd.intelligence-body.v1\0".to_vec();
        body.extend_from_slice(snapshot.digest().as_array());
        body.extend_from_slice(&snapshot.body_generation().get().to_be_bytes());
        let body_digest = Digest32::of_bytes(&body);
        if neuron.runtime_body_digest() != body_digest
            || !neuron.matches_run(&request.run_id, snapshot.body_generation().get())
        {
            return Err(AgentdIntelligenceProductError::Canonical(
                CanonicalIntelligenceError::SnapshotMismatch,
            ));
        }

        let timeout_micros = request.budget.total_micros;
        let started_ms = wall_clock_ms()?;
        let timeout_ms = timeout_micros.saturating_add(999) / 1_000;
        let deadline_ms = started_ms
            .checked_add(timeout_ms.max(1))
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let stage_deadline = Instant::now()
            .checked_add(Duration::from_micros(timeout_micros))
            .ok_or(AgentdIntelligenceProductError::Clock)?;
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        let evaluation_session = match inputs.signed_evaluation.take() {
            None => None,
            Some(signed) => {
                let trust = self
                    .evaluation_trust
                    .as_ref()
                    .ok_or(AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let mut oracle = FileBackedFreshnessOracleV1::new(
                    authority_file.clone(),
                    authority_verifier.clone(),
                );
                let owner_id = StableId::new("learning.eval")
                    .map_err(|_| AgentdIntelligenceProductError::InvalidAuthorityVerifier)?;
                let current_owner = oracle
                    .current(&owner_id)
                    .map_err(AgentdIntelligenceProductError::Canonical)?;
                Some(AgentdEvaluationSessionV1 {
                    run_id: request.run_id.clone(),
                    current_owner,
                    trust: std::sync::Arc::clone(trust),
                    signed,
                })
            }
        };
        let cancellation = CancellationToken::new();
        let worker_cancellation = cancellation.clone();
        let worker_snapshot = snapshot.clone();
        let worker_authority_file = authority_file.clone();
        let worker_authority_verifier = authority_verifier.clone();
        let mut worker = self.spawn_owner_work(move || {
            let admission = NeuronStageAdmission {
                snapshot: worker_snapshot,
                authority_file: worker_authority_file,
                authority_verifier: worker_authority_verifier,
                deadline: stage_deadline,
                cancellation: worker_cancellation,
            };
            let mut ports =
                DurableNeuronOwnerPortsV1::new(inputs, evaluation_session, neuron, admission);
            let mut oracle = FileBackedFreshnessOracleV1::new(authority_file, authority_verifier);
            prepare_intelligence_run(request, &mut ports, &mut oracle)
        })?;
        let outcome = timeout(Duration::from_micros(timeout_micros), &mut worker)
            .await
            .map_err(|_| {
                cancellation.cancel();
                worker.abort();
                AgentdIntelligenceProductError::TimedOut
            })?
            .map_err(|_| AgentdIntelligenceProductError::WorkerCrashed)?
            .map_err(AgentdIntelligenceProductError::Canonical)?;

        finish_prepared_outcome(
            self,
            outcome,
            snapshot,
            candidate_ids,
            generation,
            fence_digest,
            deadline_ms,
            body_digest,
        )
    }

    /// Execute the durable product path and immediately admit its exact envelope
    /// into the Agentd run lifecycle.
    pub async fn prepare_and_admit_with_durable_neuron(
        &self,
        coordinator: &mut crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdIntelligenceProductError> {
        match self
            .prepare_with_durable_neuron(coordinator, request, inputs, neuron)
            .await?
        {
            AgentdIntelligenceProductOutcomeV1::Ready(prepared) => {
                let snapshot = prepared.run_snapshot();
                let admitted = coordinator
                    .start_run(
                        wall_clock_ms()?,
                        crate::RunSnapshot {
                            run_id: snapshot.run_id,
                            request_digest: snapshot.request_digest,
                            objective_digest: snapshot.objective_digest,
                            body_digest: snapshot.body_digest,
                            artifact_set_digest: snapshot.artifact_set_digest,
                            authority_epoch: snapshot.authority_epoch,
                            generation: snapshot.generation,
                            fence_digest: snapshot.fence_digest,
                            deadline_ms: snapshot.deadline_ms,
                        },
                    )
                    .map_err(AgentdIntelligenceProductError::Run)?;
                let attachment = prepared.context_attachment();
                let run_receipt = coordinator
                    .attach_context(
                        wall_clock_ms()?,
                        admitted.revision,
                        crate::ContextAttachment {
                            run_id: attachment.run_id,
                            request_digest: attachment.request_digest,
                            objective_digest: attachment.objective_digest,
                            body_digest: attachment.body_digest,
                            artifact_set_digest: attachment.artifact_set_digest,
                            authority_epoch: attachment.authority_epoch,
                            generation: attachment.generation,
                            fence_digest: attachment.fence_digest,
                            deadline_ms: attachment.deadline_ms,
                            context_digest: attachment.context_digest,
                            compilation_receipt_digest: attachment.compilation_receipt_digest,
                        },
                    )
                    .map_err(AgentdIntelligenceProductError::Run)?;
                Ok(AgentdIntelligenceAdmittedOutcomeV1::Ready {
                    prepared,
                    run_receipt,
                })
            }
            AgentdIntelligenceProductOutcomeV1::Abstained => {
                Ok(AgentdIntelligenceAdmittedOutcomeV1::Abstained)
            }
            AgentdIntelligenceProductOutcomeV1::SlowPath => {
                Ok(AgentdIntelligenceAdmittedOutcomeV1::SlowPath)
            }
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn finish_prepared_outcome(
    runner: &AgentdIntelligenceProductRunnerV1,
    outcome: CanonicalRunOutcomeV1,
    snapshot: CanonicalIntelligenceSnapshotV1,
    candidate_ids: Vec<StableId>,
    generation: u64,
    fence_digest: String,
    deadline_ms: u64,
    body_digest: Digest32,
) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
    match outcome {
        CanonicalRunOutcomeV1::Ready(envelope) => {
            let mut oracle = FileBackedFreshnessOracleV1::new(
                runner.authority_file.clone(),
                runner.authority_verifier.clone(),
            );
            validate_current_snapshot(&snapshot, &mut oracle)
                .map_err(AgentdIntelligenceProductError::Canonical)?;
            let mut bytes = b"hepta.agentd.intelligence-dispatch-proposal.v1\0".to_vec();
            bytes.extend_from_slice(envelope.envelope_digest.as_array());
            bytes.extend_from_slice(snapshot.revocation_frontier_digest().as_array());
            let dispatch_proposal_digest = Digest32::of_bytes(&bytes);
            let run_snapshot = crate::AgentRunSnapshot {
                run_id: envelope.run_id.to_string(),
                request_digest: envelope.trace_digest.to_string(),
                objective_digest: envelope.objective_digest.to_string(),
                body_digest: body_digest.to_string(),
                artifact_set_digest: snapshot.digest().to_string(),
                authority_epoch: snapshot.authority_epoch(),
                generation,
                fence_digest,
                deadline_ms,
            };
            let context_attachment = crate::AgentContextAttachment {
                run_id: run_snapshot.run_id.clone(),
                request_digest: run_snapshot.request_digest.clone(),
                objective_digest: run_snapshot.objective_digest.clone(),
                body_digest: run_snapshot.body_digest.clone(),
                artifact_set_digest: run_snapshot.artifact_set_digest.clone(),
                authority_epoch: run_snapshot.authority_epoch,
                generation: run_snapshot.generation,
                fence_digest: run_snapshot.fence_digest.clone(),
                deadline_ms: run_snapshot.deadline_ms,
                context_digest: envelope.context_receipt_digest.to_string(),
                compilation_receipt_digest: envelope.envelope_digest.to_string(),
            };
            Ok(AgentdIntelligenceProductOutcomeV1::Ready(
                PreparedAgentdIntelligenceRunV1 {
                    envelope,
                    dispatch_proposal_digest,
                    snapshot,
                    candidate_ids,
                    run_snapshot,
                    context_attachment,
                },
            ))
        }
        CanonicalRunOutcomeV1::Abstained(_) => Ok(AgentdIntelligenceProductOutcomeV1::Abstained),
        CanonicalRunOutcomeV1::SlowPath(_) => Ok(AgentdIntelligenceProductOutcomeV1::SlowPath),
    }
}
