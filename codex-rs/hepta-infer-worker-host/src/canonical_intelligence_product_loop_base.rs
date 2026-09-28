//! One real canonical intelligence product continuation.
//!
//! This component does not implement another executor or learning writer. It
//! sequences the existing Agentd learning outbox, the existing runtime.codex
//! `AppServerModelDriver::run_intelligence` path, the existing durable inference
//! journal, and the existing Agentd run-lifecycle observer.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::str::FromStr;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::AgentRunPhase;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIntelligenceDecisionAppendV1;
use codex_hepta_agentd::AgentdIntelligenceLearningDispositionV1;
use codex_hepta_agentd::AgentdIntelligenceLearningHostV1;
use codex_hepta_agentd::AgentdIntelligenceOutcomeAppendV1;
use codex_hepta_agentd::AgentdIntelligenceProductContinuationFuture;
use codex_hepta_agentd::AgentdIntelligenceProductContinuationV1;
use codex_hepta_agentd::AgentdIntelligenceProductLoopDispositionV1;
use codex_hepta_agentd::AgentdIntelligenceProductLoopReceiptV1;
use codex_hepta_agentd::PreparedAgentdIntelligenceRunV1;
use codex_hepta_agentd::RunPhase;
use codex_hepta_agentd::RunReceipt;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;
use tokio::sync::Semaphore;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::AppServerModelDriver;
use crate::native_app_server::NativeAdmission;
use crate::native_app_server::NativeIntelligenceRunBinding;
use crate::native_app_server::NativeRunOutput;

const MAX_LOOP_CONCURRENCY: usize = 64;
const MAX_LEARNING_SETTLEMENT_STEPS: u32 = 256;
const MAX_OWNER_INPUT_BUDGET: Duration = Duration::from_secs(30);

pub struct CanonicalIntelligencePhysicalRequestV1 {
    pub decision: AgentdIntelligenceDecisionAppendV1,
    pub admission: NativeAdmission,
    /// Compatibility witness supplied by the owner. The bytes must equal the
    /// Prompt Registry/Context owner payload already frozen in `prepared`.
    pub prompt: String,
    /// Canonical Prompt delivery already contains its complete compiled context;
    /// adding a second query would create an unbound physical payload.
    pub context_query: Option<String>,
    pub cancellation: CancellationToken,
}

pub type CanonicalIntelligencePhysicalRequestFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<CanonicalIntelligencePhysicalRequestV1, AgentdError>>
            + Send
            + 'a,
    >,
>;

pub type CanonicalIntelligenceOutcomeFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<AgentdIntelligenceOutcomeAppendV1, AgentdError>>
            + Send
            + 'a,
    >,
>;

/// Host-owned inputs for the already-selected run. The owner creates signed
/// learning evidence and confirms the exact frozen physical payload; it cannot
/// replace Prompt/Context bytes, signing keys, policy, candidates, or outcome
/// interpretation at the continuation boundary.
pub trait CanonicalIntelligenceProductLoopOwnerV1: Send + Sync {
    fn prepare_physical_request<'a>(
        &'a self,
        prepared: &'a PreparedAgentdIntelligenceRunV1,
        attached: &'a RunReceipt,
    ) -> CanonicalIntelligencePhysicalRequestFuture<'a>;

    fn build_terminal_outcome<'a>(
        &'a self,
        prepared: &'a PreparedAgentdIntelligenceRunV1,
        terminal: &'a RunReceipt,
        output: &'a NativeRunOutput,
        provider_terminal_digest: Digest32,
    ) -> CanonicalIntelligenceOutcomeFuture<'a>;
}

/// Product embedding over the existing physical and learning owners.
pub struct CanonicalIntelligenceProductLoopV1 {
    driver: Arc<AppServerModelDriver>,
    control: Mutex<DurableInferenceControl>,
    learning: Arc<AgentdIntelligenceLearningHostV1>,
    owner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1>,
    agentd_socket: PathBuf,
    agent_id: AgentId,
    spawn_generation: u64,
    settlement_steps: u32,
    owner_input_budget: Duration,
    slots: Arc<Semaphore>,
}

impl CanonicalIntelligenceProductLoopV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        driver: Arc<AppServerModelDriver>,
        control: DurableInferenceControl,
        learning: Arc<AgentdIntelligenceLearningHostV1>,
        owner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1>,
        agentd_socket: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        settlement_steps: u32,
        owner_input_budget: Duration,
        maximum_concurrent_loops: usize,
    ) -> Result<Self, AgentdError> {
        if !agentd_socket.is_absolute()
            || spawn_generation == 0
            || settlement_steps == 0
            || settlement_steps > MAX_LEARNING_SETTLEMENT_STEPS
            || owner_input_budget.is_zero()
            || owner_input_budget > MAX_OWNER_INPUT_BUDGET
            || maximum_concurrent_loops == 0
            || maximum_concurrent_loops > MAX_LOOP_CONCURRENCY
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence product-loop policy is out of bounds".to_string(),
            ));
        }
        let expected_generation = spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("running generation overflow".to_string()))?;
        if learning.owner_generation().get() != expected_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "learning owner generation {} does not match Running generation {expected_generation}",
                learning.owner_generation().get()
            )));
        }
        Ok(Self {
            driver,
            control: Mutex::new(control),
            learning,
            owner,
            agentd_socket,
            agent_id,
            spawn_generation,
            settlement_steps,
            owner_input_budget,
            slots: Arc::new(Semaphore::new(maximum_concurrent_loops)),
        })
    }

    async fn continue_ready_impl(
        &self,
        prepared: PreparedAgentdIntelligenceRunV1,
        attached: RunReceipt,
    ) -> Result<AgentdIntelligenceProductLoopReceiptV1, AgentdError> {
        validate_attached(&prepared, &attached)?;
        let permit = Arc::clone(&self.slots)
            .try_acquire_owned()
            .map_err(|_| AgentdError::Overloaded {
                retry_after_ms: duration_millis(self.owner_input_budget),
            })?;
        let _permit = permit;

        let request = timeout(
            self.owner_input_budget,
            self.owner.prepare_physical_request(&prepared, &attached),
        )
        .await
        .map_err(|_| AgentdError::Overloaded {
            retry_after_ms: duration_millis(self.owner_input_budget),
        })??;

        // The actual Prompt Registry realization, Context compilation,
        // serialization and attachment are frozen before Decision publication.
        // Owner input remains useful for signed learning evidence and admission,
        // but it cannot replace the bytes or append an unbound context query.
        let frozen = prepared.physical_prompt().map_err(|error| {
            AgentdError::Protocol(format!(
                "canonical product continuation omitted owner-backed Prompt delivery: {error}"
            ))
        })?;
        let physical_prompt = require_exact_frozen_prompt(
            &frozen.payload,
            &request.prompt,
            request.context_query.as_ref(),
        )?;

        let scope_id = self
            .learning
            .learning_scope_id_for(&prepared)
            .map_err(learning_error)?;
        let decision_operation_id = self
            .learning
            .decision_operation_id_for(&prepared, &request.decision.episode_id)
            .map_err(learning_error)?;
        self.learning
            .enqueue_decision(&prepared, request.decision)
            .await
            .map_err(learning_error)?;
        let decision = self
            .learning
            .settle_operation_current(
                &scope_id,
                &decision_operation_id,
                self.settlement_steps,
            )
            .await
            .map_err(learning_error)?;
        match decision.disposition {
            AgentdIntelligenceLearningDispositionV1::Acknowledged => {}
            AgentdIntelligenceLearningDispositionV1::Indeterminate => {
                return Ok(indeterminate_receipt(
                    &prepared,
                    decision_operation_id,
                ));
            }
            AgentdIntelligenceLearningDispositionV1::Rejected
            | AgentdIntelligenceLearningDispositionV1::Revoked => {
                return Err(AgentdError::Protocol(format!(
                    "canonical Decision was terminally rejected: {:?}",
                    decision.disposition
                )));
            }
        }

        let binding = NativeIntelligenceRunBinding {
            run_id: attached.run_id.clone(),
            expected_revision: attached.revision,
            context_digest: attached
                .context_digest
                .clone()
                .ok_or_else(|| AgentdError::Protocol("attached context missing".to_string()))?,
            envelope_digest: prepared.envelope.envelope_digest.to_string(),
        };
        let native_request_id = request.admission.request_id.clone();
        let physical = {
            let mut control = self.control.lock().await;
            match self
                .driver
                .run_intelligence(
                    &mut control,
                    request.admission,
                    physical_prompt,
                    None,
                    binding,
                    &request.cancellation,
                )
                .await
            {
                Ok(output) => output,
                Err(error) => {
                    let uncertain = control.native_record(&native_request_id).is_some_and(|record| {
                        matches!(
                            record.state,
                            NativeReservationState::Dispatching
                                | NativeReservationState::Running
                                | NativeReservationState::Cancelling
                                | NativeReservationState::Indeterminate
                        )
                    });
                    if uncertain {
                        return Ok(indeterminate_receipt(
                            &prepared,
                            decision_operation_id,
                        ));
                    }
                    return Err(AgentdError::Protocol(format!(
                        "physical intelligence turn was rejected before an uncertain effect: {error}"
                    )));
                }
            }
        };

        let provider_terminal_digest = match physical_terminal_digest(&physical) {
            Some(value) => value,
            None => {
                return Ok(indeterminate_receipt(
                    &prepared,
                    decision_operation_id,
                ));
            }
        };
        let terminal = match matching_terminal_receipt(
            self.current_terminal_receipt(&attached.run_id).await,
            &physical,
        ) {
            Some(value) => value,
            None => {
                return Ok(reconciliation_required_receipt(
                    &prepared,
                    decision_operation_id,
                    None,
                    provider_terminal_digest,
                ));
            }
        };

        let outcome_request = match timeout(
            self.owner_input_budget,
            self.owner.build_terminal_outcome(
                &prepared,
                &terminal,
                &physical,
                provider_terminal_digest,
            ),
        )
        .await
        {
            Ok(Ok(value)) => value,
            Ok(Err(_)) | Err(_) => {
                return Ok(reconciliation_required_receipt(
                    &prepared,
                    decision_operation_id,
                    None,
                    provider_terminal_digest,
                ));
            }
        };
        let outcome_operation_id = match self
            .learning
            .outcome_operation_id_for(&prepared, &outcome_request)
        {
            Ok(value) => value,
            Err(_) => {
                return Ok(reconciliation_required_receipt(
                    &prepared,
                    decision_operation_id,
                    None,
                    provider_terminal_digest,
                ));
            }
        };
        if self
            .learning
            .enqueue_outcome(&prepared, outcome_request)
            .await
            .is_err()
        {
            return Ok(reconciliation_required_receipt(
                &prepared,
                decision_operation_id,
                Some(outcome_operation_id),
                provider_terminal_digest,
            ));
        }
        let outcome = match self
            .learning
            .settle_operation_current(
                &scope_id,
                &outcome_operation_id,
                self.settlement_steps,
            )
            .await
        {
            Ok(value) => value,
            Err(_) => {
                return Ok(reconciliation_required_receipt(
                    &prepared,
                    decision_operation_id,
                    Some(outcome_operation_id),
                    provider_terminal_digest,
                ));
            }
        };
        match outcome.disposition {
            AgentdIntelligenceLearningDispositionV1::Acknowledged => {
                Ok(AgentdIntelligenceProductLoopReceiptV1 {
                    run_id: prepared.envelope.run_id.clone(),
                    decision_operation_id,
                    outcome_operation_id: Some(outcome_operation_id),
                    physical_terminal_digest: Some(provider_terminal_digest),
                    disposition: AgentdIntelligenceProductLoopDispositionV1::Completed,
                })
            }
            AgentdIntelligenceLearningDispositionV1::Indeterminate
            | AgentdIntelligenceLearningDispositionV1::Rejected
            | AgentdIntelligenceLearningDispositionV1::Revoked => {
                Ok(reconciliation_required_receipt(
                    &prepared,
                    decision_operation_id,
                    Some(outcome_operation_id),
                    provider_terminal_digest,
                ))
            }
        }
    }

    async fn current_terminal_receipt(
        &self,
        run_id: &str,
    ) -> Result<Option<RunReceipt>, AgentdError> {
        let client = AgentdClient::new(
            self.agentd_socket.clone(),
            self.agent_id.clone(),
            self.spawn_generation,
        )?;
        client
            .run_status(run_id.to_string())
            .await?
            .map(protocol_receipt)
            .transpose()
    }
}

impl AgentdIntelligenceProductContinuationV1 for CanonicalIntelligenceProductLoopV1 {
    fn continue_ready<'a>(
        &'a self,
        prepared: PreparedAgentdIntelligenceRunV1,
        run_receipt: RunReceipt,
    ) -> AgentdIntelligenceProductContinuationFuture<'a> {
        Box::pin(async move { self.continue_ready_impl(prepared, run_receipt).await })
    }
}

fn validate_attached(
    prepared: &PreparedAgentdIntelligenceRunV1,
    attached: &RunReceipt,
) -> Result<(), AgentdError> {
    let snapshot = prepared.run_snapshot();
    let context = prepared.context_attachment();
    if attached.phase != RunPhase::ContextAttached
        || attached.run_id != snapshot.run_id
        || attached.context_digest.as_deref() != Some(context.context_digest.as_str())
        || attached.compilation_receipt_digest.as_deref()
            != Some(context.compilation_receipt_digest.as_str())
        || attached.authority_epoch != snapshot.authority_epoch
        || attached.generation != snapshot.generation
        || attached.fence_digest != snapshot.fence_digest
        || attached.deadline_ms != snapshot.deadline_ms
    {
        return Err(AgentdError::Protocol(
            "canonical product continuation requires the exact ContextAttached run"
                .to_string(),
        ));
    }
    Ok(())
}

fn require_exact_frozen_prompt(
    frozen: &[u8],
    owner_witness: &str,
    context_query: Option<&String>,
) -> Result<String, AgentdError> {
    if context_query.is_some() {
        return Err(AgentdError::Protocol(
            "canonical Prompt delivery already contains compiled context; a second context query is forbidden"
                .to_string(),
        ));
    }
    if frozen != owner_witness.as_bytes() {
        return Err(AgentdError::Protocol(
            "physical Prompt bytes differ from the owner-backed prepared delivery".to_string(),
        ));
    }
    String::from_utf8(frozen.to_vec()).map_err(|_| {
        AgentdError::Protocol(
            "owner-backed physical Prompt payload is not valid UTF-8 for App Server".to_string(),
        )
    })
}

fn protocol_receipt(value: AgentRunReceipt) -> Result<RunReceipt, AgentdError> {
    Ok(RunReceipt {
        run_id: value.run_id,
        revision: value.revision,
        phase: match value.phase {
            AgentRunPhase::Admitted => RunPhase::Admitted,
            AgentRunPhase::ContextAttached => RunPhase::ContextAttached,
            AgentRunPhase::Dispatched => RunPhase::Dispatched,
            AgentRunPhase::Cancelling => RunPhase::Cancelling,
            AgentRunPhase::Cancelled => RunPhase::Cancelled,
            AgentRunPhase::Succeeded => RunPhase::Succeeded,
            AgentRunPhase::Failed => RunPhase::Failed,
            AgentRunPhase::Indeterminate => RunPhase::Indeterminate,
        },
        context_digest: value.context_digest,
        authority_epoch: value.authority_epoch,
        generation: value.generation,
        fence_digest: value.fence_digest,
        deadline_ms: value.deadline_ms,
        cancel_reason: value.cancel_reason,
        cancel_ack_deadline_ms: value.cancel_ack_deadline_ms,
        compilation_receipt_digest: value.compilation_receipt_digest,
        terminal_observed: value.terminal_observed,
        idempotent: value.idempotent,
    })
}

fn matching_terminal_receipt(
    observed: Result<Option<RunReceipt>, AgentdError>,
    output: &NativeRunOutput,
) -> Option<RunReceipt> {
    match observed {
        Ok(Some(receipt)) if terminal_matches_output(&receipt, output) => Some(receipt),
        Ok(_) | Err(_) => None,
    }
}

fn terminal_matches_output(receipt: &RunReceipt, output: &NativeRunOutput) -> bool {
    if !receipt.terminal_observed || !output.terminal_observed {
        return false;
    }
    matches!(
        (receipt.phase, output.status),
        (RunPhase::Succeeded, NativeRunStatus::Completed)
            | (RunPhase::Failed, NativeRunStatus::Failed)
            | (RunPhase::Cancelled, NativeRunStatus::Interrupted)
    )
}

fn physical_terminal_digest(output: &NativeRunOutput) -> Option<Digest32> {
    if !output.terminal_observed || output.status == NativeRunStatus::Indeterminate {
        return None;
    }
    output
        .codex_terminal_correlation_digest
        .as_deref()
        .and_then(|value| Digest32::from_str(value).ok())
        .filter(|value| !value.is_zero())
}

fn indeterminate_receipt(
    prepared: &PreparedAgentdIntelligenceRunV1,
    decision_operation_id: StableId,
) -> AgentdIntelligenceProductLoopReceiptV1 {
    AgentdIntelligenceProductLoopReceiptV1 {
        run_id: prepared.envelope.run_id.clone(),
        decision_operation_id,
        outcome_operation_id: None,
        physical_terminal_digest: None,
        disposition: AgentdIntelligenceProductLoopDispositionV1::Indeterminate,
    }
}

fn reconciliation_required_receipt(
    prepared: &PreparedAgentdIntelligenceRunV1,
    decision_operation_id: StableId,
    outcome_operation_id: Option<StableId>,
    physical_terminal_digest: Digest32,
) -> AgentdIntelligenceProductLoopReceiptV1 {
    AgentdIntelligenceProductLoopReceiptV1 {
        run_id: prepared.envelope.run_id.clone(),
        decision_operation_id,
        outcome_operation_id,
        physical_terminal_digest: Some(physical_terminal_digest),
        disposition: AgentdIntelligenceProductLoopDispositionV1::ReconciliationRequired,
    }
}

fn duration_millis(value: Duration) -> u64 {
    u64::try_from(value.as_millis()).unwrap_or(u64::MAX).max(1)
}

fn learning_error(error: codex_hepta_agentd::AgentdIntelligenceLearningErrorV1) -> AgentdError {
    AgentdError::Protocol(format!("canonical intelligence learning: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
    use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;

    fn terminal_output(status: NativeRunStatus, digest: Option<&str>) -> NativeRunOutput {
        NativeRunOutput {
            thread_id: "thread.test".to_string(),
            turn_id: "turn.test".to_string(),
            model: "model.test".to_string(),
            model_provider: "provider.test".to_string(),
            status,
            boundary_status: match status {
                NativeRunStatus::Completed => NativeBoundaryStatus::Succeeded,
                NativeRunStatus::Failed => NativeBoundaryStatus::Failed,
                NativeRunStatus::Interrupted => NativeBoundaryStatus::Interrupted,
                NativeRunStatus::Indeterminate => NativeBoundaryStatus::Indeterminate,
            },
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: status != NativeRunStatus::Indeterminate,
            stop_reason: None,
            owner_authority: NativeOwnerAuthority::ObservedReady,
            codex_terminal_correlation_digest: digest.map(ToOwned::to_owned),
        }
    }

    fn terminal_receipt(phase: RunPhase) -> RunReceipt {
        RunReceipt {
            run_id: "run.test".to_string(),
            revision: 4,
            phase,
            context_digest: Some("context".to_string()),
            authority_epoch: 1,
            generation: 2,
            fence_digest: "fence".to_string(),
            deadline_ms: 100,
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
            compilation_receipt_digest: Some("envelope".to_string()),
            terminal_observed: true,
            idempotent: false,
        }
    }

    #[test]
    fn provider_terminal_requires_exact_correlation_digest() {
        assert!(physical_terminal_digest(&terminal_output(
            NativeRunStatus::Completed,
            None
        ))
        .is_none());
        let digest = Digest32::of_bytes(b"terminal");
        assert_eq!(
            physical_terminal_digest(&terminal_output(
                NativeRunStatus::Completed,
                Some(&digest.to_string())
            )),
            Some(digest)
        );
    }

    #[test]
    fn protocol_and_physical_terminal_must_agree() {
        let receipt = terminal_receipt(RunPhase::Succeeded);
        assert!(terminal_matches_output(
            &receipt,
            &terminal_output(
                NativeRunStatus::Completed,
                Some(&Digest32::of_bytes(b"terminal").to_string())
            )
        ));
        assert!(!terminal_matches_output(
            &receipt,
            &terminal_output(
                NativeRunStatus::Failed,
                Some(&Digest32::of_bytes(b"terminal").to_string())
            )
        ));
    }

    #[test]
    fn terminal_control_loss_never_discards_a_provider_terminal_into_replay() {
        let output = terminal_output(
            NativeRunStatus::Completed,
            Some(&Digest32::of_bytes(b"terminal").to_string()),
        );
        assert!(
            matching_terminal_receipt(
                Err(AgentdError::Protocol("temporarily unavailable".to_string())),
                &output,
            )
            .is_none()
        );
        assert!(matching_terminal_receipt(Ok(None), &output).is_none());
        assert!(matching_terminal_receipt(
            Ok(Some(terminal_receipt(RunPhase::Failed))),
            &output,
        )
        .is_none());
        assert!(matching_terminal_receipt(
            Ok(Some(terminal_receipt(RunPhase::Succeeded))),
            &output,
        )
        .is_some());
    }

    #[test]
    fn unknown_dispatch_and_post_terminal_reconciliation_are_distinct() {
        assert_ne!(
            AgentdIntelligenceProductLoopDispositionV1::Indeterminate,
            AgentdIntelligenceProductLoopDispositionV1::ReconciliationRequired
        );
    }

    #[test]
    fn physical_prompt_must_equal_frozen_payload_and_cannot_add_context() {
        assert_eq!(
            require_exact_frozen_prompt(b"exact prompt", "exact prompt", None)
                .expect("exact frozen prompt"),
            "exact prompt"
        );
        assert!(require_exact_frozen_prompt(b"exact prompt", "substituted", None).is_err());
        let query = "extra context".to_string();
        assert!(
            require_exact_frozen_prompt(b"exact prompt", "exact prompt", Some(&query)).is_err()
        );
        assert!(require_exact_frozen_prompt(&[0xff], "", None).is_err());
    }
}
