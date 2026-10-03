use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::*;
use std::path::PathBuf;

use codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelFailureV1;
use codex_hepta_agent_components::infer_core::SelfIterationModelRequestV1;
use codex_hepta_agent_components::types::StableId;

type Response = oneshot::Sender<Result<AgentdSelfIterationRecordV1, AgentdError>>;
#[path = "self_iteration_runtime_command.rs"]
mod command;
use command::Command;

/// Bounded product handle. The caller receives neither signing material nor
/// mutable journal/controller access. Model assessments alone cannot select.
#[derive(Clone)]
pub struct AgentdSelfIterationHandleV1 {
    sender: mpsc::Sender<Command>,
}

impl AgentdSelfIterationHandleV1 {
    #[cfg(test)]
    pub(in crate::self_iteration) fn closed_test_handle() -> Self {
        let (sender, _receiver) = mpsc::channel(8);
        Self { sender }
    }
    pub async fn begin_candidate_effects(
        &self,
        round: AgentdSelfIterationRoundV1,
        assessment: SelfIterationModelAssessmentV1,
    ) -> Result<AgentdSelfIterationCandidateConstructionAdmissionV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::BeginCandidateEffects(round, assessment, response),
            receive,
        )
        .await
    }
    pub async fn inspect_round(
        &self,
        goal: StableId,
        canonical_policy: Digest32,
    ) -> Result<AgentdSelfIterationRoundStatusV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::InspectRound(goal, canonical_policy, response),
            receive,
        )
        .await
    }
    /// Debit the original policy window before any model or generation effect.
    pub async fn reserve_round(
        &self,
        goal: StableId,
        canonical: crate::CanonicalIterationEnvelopeV1,
        envelope: IterationEnvelopeV1,
    ) -> Result<AgentdSelfIterationRoundV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Reserve(goal, canonical, envelope, response),
            receive,
        )
        .await
    }
    pub async fn complete_model(
        &self,
        round: AgentdSelfIterationRoundV1,
        request: SelfIterationModelRequestV1,
        assessment: SelfIterationModelAssessmentV1,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Complete(round, request, assessment, response),
            receive,
        )
        .await
    }

    pub async fn reject_proposal_before_candidate_effects(
        &self,
        round: AgentdSelfIterationRoundV1,
        assessment: SelfIterationModelAssessmentV1,
        reason: AgentdSelfIterationProposalRejectionV1,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::RejectProposal(round, assessment, reason, response),
            receive,
        )
        .await
    }

    pub async fn freeze(
        &self,
        candidate: AgentdSelfIterationCandidateV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::Freeze(Box::new(candidate), response), receive)
            .await
    }
    pub async fn evaluate(
        &self,
        frozen: Digest32,
        evaluation: AgentdSignedEvaluationV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Evaluate(frozen, Box::new(evaluation), response),
            receive,
        )
        .await
    }
    pub async fn select(
        &self,
        frozen: Digest32,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(Command::Select(frozen, attestation, response), receive)
            .await
    }
    pub async fn observe(
        &self,
        frozen: Digest32,
        verdict: AgentdSelfIterationCanaryVerdictV1,
        attestation: SignedLearningEvidenceV1,
    ) -> Result<AgentdSelfIterationRecordV1, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::Observe(frozen, verdict, attestation, response),
            receive,
        )
        .await
    }
    async fn send<T>(
        &self,
        command: Command,
        receive: oneshot::Receiver<Result<T, AgentdError>>,
    ) -> Result<T, AgentdError> {
        self.sender
            .try_send(command)
            .map_err(|error| invalid(format!("self-iteration admission: {error}")))?;
        // Cancellation or timeout drops only the reply. The sole runtime owner
        // retains work and capacity until the actual operation has retired.
        tokio::time::timeout(std::time::Duration::from_secs(15), receive)
            .await
            .map_err(|_| invalid("self-iteration reply timed out; recover exact candidate"))?
            .map_err(|_| invalid("self-iteration owner closed"))?
    }
}

pub struct AgentdSelfIterationRuntimeConfigV1 {
    journal: IterationJournal,
    handle: AgentdSelfIterationHandleV1,
    trust: Arc<ActivatedLearningTrustV1>,
    receiver: mpsc::Receiver<Command>,
}
impl AgentdSelfIterationRuntimeConfigV1 {
    pub fn new(
        journal_path: PathBuf,
        trust: Arc<ActivatedLearningTrustV1>,
    ) -> Result<(Self, AgentdSelfIterationHandleV1), AgentdError> {
        if !journal_path.is_absolute() || journal_path.file_name().is_none() {
            return Err(invalid("iteration journal path must be absolute"));
        }
        let journal = IterationJournal::open(journal_path)?;
        let (sender, receiver) = mpsc::channel(8);
        let handle = AgentdSelfIterationHandleV1 { sender };
        Ok((
            Self {
                journal,
                handle: handle.clone(),
                trust,
                receiver,
            },
            handle,
        ))
    }
    pub(crate) fn handle(&self) -> AgentdSelfIterationHandleV1 {
        self.handle.clone()
    }
    pub(crate) fn unresolved_apply(&self) -> bool {
        self.journal.unresolved_apply()
    }

    pub(crate) fn start(
        self,
        host: Arc<AgentdNeuronRuntimeV2Host>,
    ) -> Result<SelfIterationRuntime, AgentdError> {
        let owner = SelfIterationOwner::open(self.journal, self.trust, host)?;
        Ok(SelfIterationRuntime {
            owner: Arc::new(std::sync::Mutex::new(owner)),
            receiver: self.receiver,
        })
    }
}

pub(crate) struct SelfIterationRuntime {
    owner: Arc<std::sync::Mutex<SelfIterationOwner>>,
    receiver: mpsc::Receiver<Command>,
}
impl SelfIterationRuntime {
    pub(crate) async fn run(mut self, cancellation: CancellationToken) -> Result<(), AgentdError> {
        self.owner
            .lock()
            .map_err(|_| invalid("self-iteration owner poisoned"))?
            .cancellation = cancellation.clone();
        let mut receiver_closed = false;
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(1));
        interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = interval.tick() => None,
                command = self.receiver.recv(), if !receiver_closed => match command {
                    Some(command) => Some(command),
                    None => { receiver_closed = true; continue; }
                },
            };
            let owner = Arc::clone(&self.owner);
            let lifetime = cancellation.clone();
            // Only one worker is ever admitted. This owner awaits actual worker
            // retirement rather than spawning another after request timeout.
            tokio::task::spawn_blocking(move || {
                if lifetime.is_cancelled() {
                    return Ok(());
                }
                let now = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_err(|_| invalid("self-iteration clock"))?
                    .as_millis()
                    .try_into()
                    .map_err(|_| invalid("self-iteration clock overflow"))?;
                let mut owner = owner
                    .lock()
                    .map_err(|_| invalid("self-iteration owner poisoned"))?;
                let context_command = matches!(
                    &command,
                    Some(
                        Command::Complete(..)
                            | Command::CompleteFailure(..)
                            | Command::InspectRound(..)
                            | Command::InspectCurrentRound(..)
                            | Command::PrepareParameterCheckpoint(..)
                            | Command::InspectParameterServingScope(..)
                            | Command::RejectProposal(..)
                            | Command::CompletePreparation(..)
                            | Command::PreparePlasticityInputFromContext(..)
                            | Command::RefreshPlasticityContext(..)
                    )
                );
                if context_command && let Err(error) = owner.journal.check_clock(now) {
                    if let Some(command) = command {
                        command.reject(error);
                    }
                    return Ok(());
                }
                if !context_command
                    && !matches!(
                        &command,
                        Some(
                            Command::Complete(..)
                                | Command::CompleteFailure(..)
                                | Command::InspectRound(..)
                                | Command::InspectCurrentRound(..)
                                | Command::RejectProposal(..)
                        )
                    )
                    && let Err(error) = owner.journal.observe_clock(now, command.is_some())
                {
                    if let Some(command) = command {
                        command.reject(error);
                    }
                    return Ok(());
                }
                let expiry = if context_command {
                    Ok(())
                } else {
                    owner.expire(now)
                };
                match expiry {
                    Ok(()) => {}
                    Err(error @ AgentdError::Overloaded { .. }) => {
                        if let Some(command) = command {
                            command.reject(error);
                        }
                        return Ok(());
                    }
                    Err(error) => return Err(error),
                }
                if let Some(command) = command {
                    match command {
                        Command::PreparePlasticityInputFromContext(
                            handle,
                            runtime,
                            request,
                            response,
                        ) => {
                            let _ =
                                response.send(owner.prepare_plasticity_input_from_context(
                                    handle, runtime, request,
                                ));
                        }
                        Command::RefreshPlasticityContext(
                            handle,
                            runtime,
                            expected_round,
                            path,
                            pin,
                            response,
                        ) => {
                            let _ = response.send(owner.refresh_plasticity_context(
                                handle,
                                runtime,
                                expected_round,
                                path,
                                pin,
                            ));
                        }
                        Command::InspectParameterServingScope(host, round, response) => {
                            let _ =
                                response.send(owner.inspect_parameter_serving_scope(host, round));
                        }
                        Command::PrepareParameterCheckpoint(host, round, path, pin, response) => {
                            let _ = response
                                .send(owner.prepare_parameter_checkpoint(host, round, path, pin));
                        }
                        Command::InspectCurrentRound(response) => {
                            let _ = response.send(owner.inspect_current_round());
                        }
                        Command::InspectRound(goal, policy, response) => {
                            let result = owner
                                .journal
                                .rounds
                                .as_ref()
                                .ok_or_else(|| invalid("round not reserved"))
                                .and_then(|rounds| rounds.status(&goal, policy));
                            let _ = response.send(result);
                        }
                        Command::Reserve(goal, canonical, envelope, response) => {
                            let result = (|| {
                                if !owner.trust.is_current_at(now)
                                    || canonical
                                        .policy()
                                        .objective_digest
                                        .parse::<Digest32>()
                                        .map_err(|e| invalid(e.to_string()))?
                                        != owner.trust.verifier().objective_digest()
                                {
                                    return Err(invalid(
                                        "round policy lacks current original learning trust",
                                    ));
                                }
                                if owner.journal.rounds.is_none() && owner.journal.pending() {
                                    return Err(invalid(
                                        "legacy pending candidate requires exact recovery",
                                    ));
                                }
                                let mut rounds = owner.journal.rounds.clone().unwrap_or_default();
                                let permit = rounds.reserve(goal, &canonical, &envelope, now)?;
                                owner.journal.persist_rounds(rounds)?;
                                Ok(permit)
                            })();
                            let _ = response.send(result);
                        }
                        Command::Begin(round, request, response) => {
                            let result = (|| {
                                if !owner.trust.is_current_at(now) {
                                    return Err(invalid(
                                        "model admission lacks current original learning trust",
                                    ));
                                }
                                let mut rounds = owner
                                    .journal
                                    .rounds
                                    .clone()
                                    .ok_or_else(|| invalid("round not reserved"))?;
                                let admission = rounds.begin(&round, &request, now)?;
                                owner.journal.persist_rounds(rounds)?;
                                Ok(admission)
                            })();
                            let _ = response.send(result);
                        }
                        Command::Complete(round, request, assessment, response) => {
                            let result =
                                terminal::complete(&mut owner, &round, &request, &assessment, now);
                            let _ = response.send(result);
                        }
                        Command::CompleteFailure(round, request, failure, response) => {
                            let result = terminal::complete_failed(
                                &mut owner, &round, &request, &failure, now,
                            );
                            let _ = response.send(result);
                        }
                        Command::CompletePreparation(round, terminal, response) => {
                            let result = super::round::preparation::complete(
                                &mut owner, &round, &terminal, now,
                            );
                            let _ = response.send(result);
                        }
                        Command::BeginCandidateEffects(round, assessment, response) => {
                            let result = owner.begin_candidate_effects(round, assessment, now);
                            let _ = response.send(result);
                        }
                        Command::RejectProposal(round, assessment, reason, response) => {
                            let result = (|| {
                                let mut rounds = owner
                                    .journal
                                    .rounds
                                    .clone()
                                    .ok_or_else(|| invalid("round not reserved"))?;
                                rounds.retain_terminal_clock(now);
                                rounds.reject_before_candidate_effects(
                                    &round,
                                    &assessment,
                                    reason,
                                )?;
                                owner.journal.persist_rounds(rounds)
                            })();
                            let _ = response.send(result);
                        }
                        Command::Freeze(candidate, response) => {
                            let _ = response.send(owner.freeze(*candidate, now));
                        }
                        Command::Evaluate(frozen, signed, response) => {
                            let _ = response.send(owner.evaluate(frozen, *signed, now));
                        }
                        Command::Select(frozen, signed, response) => {
                            let _ = response.send(owner.select(frozen, signed, now));
                        }
                        Command::Observe(frozen, verdict, signed, response) => {
                            let _ = response.send(owner.observe(frozen, verdict, signed, now));
                        }
                    }
                }
                Ok::<_, AgentdError>(())
            })
            .await
            .map_err(|error| invalid(format!("self-iteration worker: {error}")))??;
        }
    }
}

#[cfg(test)]
#[path = "self_iteration_runtime_tests.rs"]
mod tests;

#[path = "self_iteration_runtime_effects.rs"]
mod effects;

#[path = "self_iteration_runtime_current.rs"]
mod current;
#[path = "self_iteration_runtime_preparation.rs"]
mod preparation;
#[path = "self_iteration_runtime_terminal.rs"]
mod terminal;

#[path = "self_iteration_runtime_plasticity_context.rs"]
pub(crate) mod plasticity_context;

#[path = "self_iteration_runtime_parameter_checkpoint.rs"]
mod parameter_checkpoint;
