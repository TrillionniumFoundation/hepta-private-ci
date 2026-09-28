//! Panic-safe bounded host invocation provider for canonical intelligence.
//!
//! This is the product composer selected provider. The historical V1 provider
//! remains source compatible, while this implementation owns a physical worker
//! reservation whose `Drop` runs on normal return, panic, channel loss, or
//! thread-spawn failure. A timed-out factory keeps that reservation until its
//! synchronous work really exits.

use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc::RecvTimeoutError;
use std::sync::mpsc::sync_channel;
use std::time::Duration;

use codex_hepta_learning_ledger::RunStartRecordV1;

use crate::AgentdError;
use crate::AgentdIdentity;

use super::AgentdIntelligenceInvocationProviderV1;
use super::AgentdIntelligenceInvocationV1;
use super::AgentdIntelligenceProductContinuationV1;
use super::AgentdIntelligenceRunIdentityV1;

const DEFAULT_FACTORY_BUDGET: Duration = Duration::from_millis(250);
const MAX_FACTORY_BUDGET: Duration = Duration::from_secs(30);
const DEFAULT_FACTORY_WORKERS: usize = 4;
const MAX_FACTORY_WORKERS: usize = 64;

struct InvocationWorkerReservation {
    active_workers: Arc<AtomicUsize>,
}

impl Drop for InvocationWorkerReservation {
    fn drop(&mut self) {
        self.active_workers.fetch_sub(1, Ordering::AcqRel);
    }
}

pub struct SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    factory: Arc<F>,
    budget: Duration,
    active_workers: Arc<AtomicUsize>,
    max_workers: usize,
    continuation: Option<Arc<dyn AgentdIntelligenceProductContinuationV1>>,
}

impl<F> SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    #[must_use]
    pub fn new(factory: F) -> Self {
        Self {
            factory: Arc::new(factory),
            budget: DEFAULT_FACTORY_BUDGET,
            active_workers: Arc::new(AtomicUsize::new(0)),
            max_workers: DEFAULT_FACTORY_WORKERS,
            continuation: None,
        }
    }

    pub fn with_worker_policy(
        mut self,
        budget: Duration,
        max_workers: usize,
    ) -> Result<Self, AgentdError> {
        if budget.is_zero()
            || budget > MAX_FACTORY_BUDGET
            || max_workers == 0
            || max_workers > MAX_FACTORY_WORKERS
        {
            return Err(AgentdError::Invalid(
                "intelligence invocation factory policy is out of bounds".to_string(),
            ));
        }
        self.budget = budget;
        self.max_workers = max_workers;
        Ok(self)
    }

    pub fn with_product_continuation(
        mut self,
        continuation: Arc<dyn AgentdIntelligenceProductContinuationV1>,
    ) -> Result<Self, AgentdError> {
        if self.continuation.is_some() {
            return Err(AgentdError::Invalid(
                "intelligence product continuation already configured".to_string(),
            ));
        }
        self.continuation = Some(continuation);
        Ok(self)
    }

    fn acquire_worker(&self) -> Result<InvocationWorkerReservation, AgentdError> {
        let mut observed = self.active_workers.load(Ordering::Acquire);
        loop {
            if observed >= self.max_workers {
                return Err(AgentdError::Overloaded {
                    retry_after_ms: duration_millis(self.budget),
                });
            }
            match self.active_workers.compare_exchange_weak(
                observed,
                observed + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(InvocationWorkerReservation {
                        active_workers: Arc::clone(&self.active_workers),
                    });
                }
                Err(actual) => observed = actual,
            }
        }
    }
}

impl<F> AgentdIntelligenceInvocationProviderV1
    for SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1<F>
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send
        + Sync
        + 'static,
{
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let reservation = self.acquire_worker()?;
        let factory = Arc::clone(&self.factory);
        let identity = identity.clone();
        let record = record.clone();
        let (sender, receiver) = sync_channel(1);
        std::thread::Builder::new()
            .name("agentd-intelligence-invocation".to_string())
            .spawn(move || {
                let _reservation = reservation;
                let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
                    (factory)(&identity, &record)
                }))
                .unwrap_or_else(|_| {
                    Err(AgentdError::Protocol(
                        "intelligence invocation factory panicked".to_string(),
                    ))
                });
                let _ = sender.send(result);
            })
            .map_err(AgentdError::Io)?;

        let mut invocation = match receiver.recv_timeout(self.budget) {
            Ok(result) => result?,
            Err(RecvTimeoutError::Timeout) => {
                return Err(AgentdError::Overloaded {
                    retry_after_ms: duration_millis(self.budget),
                });
            }
            Err(RecvTimeoutError::Disconnected) => {
                return Err(AgentdError::Protocol(
                    "intelligence invocation factory worker terminated without a result"
                        .to_string(),
                ));
            }
        };
        invocation.inputs.run_identity = Some(AgentdIntelligenceRunIdentityV1::from_run_start(
            &identity, &record,
        )?);
        invocation.validate(&identity, &record)?;
        Ok(invocation)
    }

    fn product_continuation(
        &self,
    ) -> Option<Arc<dyn AgentdIntelligenceProductContinuationV1>> {
        self.continuation.clone()
    }
}

fn duration_millis(value: Duration) -> u64 {
    u64::try_from(value.as_millis()).unwrap_or(u64::MAX).max(1)
}

#[cfg(test)]
mod tests {
    use std::sync::Barrier;

    use super::*;

    fn provider() -> SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1<
        impl Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>,
    > {
        SupervisedHostOwnedAgentdIntelligenceInvocationProviderV1::new(
            |_: &AgentdIdentity,
             _: &RunStartRecordV1|
             -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
                unreachable!("reservation tests do not invoke the factory")
            },
        )
        .with_worker_policy(Duration::from_millis(10), 1)
        .expect("bounded policy")
    }

    #[test]
    fn physical_worker_reservation_survives_until_thread_exit() {
        let provider = provider();
        let reservation = provider.acquire_worker().expect("first reservation");
        let barrier = Arc::new(Barrier::new(2));
        let worker_barrier = Arc::clone(&barrier);
        let worker = std::thread::spawn(move || {
            let _reservation = reservation;
            worker_barrier.wait();
            std::thread::sleep(Duration::from_millis(20));
        });
        barrier.wait();
        assert!(matches!(
            provider.acquire_worker(),
            Err(AgentdError::Overloaded { .. })
        ));
        worker.join().expect("worker exit");
        drop(provider.acquire_worker().expect("reservation released"));
    }

    #[test]
    fn panicking_worker_releases_its_reservation() {
        let provider = provider();
        let reservation = provider.acquire_worker().expect("first reservation");
        let worker = std::thread::spawn(move || {
            let _reservation = reservation;
            panic!("expected test panic");
        });
        assert!(worker.join().is_err());
        drop(provider.acquire_worker().expect("reservation released"));
    }
}
