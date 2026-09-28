//! Daemon-owned scheduling for durable intelligence Decision/Outcome closure.
//!
//! The host and all final-use authority are supplied explicitly by the product
//! embedding. Agentd owns only bounded restart reconciliation and outbox drain
//! scheduling for the current Running generation. The default CLI installs no
//! host and therefore gains no learning-writer authority.

use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_operations::DurableOperationError;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIntelligenceLearningErrorV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdState;

const MIN_RECONCILE_INTERVAL: Duration = Duration::from_millis(10);
const MAX_RECONCILE_INTERVAL: Duration = Duration::from_secs(60 * 60);
const MAX_RECONCILE_BATCH: u32 = 256;
const NOT_READY_POLL: Duration = Duration::from_millis(50);

/// Explicit product-owned scheduling profile for the durable learning outbox.
///
/// Construction does not mint a writer, grant provider, or authority. Those
/// objects are already sealed inside `AgentdIntelligenceLearningHostV1`.
pub struct AgentdIntelligenceLearningRuntimeConfigV1 {
    host: Arc<AgentdIntelligenceLearningHostV1>,
    interval: Duration,
    max_batch: u32,
}

impl AgentdIntelligenceLearningRuntimeConfigV1 {
    pub fn new(
        host: Arc<AgentdIntelligenceLearningHostV1>,
        interval: Duration,
        max_batch: u32,
    ) -> Result<Self, AgentdError> {
        validate_runtime_policy(interval, max_batch)?;
        Ok(Self {
            host,
            interval,
            max_batch,
        })
    }

    #[must_use]
    pub fn owner_generation(&self) -> u64 {
        self.host.owner_generation().get()
    }

    pub(crate) fn into_parts(self) -> (Arc<AgentdIntelligenceLearningHostV1>, Duration, u32) {
        (self.host, self.interval, self.max_batch)
    }
}

fn validate_runtime_policy(interval: Duration, max_batch: u32) -> Result<(), AgentdError> {
    if !(MIN_RECONCILE_INTERVAL..=MAX_RECONCILE_INTERVAL).contains(&interval) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation interval must be 10ms..=1h".to_string(),
        ));
    }
    if !(1..=MAX_RECONCILE_BATCH).contains(&max_batch) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation batch must be 1..=256".to_string(),
        ));
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CycleBudget {
    reconcile: u32,
    dispatch: u32,
}

/// Reserve work for both restart reconciliation and newly prepared operations.
/// A batch of one alternates ownership between the two classes; larger batches
/// always reserve at least one slot for each class. This prevents a permanently
/// indeterminate oldest row from starving all newly prepared work.
fn cycle_budget(max_batch: u32, reconcile_turn: &mut bool) -> CycleBudget {
    debug_assert!(max_batch > 0);
    if max_batch == 1 {
        let budget = if *reconcile_turn {
            CycleBudget {
                reconcile: 1,
                dispatch: 0,
            }
        } else {
            CycleBudget {
                reconcile: 0,
                dispatch: 1,
            }
        };
        *reconcile_turn = !*reconcile_turn;
        return budget;
    }

    let dispatch = (max_batch / 4).max(1);
    CycleBudget {
        reconcile: max_batch - dispatch,
        dispatch,
    }
}

fn current_validation_time() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AgentdError::Protocol("learning validation clock is before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .ok()
        .filter(|value| *value != 0)
        .ok_or_else(|| AgentdError::Protocol("learning validation clock overflow".to_string()))
}

pub(crate) async fn run_intelligence_learning_runtime_v1(
    host: Arc<AgentdIntelligenceLearningHostV1>,
    state: Arc<AgentdState>,
    interval: Duration,
    max_batch: u32,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    validate_runtime_policy(interval, max_batch)?;
    let mut reconcile_turn = true;
    loop {
        if !state.automation_admission_ready()? {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(std::cmp::min(interval, NOT_READY_POLL)) => {}
            }
            continue;
        }

        let current_generation = state.current_generation()?;
        let owner_generation = host.owner_generation().get();
        if current_generation != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(format!(
                "intelligence learning host generation {owner_generation} does not match current Running generation {current_generation}"
            )));
        }

        let budget = cycle_budget(max_batch, &mut reconcile_turn);
        let reconciled = if budget.reconcile == 0 {
            0
        } else {
            let validation_now = current_validation_time()?;
            match host
                .reconcile_unsettled_at(budget.reconcile, validation_now)
                .await
            {
                Ok(receipts) => u32::try_from(receipts.len()).unwrap_or(budget.reconcile),
                Err(error) if retryable_learning_error(&error) => budget.reconcile,
                Err(error) => return Err(learning_error(error)),
            }
        };
        let unused_reconciliation = budget.reconcile.saturating_sub(reconciled);
        let dispatch_budget = budget.dispatch.saturating_add(unused_reconciliation);
        for _ in 0..dispatch_budget {
            let validation_now = current_validation_time()?;
            match host.dispatch_next_at(validation_now).await {
                Ok(Some(_)) => {}
                Ok(None) => break,
                Err(error) if retryable_learning_error(&error) => break,
                Err(error) => return Err(learning_error(error)),
            }
        }

        // A generation change during destination observation or append closes
        // the required service. The operation store retains any unsettled row
        // for adoption and exact replay by the successor generation.
        state.refresh_generation()?;
        if state.current_generation()? != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(
                "intelligence learning generation changed during reconciliation".to_string(),
            ));
        }

        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {}
        }
    }
}

fn retryable_learning_error(error: &AgentdIntelligenceLearningErrorV1) -> bool {
    match error {
        AgentdIntelligenceLearningErrorV1::Io(_) => true,
        AgentdIntelligenceLearningErrorV1::Agentd(
            AgentdError::Overloaded { .. } | AgentdError::Io(_),
        ) => true,
        AgentdIntelligenceLearningErrorV1::Operation(
            DurableOperationError::Capacity
            | DurableOperationError::StaleLease
            | DurableOperationError::Unavailable(_),
        ) => true,
        AgentdIntelligenceLearningErrorV1::Authority(
            FinalUseError::AlreadyClaimed
            | FinalUseError::CapacityExceeded
            | FinalUseError::DispatchInProgress
            | FinalUseError::Unavailable
            | FinalUseError::UnsafeStateDirectory
            | FinalUseError::StateLocked,
        ) => true,
        _ => false,
    }
}

fn learning_error(error: AgentdIntelligenceLearningErrorV1) -> AgentdError {
    AgentdError::Protocol(format!(
        "intelligence learning reconciliation failed: {error}"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn learning_runtime_policy_is_bounded() {
        assert!(validate_runtime_policy(Duration::from_millis(10), 1).is_ok());
        assert!(validate_runtime_policy(Duration::from_secs(3600), 256).is_ok());
        assert!(validate_runtime_policy(Duration::ZERO, 1).is_err());
        assert!(validate_runtime_policy(Duration::from_millis(9), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(3601), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 0).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 257).is_err());
    }

    #[test]
    fn single_slot_cycles_alternate_without_starvation() {
        let mut reconcile_turn = true;
        assert_eq!(
            cycle_budget(1, &mut reconcile_turn),
            CycleBudget {
                reconcile: 1,
                dispatch: 0
            }
        );
        assert_eq!(
            cycle_budget(1, &mut reconcile_turn),
            CycleBudget {
                reconcile: 0,
                dispatch: 1
            }
        );
        assert_eq!(
            cycle_budget(1, &mut reconcile_turn),
            CycleBudget {
                reconcile: 1,
                dispatch: 0
            }
        );
    }

    #[test]
    fn multi_slot_cycles_reserve_both_classes() {
        let mut reconcile_turn = true;
        for batch in 2..=MAX_RECONCILE_BATCH {
            let budget = cycle_budget(batch, &mut reconcile_turn);
            assert!(budget.reconcile > 0);
            assert!(budget.dispatch > 0);
            assert_eq!(budget.reconcile + budget.dispatch, batch);
        }
    }

    #[test]
    fn temporary_capacity_and_io_failures_remain_retryable() {
        assert!(retryable_learning_error(
            &AgentdIntelligenceLearningErrorV1::Operation(DurableOperationError::Capacity)
        ));
        assert!(retryable_learning_error(
            &AgentdIntelligenceLearningErrorV1::Agentd(AgentdError::Overloaded {
                retry_after_ms: 10
            })
        ));
        assert!(retryable_learning_error(
            &AgentdIntelligenceLearningErrorV1::Io("temporary".to_string())
        ));
    }

    #[test]
    fn runtime_validation_clock_is_nonzero() {
        assert!(current_validation_time().expect("clock") > 0);
    }
}
