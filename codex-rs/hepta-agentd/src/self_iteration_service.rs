//! Non-test control.engineering service composition for parameter self-iteration.
//!
//! The service owns the coordinator verifier and terminal journal only. Submission
//! is delegated to `AgentdState::submit_parameter_plasticity_v1`, which reaches the
//! state-held `AgentdLearningPlasticityProducerV1`; no proposal writer or activation
//! capability is exposed to this service.

use std::future::Future;
use std::pin::Pin;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::Digest32;
use tokio_util::sync::CancellationToken;

use super::self_iteration_coordinator::CoordinatedParameterPlasticityReceiptV1;
use super::self_iteration_coordinator::CoordinatedParameterPlasticityRequestV1;
use super::self_iteration_coordinator::SelfIterationCoordinatorErrorV1;
use super::self_iteration_coordinator::SelfIterationTerminalDispositionV1;
use super::self_iteration_coordinator::SelfIterationTerminalJournalV1;
use super::self_iteration_coordinator::prepare_coordinated_parameter_plasticity_v1;
use crate::AgentdState;
use crate::plasticity_runtime::PlasticityRuntimeBudgetV1;
use crate::plasticity_runtime::PlasticityRuntimeCallErrorV1;

#[derive(Debug)]
pub enum ControlEngineeringSelfIterationErrorV1 {
    Coordinator(SelfIterationCoordinatorErrorV1),
    Runtime(PlasticityRuntimeCallErrorV1),
    PreviouslyFailed(Digest32),
    DeadlineExceeded,
    Cancelled,
    Poisoned,
}

impl std::fmt::Display for ControlEngineeringSelfIterationErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for ControlEngineeringSelfIterationErrorV1 {}
impl From<SelfIterationCoordinatorErrorV1> for ControlEngineeringSelfIterationErrorV1 {
    fn from(value: SelfIterationCoordinatorErrorV1) -> Self {
        Self::Coordinator(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for ControlEngineeringSelfIterationErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Runtime(value)
    }
}

pub struct ControlEngineeringSelfIterationCoordinatorV1 {
    verifier: LearningEvidenceVerifierV1,
    journal: Mutex<SelfIterationTerminalJournalV1>,
}

impl ControlEngineeringSelfIterationCoordinatorV1 {
    pub fn open(
        journal_path: &Path,
        journal_scope: Digest32,
        verifier: LearningEvidenceVerifierV1,
    ) -> Result<Self, SelfIterationCoordinatorErrorV1> {
        Ok(Self {
            verifier,
            journal: Mutex::new(SelfIterationTerminalJournalV1::open(
                journal_path,
                journal_scope,
            )?),
        })
    }

    pub async fn submit_with<Submit, Submitted>(
        &self,
        request: CoordinatedParameterPlasticityRequestV1,
        now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
        submit: Submit,
    ) -> Result<CoordinatedParameterPlasticityReceiptV1, ControlEngineeringSelfIterationErrorV1>
    where
        Submit: FnOnce(ParameterPlasticityProductRequestV1) -> Submitted,
        Submitted: Future<
            Output = Result<
                ParameterPlasticityProductReceiptV1,
                PlasticityRuntimeCallErrorV1,
            >,
        >,
    {
        budget.validate(current_unix_seconds()?)?;
        let prepared = prepare_coordinated_parameter_plasticity_v1(request, &self.verifier, now)?;

        {
            let journal = self.journal.lock().map_err(|_| {
                ControlEngineeringSelfIterationErrorV1::Poisoned
            })?;
            if let Some(terminal) = journal.lookup(&prepared.key, prepared.request_digest)? {
                return match terminal.disposition {
                    SelfIterationTerminalDispositionV1::Committed => {
                        Ok(CoordinatedParameterPlasticityReceiptV1 {
                            product: None,
                            terminal,
                        })
                    }
                    SelfIterationTerminalDispositionV1::Failed => Err(
                        ControlEngineeringSelfIterationErrorV1::PreviouslyFailed(
                            terminal.outcome_digest,
                        ),
                    ),
                    SelfIterationTerminalDispositionV1::Pending => Err(
                        SelfIterationCoordinatorErrorV1::Indeterminate.into(),
                    ),
                };
            }
        }
        {
            let mut journal = self.journal.lock().map_err(|_| {
                ControlEngineeringSelfIterationErrorV1::Poisoned
            })?;
            journal.append_pending(prepared.key.clone(), prepared.request_digest)?;
        }

        let remaining = remaining_until(budget.deadline_unix_seconds)?;
        let submitted = tokio::select! {
            _ = cancellation.cancelled() => {
                return Err(ControlEngineeringSelfIterationErrorV1::Cancelled);
            }
            value = tokio::time::timeout(remaining, submit(prepared.product)) => {
                match value {
                    Ok(value) => value,
                    Err(_) => return Err(ControlEngineeringSelfIterationErrorV1::DeadlineExceeded),
                }
            }
        };

        match submitted {
            Ok(product) => {
                let terminal = self
                    .journal
                    .lock()
                    .map_err(|_| ControlEngineeringSelfIterationErrorV1::Poisoned)?
                    .append_committed(
                        prepared.key,
                        prepared.request_digest,
                        &product,
                    )?;
                Ok(CoordinatedParameterPlasticityReceiptV1 {
                    product: Some(product),
                    terminal,
                })
            }
            Err(error) => {
                let mut material = b"hepta.control-engineering.self-iteration-failure.v1\0".to_vec();
                material.extend_from_slice(format!("{error:?}").as_bytes());
                let outcome_digest = Digest32::of_bytes(&material);
                self.journal
                    .lock()
                    .map_err(|_| ControlEngineeringSelfIterationErrorV1::Poisoned)?
                    .append_failed(
                        prepared.key,
                        prepared.request_digest,
                        outcome_digest,
                    )?;
                Err(error.into())
            }
        }
    }
}

/// Extension port used by the control.engineering owner. The implementation calls
/// the existing AgentdState method, so all submissions traverse the state-held named
/// producer and its long-lived owner rather than opening another writer path.
pub(crate) trait AgentdSelfIterationSubmissionV1 {
    fn submit_parameter_self_iteration_v1<'a>(
        &'a self,
        coordinator: &'a ControlEngineeringSelfIterationCoordinatorV1,
        request: CoordinatedParameterPlasticityRequestV1,
        now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Pin<
        Box<
            dyn Future<
                    Output = Result<
                        CoordinatedParameterPlasticityReceiptV1,
                        ControlEngineeringSelfIterationErrorV1,
                    >,
                > + Send
                + 'a,
        >,
    >;
}

impl AgentdSelfIterationSubmissionV1 for AgentdState {
    fn submit_parameter_self_iteration_v1<'a>(
        &'a self,
        coordinator: &'a ControlEngineeringSelfIterationCoordinatorV1,
        request: CoordinatedParameterPlasticityRequestV1,
        now: u64,
        budget: PlasticityRuntimeBudgetV1,
        cancellation: CancellationToken,
    ) -> Pin<
        Box<
            dyn Future<
                    Output = Result<
                        CoordinatedParameterPlasticityReceiptV1,
                        ControlEngineeringSelfIterationErrorV1,
                    >,
                > + Send
                + 'a,
        >,
    > {
        Box::pin(async move {
            coordinator
                .submit_with(request, now, budget, cancellation, |product| {
                    self.submit_parameter_plasticity_v1(product, now)
                })
                .await
        })
    }
}

fn current_unix_seconds() -> Result<u64, ControlEngineeringSelfIterationErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| ControlEngineeringSelfIterationErrorV1::DeadlineExceeded)
}

fn remaining_until(
    deadline_unix_seconds: u64,
) -> Result<Duration, ControlEngineeringSelfIterationErrorV1> {
    deadline_unix_seconds
        .checked_sub(current_unix_seconds()?)
        .filter(|value| *value > 0)
        .map(Duration::from_secs)
        .ok_or(ControlEngineeringSelfIterationErrorV1::DeadlineExceeded)
}
