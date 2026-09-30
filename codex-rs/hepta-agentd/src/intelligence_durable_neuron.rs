//! Canonical intelligence execution through a long-lived durable Neuron owner.
//!
//! The compatibility V1 invocation and the unified V2 invocation share one
//! transport path. V2 carries the durable terminal disposition explicitly;
//! committed abstention or degradation is quarantined and is never retried as
//! an unexecuted tick.

use super::*;

use codex_hepta_agent_components::neuron::AbstainReasonV1;
use codex_hepta_agent_components::neuron::GenerationStoreError;
use codex_hepta_agent_components::neuron::NeuronAdmissionError;
use codex_hepta_agent_components::neuron::NeuronAdmissionGuard;
use codex_hepta_agent_components::neuron::NeuronCommitDispositionV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeConfigV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeError;
use codex_hepta_agent_components::neuron::NeuronRuntimeIndexError;
use codex_hepta_agent_components::neuron::NeuronRuntimeOutputV1;
use codex_hepta_agent_components::neuron::NeuronRuntimeV2Error;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::neuron::OperationStoreError;
use codex_hepta_agent_components::neuron::WitnessStoreError;
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
        | NeuronRuntimeError::Journal(
            codex_hepta_agent_components::neuron::JournalError::Indeterminate,
        )
        | NeuronRuntimeError::Journal(
            codex_hepta_agent_components::neuron::JournalError::Poisoned,
        )
        | NeuronRuntimeError::Model(
            codex_hepta_agent_components::neuron::NeuronModelError::Indeterminate,
        ) => CanonicalPortFailureClassV1::Indeterminate,
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
        | NeuronRuntimeV2Error::Model(
            codex_hepta_agent_components::neuron::NeuronModelError::Indeterminate,
        )
        | NeuronRuntimeV2Error::PendingOperation => CanonicalPortFailureClassV1::Indeterminate,
        NeuronRuntimeV2Error::Configuration(NeuronRuntimeError::CalibrationExpired) => {
            CanonicalPortFailureClassV1::Quarantined
        }
        _ => CanonicalPortFailureClassV1::Rejected,
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    pub async fn prepare_for_composition_with_durable_neuron_v2(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: crate::AgentdNeuronInvocationV2,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        let identity = inputs
            .run_identity
            .as_ref()
            .ok_or(AgentdIntelligenceProductError::MissingRunIdentity)?;
        if !neuron.matches_run(&request.run_id, request.snapshot.body_generation().get())
            || neuron.runtime_body_digest() != identity.body_digest
        {
            return Err(AgentdIntelligenceProductError::RunIdentityMismatch);
        }
        let authority_file = self.authority_file.clone();
        let authority_verifier = self.authority_verifier.clone();
        self.prepare_for_composition_with_ports(
            composition,
            request,
            inputs,
            move |inner, snapshot, deadline, cancellation| DurableNeuronOwnerPorts {
                inner,
                neuron: Some(neuron),
                neuron_admission: NeuronStageAdmission {
                    snapshot,
                    authority_file,
                    authority_verifier,
                    deadline,
                    cancellation,
                },
            },
        )
        .await
    }
}
