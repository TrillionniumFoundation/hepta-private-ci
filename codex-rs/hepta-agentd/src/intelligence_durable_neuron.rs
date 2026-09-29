//! Canonical intelligence execution through a long-lived durable Neuron owner.
//!
//! The compatibility V1 invocation and the unified V2 invocation share one
//! transport path. V2 carries the durable terminal disposition explicitly;
//! committed abstention or degradation is quarantined and is never retried as
//! an unexecuted tick.

use super::*;

use codex_hepta_neuron::AbstainReasonV1;
use codex_hepta_neuron::GenerationStoreError;
use codex_hepta_neuron::NeuronAdmissionError;
use codex_hepta_neuron::NeuronAdmissionGuard;
use codex_hepta_neuron::NeuronCommitDispositionV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeIndexError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronRuntimeV2Error;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::OperationStoreError;
use codex_hepta_neuron::WitnessStoreError;
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

#[derive(Debug)]
enum AgentdNeuronStageError {
    Legacy(NeuronRuntimeError),
    Unified(NeuronRuntimeV2Error),
}

struct AgentdNeuronStageResult {
    output: NeuronRuntimeOutputV1,
    disposition: NeuronCommitDispositionV1,
    operation_digest: Option<Digest32>,
}

trait DurableNeuronInvocation: Send + 'static {
    fn runtime_body_digest(&self) -> Digest32;
    fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool;
    fn execute_stage(
        &self,
        input: &CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<AgentdNeuronStageResult, AgentdNeuronStageError>;
}

impl DurableNeuronInvocation for crate::AgentdNeuronInvocationV1 {
    fn runtime_body_digest(&self) -> Digest32 {
        crate::AgentdNeuronInvocationV1::runtime_body_digest(self)
    }

    fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        crate::AgentdNeuronInvocationV1::matches_run(self, run_id, body_generation)
    }

    fn execute_stage(
        &self,
        input: &CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<AgentdNeuronStageResult, AgentdNeuronStageError> {
        let output = self
            .execute(input, guard)
            .map_err(AgentdNeuronStageError::Legacy)?;
        let disposition = if output.tick.abstain || output.signal.abstain {
            NeuronCommitDispositionV1::abstained(vec![AbstainReasonV1::HostPolicy])
                .map_err(|_| AgentdNeuronStageError::Legacy(NeuronRuntimeError::InvalidInput))?
        } else {
            NeuronCommitDispositionV1::CommittedReady
        };
        Ok(AgentdNeuronStageResult {
            output,
            disposition,
            operation_digest: None,
        })
    }
}

impl DurableNeuronInvocation for crate::AgentdNeuronInvocationV2 {
    fn runtime_body_digest(&self) -> Digest32 {
        crate::AgentdNeuronInvocationV2::runtime_body_digest(self)
    }

    fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        crate::AgentdNeuronInvocationV2::matches_run(self, run_id, body_generation)
    }

    fn execute_stage(
        &self,
        input: &CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<AgentdNeuronStageResult, AgentdNeuronStageError> {
        let commit = self
            .execute(input, guard)
            .map_err(AgentdNeuronStageError::Unified)?;
        Ok(AgentdNeuronStageResult {
            output: commit.output,
            disposition: commit.disposition,
            operation_digest: Some(commit.operation_digest),
        })
    }
}

struct DurableNeuronOwnerPorts<I: DurableNeuronInvocation> {
    inner: AgentdOwnerPortsV1,
    neuron: Option<I>,
    neuron_admission: NeuronStageAdmission,
}

impl<I: DurableNeuronInvocation> DurableNeuronOwnerPorts<I> {
    fn new(
        inputs: AgentdIntelligenceOwnerInputsV1,
        evaluation_session: Option<AgentdEvaluationSessionV1>,
        neuron: I,
        neuron_admission: NeuronStageAdmission,
    ) -> Self {
        Self {
            inner: AgentdOwnerPortsV1::new(inputs, evaluation_session),
            neuron: Some(neuron),
            neuron_admission,
        }
    }
}

impl<I: DurableNeuronInvocation> CanonicalOwnerPortsV1 for DurableNeuronOwnerPorts<I> {
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
            .map_err(|error| {
                neuron_failure(
                    input.stage,
                    &AgentdNeuronStageError::Legacy(NeuronRuntimeError::Admission(error)),
                )
            })?;
        let started = Instant::now();
        let result = invocation
            .execute_stage(input, &mut self.neuron_admission)
            .map_err(|error| neuron_failure(input.stage, &error))?;
        AgentdOwnerPortsV1::within_budget(input, started)?;
        if result.output.signal.authority.grants_any() {
            return Err(AgentdOwnerPortsV1::reject(
                input.stage,
                "neuron authority widening",
            ));
        }

        match &result.disposition {
            NeuronCommitDispositionV1::CommittedReady => {
                if result.output.signal.abstain || result.output.tick.abstain {
                    return Err(AgentdOwnerPortsV1::reject(
                        input.stage,
                        "ready disposition carried abstention",
                    ));
                }
            }
            NeuronCommitDispositionV1::CommittedAbstained { .. }
            | NeuronCommitDispositionV1::CommittedDegraded { .. } => {
                if !result.output.signal.abstain || !result.output.tick.abstain {
                    return Err(AgentdOwnerPortsV1::reject(
                        input.stage,
                        "non-ready disposition omitted abstention",
                    ));
                }
                let disposition = result
                    .disposition
                    .semantic_digest()
                    .map_err(|_| AgentdOwnerPortsV1::reject(input.stage, "invalid disposition"))?;
                let operation = result.operation_digest.unwrap_or(Digest32::ZERO);
                return Err(CanonicalPortFailureV1 {
                    class: CanonicalPortFailureClassV1::Quarantined,
                    evidence_digest: Digest32::of_parts(&[
                        b"hepta.agentd.neuron-committed-not-ready.v2",
                        disposition.as_array(),
                        operation.as_array(),
                        result.output.tick.checkpoint_after.as_array(),
                    ]),
                });
            }
        }

        let intuition =
            self.inner.intuition_request.as_mut().ok_or_else(|| {
                AgentdOwnerPortsV1::reject(input.stage, "intuition consumer missing")
            })?;
        intuition.state_digest = result.output.tick.checkpoint_after;
        AgentdOwnerPortsV1::receipt(
            input,
            "neuron.runtime",
            result.output.tick.checkpoint_after,
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

fn neuron_failure(
    stage: CanonicalStageV1,
    error: &AgentdNeuronStageError,
) -> CanonicalPortFailureV1 {
    let class = match error {
        AgentdNeuronStageError::Legacy(error) => legacy_failure_class(error),
        AgentdNeuronStageError::Unified(error) => unified_failure_class(error),
    };
    CanonicalPortFailureV1 {
        class,
        evidence_digest: Digest32::of_bytes(
            format!("hepta.agentd.neuron-stage.v3:{stage:?}:{error:?}").as_bytes(),
        ),
    }
}

fn legacy_failure_class(error: &NeuronRuntimeError) -> CanonicalPortFailureClassV1 {
    match error {
        NeuronRuntimeError::Admission(
            NeuronAdmissionError::DeadlineExceeded | NeuronAdmissionError::Cancelled,
        ) => CanonicalPortFailureClassV1::TimedOut,
        NeuronRuntimeError::Admission(NeuronAdmissionError::Unavailable)
        | NeuronRuntimeError::InvalidCalibration => CanonicalPortFailureClassV1::Unavailable,
        NeuronRuntimeError::WitnessAfterCommit { .. }
        | NeuronRuntimeError::PendingReconciliation
        | NeuronRuntimeError::Operation(OperationStoreError::Indeterminate)
        | NeuronRuntimeError::Operation(OperationStoreError::Poisoned)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Indeterminate)
        | NeuronRuntimeError::Journal(codex_hepta_neuron::JournalError::Poisoned)
        | NeuronRuntimeError::Model(codex_hepta_neuron::NeuronModelError::Indeterminate) => {
            CanonicalPortFailureClassV1::Indeterminate
        }
        NeuronRuntimeError::CalibrationExpired => CanonicalPortFailureClassV1::Quarantined,
        _ => CanonicalPortFailureClassV1::Rejected,
    }
}

fn unified_failure_class(error: &NeuronRuntimeV2Error) -> CanonicalPortFailureClassV1 {
    match error {
        NeuronRuntimeV2Error::Admission(
            NeuronAdmissionError::DeadlineExceeded | NeuronAdmissionError::Cancelled,
        ) => CanonicalPortFailureClassV1::TimedOut,
        NeuronRuntimeV2Error::Admission(NeuronAdmissionError::Unavailable)
        | NeuronRuntimeV2Error::Configuration(NeuronRuntimeError::InvalidCalibration) => {
            CanonicalPortFailureClassV1::Unavailable
        }
        NeuronRuntimeV2Error::Store(
            GenerationStoreError::Indeterminate | GenerationStoreError::Poisoned,
        )
        | NeuronRuntimeV2Error::Index(
            NeuronRuntimeIndexError::Indeterminate | NeuronRuntimeIndexError::Poisoned,
        )
        | NeuronRuntimeV2Error::Witness(
            WitnessStoreError::Indeterminate | WitnessStoreError::Poisoned,
        )
        | NeuronRuntimeV2Error::Codec(
            OperationStoreError::Indeterminate | OperationStoreError::Poisoned,
        )
        | NeuronRuntimeV2Error::Model(codex_hepta_neuron::NeuronModelError::Indeterminate)
        | NeuronRuntimeV2Error::PendingOperation => CanonicalPortFailureClassV1::Indeterminate,
        NeuronRuntimeV2Error::Configuration(NeuronRuntimeError::CalibrationExpired) => {
            CanonicalPortFailureClassV1::Quarantined
        }
        _ => CanonicalPortFailureClassV1::Rejected,
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    pub async fn prepare_with_durable_neuron(
        &self,
        coordinator: &crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_with_neuron_invocation(coordinator, request, inputs, neuron)
            .await
    }

    pub async fn prepare_with_durable_neuron_v2(
        &self,
        coordinator: &crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV2,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_with_neuron_invocation(coordinator, request, inputs, neuron)
            .await
    }

    async fn prepare_with_neuron_invocation<I: DurableNeuronInvocation>(
        &self,
        coordinator: &crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: I,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let composition = coordinator.composition().clone();
        self.prepare_for_composition_with_neuron_invocation(&composition, request, inputs, neuron)
            .await
    }

    pub async fn prepare_for_composition_with_durable_neuron(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_for_composition_with_neuron_invocation(composition, request, inputs, neuron)
            .await
    }

    pub async fn prepare_for_composition_with_durable_neuron_v2(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV2,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_for_composition_with_neuron_invocation(composition, request, inputs, neuron)
            .await
    }

    async fn prepare_for_composition_with_neuron_invocation<I: DurableNeuronInvocation>(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        mut inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: I,
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
                DurableNeuronOwnerPorts::new(inputs, evaluation_session, neuron, admission);
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

    pub async fn prepare_and_admit_with_durable_neuron(
        &self,
        coordinator: &mut crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV1,
    ) -> Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_and_admit_with_neuron_invocation(coordinator, request, inputs, neuron)
            .await
    }

    pub async fn prepare_and_admit_with_durable_neuron_v2(
        &self,
        coordinator: &mut crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV2,
    ) -> Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_and_admit_with_neuron_invocation(coordinator, request, inputs, neuron)
            .await
    }

    async fn prepare_and_admit_with_neuron_invocation<I: DurableNeuronInvocation>(
        &self,
        coordinator: &mut crate::AgentRunCoordinator,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: I,
    ) -> Result<AgentdIntelligenceAdmittedOutcomeV1, AgentdIntelligenceProductError> {
        match self
            .prepare_with_neuron_invocation(coordinator, request, inputs, neuron)
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
