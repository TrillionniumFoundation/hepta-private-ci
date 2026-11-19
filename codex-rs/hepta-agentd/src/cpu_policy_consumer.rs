//! One retained proposal at the original synchronous HOS2 consumer entry.
//! This bounded, process-local slot owns no K/D, grant or durable outcome.

use crate::AgentdHos2Device;
use crate::CpuBudgetProposal;
use crate::CpuPolicyError;
use codex_hepta_memory::Hos2InstallAdmission;
use codex_hepta_memory::Hos2InstallBudgetV1;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

struct Pending {
    proposal: CpuBudgetProposal,
    request: Hos2InstallBudgetV1,
}

/// Required admission for a policy-enabled original HOS2 target. The clock
/// must be the embedding's trusted CLOCK_BOOTTIME source, never a model value.
/// Attach this to `ProductionHos2Target::with_admission` before exposing the
/// host; a missing proposal then always refuses entry, including after restart.
pub struct CpuPolicyConsumer {
    native: Arc<AgentdHos2Device>,
    now_boottime: Arc<dyn Fn() -> Result<u64, String> + Send + Sync>,
    pending: Mutex<Option<Pending>>,
    lost_events: AtomicBool,
}

impl CpuPolicyConsumer {
    pub fn new(
        native: Arc<AgentdHos2Device>,
        now_boottime: Arc<dyn Fn() -> Result<u64, String> + Send + Sync>,
    ) -> Self {
        Self {
            native,
            now_boottime,
            pending: Mutex::new(None),
            lost_events: AtomicBool::new(false),
        }
    }

    /// Recheck the original proposal and retain its exact immutable request.
    /// The sequence comes from the original durable writer. Keep the returned
    /// handle through preparation, grant waits and dispatch; dropping it only
    /// removes local admission and never settles or retries the original K/D.
    pub fn prepare(
        self: &Arc<Self>,
        proposal: CpuBudgetProposal,
        sequence: u64,
    ) -> Result<CpuPolicySubmission, CpuPolicyError> {
        let mut pending = self.pending.try_lock().map_err(|_| CpuPolicyError::Busy)?;
        if pending.is_some() {
            return Err(CpuPolicyError::Busy);
        }
        if self.lost_events.load(Ordering::Acquire) {
            return Err(CpuPolicyError::EventLoss);
        }
        let current = self
            .native
            .read_usage(u64::MAX)
            .map_err(CpuPolicyError::Native)?;
        // Latch actual event loss before the clock or any other validation can
        // fail. A stale sample or failed clock must not hide an observed loss.
        if current.dropped_events != 0 {
            self.lost_events.store(true, Ordering::Release);
            return Err(CpuPolicyError::EventLoss);
        }
        let now = (self.now_boottime)().map_err(CpuPolicyError::Native)?;
        proposal.revalidate(&current, now)?;
        let request = self
            .native
            .install_request(sequence, current.revision, proposal.cap_ns())
            .map_err(CpuPolicyError::Native)?;
        *pending = Some(Pending {
            proposal,
            request: request.clone(),
        });
        Ok(CpuPolicySubmission {
            consumer: Arc::clone(self),
            request,
        })
    }
}

impl Hos2InstallAdmission for CpuPolicyConsumer {
    fn check(&self, request: &Hos2InstallBudgetV1) -> Result<(), String> {
        if self.lost_events.load(Ordering::Acquire) {
            return Err(CpuPolicyError::EventLoss.to_string());
        }
        let pending = self
            .pending
            .try_lock()
            .map_err(|_| "CPU policy admission is busy or poisoned".to_string())?;
        let pending = pending
            .as_ref()
            .ok_or("original CPU policy proposal is no longer retained")?;
        if &pending.request != request {
            return Err("CPU policy proposal differs from the immutable original request".into());
        }
        // Both the real native observation and the trusted clock are sampled
        // here, after all grant/queue awaits. ReadUsage has no install effect;
        // a failed read is still a definite refusal before InstallBudget.
        let current = self.native.read_usage(u64::MAX)?;
        if current.dropped_events != 0 {
            self.lost_events.store(true, Ordering::Release);
        }
        let now = (self.now_boottime)()?;
        pending
            .proposal
            .revalidate(&current, now)
            .map_err(|error| error.to_string())
    }
}

/// Non-cloneable, non-serializable lifetime of one policy admission. This
/// handle is not a grant or durable receipt, and cannot revive after restart.
pub struct CpuPolicySubmission {
    consumer: Arc<CpuPolicyConsumer>,
    request: Hos2InstallBudgetV1,
}

impl CpuPolicySubmission {
    pub fn request(&self) -> &Hos2InstallBudgetV1 {
        &self.request
    }
}

impl Drop for CpuPolicySubmission {
    fn drop(&mut self) {
        if let Ok(mut pending) = self.consumer.pending.lock()
            && pending
                .as_ref()
                .is_some_and(|value| value.request == self.request)
        {
            *pending = None;
        }
    }
}
