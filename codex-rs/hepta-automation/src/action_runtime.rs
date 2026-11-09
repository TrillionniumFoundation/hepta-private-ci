//! Conservative runtime views over the existing goal-checked effect boundary.
//!
//! A view carries no dispatch, cancellation, settlement or retry authority.
//! Keep the underlying facts: a partial effect can also be waiting for input.

use serde::Deserialize;
use serde::Serialize;

use crate::ActionConditionV1;
use crate::ActionExecutionStateV1;
use crate::ActionGoalStateV1;
use crate::ActionSkillObservationV1;
use crate::AuthorizedEffectOutcome;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ActionTerminalOutcomeV1 {
    Succeeded,
    Failed,
}

/// A summary for display and planning, never a replacement for a durable receipt.
/// Missing observations, process exit and cancellation acknowledgements cannot
/// establish terminal success or failure. Destination profiles may support only
/// a subset of these states; they must not invent unsupported execution facts.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum ActionRuntimeStateV1 {
    Running,
    WaitingInput,
    PartialEffect,
    Terminal { outcome: ActionTerminalOutcomeV1 },
    Unknown,
}

/// One newly requested driver observation with its original identity and evidence.
/// The trusted destination observer owns freshness; this view does not add a
/// timestamp, sequence fence or proof against replaying old destination state.
/// Partial effect takes precedence in the summary; `observation.execution`
/// still preserves simultaneous waiting or running facts. A later UNKNOWN view
/// does not erase a historical durable receipt or authorize a second dispatch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionRuntimeObservationV1 {
    pub state: ActionRuntimeStateV1,
    pub provider_outcome: AuthorizedEffectOutcome,
    pub observation: ActionSkillObservationV1,
}

impl ActionRuntimeObservationV1 {
    pub(crate) fn from_observation(
        provider_outcome: AuthorizedEffectOutcome,
        observation: ActionSkillObservationV1,
    ) -> Self {
        let state = match verified_outcome(provider_outcome, &observation) {
            AuthorizedEffectOutcome::Succeeded => ActionRuntimeStateV1::Terminal {
                outcome: ActionTerminalOutcomeV1::Succeeded,
            },
            AuthorizedEffectOutcome::Failed => ActionRuntimeStateV1::Terminal {
                outcome: ActionTerminalOutcomeV1::Failed,
            },
            AuthorizedEffectOutcome::Indeterminate => {
                if observation.goal == ActionGoalStateV1::Partial {
                    ActionRuntimeStateV1::PartialEffect
                } else {
                    match observation.execution {
                        ActionExecutionStateV1::WaitingForInput => ActionRuntimeStateV1::WaitingInput,
                        ActionExecutionStateV1::Running => ActionRuntimeStateV1::Running,
                        ActionExecutionStateV1::NotStarted
                        | ActionExecutionStateV1::Returned { .. }
                        | ActionExecutionStateV1::Interrupted
                        | ActionExecutionStateV1::Unknown => ActionRuntimeStateV1::Unknown,
                    }
                }
            }
        };
        Self {
            state,
            provider_outcome,
            observation,
        }
    }
}

/// Shared with the existing driver so display and settlement cannot disagree
/// about the predicates. Only the durable owner may actually settle an attempt.
pub(crate) fn verified_outcome(
    provider_outcome: AuthorizedEffectOutcome,
    observation: &ActionSkillObservationV1,
) -> AuthorizedEffectOutcome {
    let terminal = matches!(
        observation.execution,
        ActionExecutionStateV1::Returned { .. } | ActionExecutionStateV1::Interrupted
    );
    if provider_outcome == AuthorizedEffectOutcome::Succeeded
        && terminal
        && observation.termination == ActionConditionV1::Met
        && observation.goal == ActionGoalStateV1::Satisfied
    {
        AuthorizedEffectOutcome::Succeeded
    } else if provider_outcome == AuthorizedEffectOutcome::Failed
        && observation.absence_proof_digest.is_some()
        && observation.goal == ActionGoalStateV1::Unsatisfied
        && observation.termination == ActionConditionV1::Met
        && (terminal || observation.execution == ActionExecutionStateV1::NotStarted)
    {
        AuthorizedEffectOutcome::Failed
    } else {
        AuthorizedEffectOutcome::Indeterminate
    }
}
