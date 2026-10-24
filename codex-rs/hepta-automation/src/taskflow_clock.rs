//! Live proof of a new TaskFlow lease claimed through its original authority clock.
//!
//! This handle is neither serializable nor reconstructible from a run row. It
//! grants no effect authority. Existing-key recovery does not require it.

use codex_hepta_contracts::FinalUseAuthority;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowRun;

/// An original-store claim tied to one live FinalUseAuthority clock instance.
///
/// Only a newly committed lease from an owner-cleared/no-lease run can produce
/// this value. Every pre-existing lease is refused, including after restart:
/// its numeric expiry does not prove it used this clock. A cold owner may
/// reconcile existing effects, but fresh dispatch needs a legitimate new or
/// original-owner-cleared claim path. There is no timestamp-based fallback.
/// This is live provenance, not persisted clock attestation or a new grant.
pub struct TaskFlowClockClaim<'owner> {
    pub(crate) store: &'owner AutomationStore,
    pub(crate) authority: &'owner FinalUseAuthority,
    pub(crate) binding: ClockClaimBinding,
}

pub(crate) struct ClockClaimBinding {
    pub(crate) run: TaskFlowRun,
    pub(crate) fence: TaskFlowFence,
    pub(crate) expires_at_unix_ms: u64,
}

impl TaskFlowClockClaim<'_> {
    /// Immutable receipt of the newly committed original lease claim.
    pub fn run(&self) -> &TaskFlowRun {
        &self.binding.run
    }

    pub fn fence(&self) -> &TaskFlowFence {
        &self.binding.fence
    }

    pub fn expires_at_unix_ms(&self) -> u64 {
        self.binding.expires_at_unix_ms
    }
}

impl AutomationStore {
    /// Claim a NEW lease using the existing FinalUseAuthority's clock.
    ///
    /// The authority must be the host's already configured owner. No clock,
    /// signer, nonce, frontier or fallback is created here. Its trust remains
    /// the supplied owner's trust: a compatibility system clock is not made
    /// protected by this API. Ordinary logical-time claim APIs stay unchanged.
    pub async fn claim_taskflow_run_with_authority_clock<'owner>(
        &'owner self,
        authority: &'owner FinalUseAuthority,
        run_id: &str,
        fence: &TaskFlowFence,
        lease_duration_ms: u64,
    ) -> Result<TaskFlowClockClaim<'owner>, TaskFlowError> {
        let run = self
            .claim_taskflow_run_with_time(
                run_id,
                fence,
                TaskFlowClaimTime::Authority(authority),
                lease_duration_ms,
            )
            .await?;
        let expires_at_unix_ms = run.lease_expires_at_ms.ok_or_else(|| {
            TaskFlowError::Corrupt("new clock claim has no lease deadline".into())
        })?;
        // Claim persistence may itself outlast the new lease. The committed
        // lease remains evidence; do not return a stale live claim or undo it.
        let now = owner_time(authority)?;
        if now < run.updated_at_ms || now >= expires_at_unix_ms {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(TaskFlowClockClaim {
            store: self,
            authority,
            binding: ClockClaimBinding {
                run,
                fence: fence.clone(),
                expires_at_unix_ms,
            },
        })
    }
}

#[derive(Clone, Copy)]
pub(crate) enum TaskFlowClaimTime<'a> {
    Caller(u64),
    Authority(&'a FinalUseAuthority),
}

impl TaskFlowClaimTime<'_> {
    pub(crate) fn new_claim_required(self) -> bool {
        matches!(self, Self::Authority(_))
    }

    pub(crate) fn observe(self) -> Result<u64, TaskFlowError> {
        match self {
            Self::Caller(now) => Ok(now),
            Self::Authority(authority) => owner_time(authority),
        }
    }

    pub(crate) fn observe_after(self, previous: u64) -> Result<u64, TaskFlowError> {
        let now = self.observe()?;
        if now < previous {
            return Err(TaskFlowError::Unavailable);
        }
        Ok(now)
    }
}

pub(crate) fn owner_time(authority: &FinalUseAuthority) -> Result<u64, TaskFlowError> {
    authority
        .observe_now_unix_ms()
        .map_err(|_| TaskFlowError::Unavailable)
}

/// Lease clearing removes the projection tuple, not its immutable history.
/// Match the original event-chain verifier's strictly advancing generation
/// invariant before the new typed path can append another lease_claimed event.
pub(crate) async fn validate_next_generation(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    run_id: &str,
    fence: &TaskFlowFence,
) -> Result<(), TaskFlowError> {
    let previous: Option<(i64, i64)> = sqlx::query_as(
        "SELECT owner_epoch, generation FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ? AND transition = 'lease_claimed'
         ORDER BY event_seq DESC LIMIT 1",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(run_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    if let Some((epoch, generation)) = previous {
        let epoch =
            u64::try_from(epoch).map_err(|_| TaskFlowError::Corrupt("lease epoch".into()))?;
        let generation = u64::try_from(generation)
            .map_err(|_| TaskFlowError::Corrupt("lease generation".into()))?;
        if epoch == 0 || generation == 0 {
            return Err(TaskFlowError::Corrupt("zero lease history identity".into()));
        }
        if fence.owner_epoch < epoch || fence.generation <= generation {
            return Err(TaskFlowError::StaleFence);
        }
    }
    Ok(())
}
