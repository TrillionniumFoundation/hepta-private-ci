//! Independently supervised owner inputs for the canonical intelligence product loop.
//!
//! The wrapped owner still owns signed Decision/Outcome evidence and physical
//! prompt/context construction. Each owner future executes on a dedicated
//! bounded thread using the current Tokio runtime handle. Request timeout drops
//! only the receiver: the physical worker and its reservation remain alive until
//! the owner future really completes or panics.

use std::panic::AssertUnwindSafe;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdIntelligenceLearningHostV1;
use codex_hepta_agentd::PreparedAgentdIntelligenceRunV1;
use codex_hepta_agentd::RunReceipt;
use codex_hepta_agentd::intelligence_run_snapshot_digest_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::runtime::Handle;
use tokio::sync::oneshot;
use tokio::time::timeout;

use crate::native_app_server::AppServerModelDriver;
use crate::native_app_server::NativeRunOutput;

use super::CanonicalIntelligenceOutcomeFuture;
use super::CanonicalIntelligencePhysicalRequestFuture;
use super::CanonicalIntelligenceProductLoopOwnerV1;
use super::CanonicalIntelligenceProductLoopV1;

const MAX_OWNER_WORKERS: usize = 64;
const MAX_OWNER_BUDGET: Duration = Duration::from_secs(30);
const MAX_NATIVE_IN_FLIGHT: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalIntelligenceOwnerSupervisorPolicyV1 {
    pub budget: Duration,
    pub maximum_workers: usize,
}

impl CanonicalIntelligenceOwnerSupervisorPolicyV1 {
    pub fn new(budget: Duration, maximum_workers: usize) -> Result<Self, AgentdError> {
        if budget.is_zero()
            || budget > MAX_OWNER_BUDGET
            || maximum_workers == 0
            || maximum_workers > MAX_OWNER_WORKERS
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence owner supervisor policy is out of bounds".to_string(),
            ));
        }
        Ok(Self {
            budget,
            maximum_workers,
        })
    }
}

struct OwnerWorkerReservation {
    active_workers: Arc<AtomicUsize>,
}

impl Drop for OwnerWorkerReservation {
    fn drop(&mut self) {
        self.active_workers.fetch_sub(1, Ordering::AcqRel);
    }
}

pub struct SupervisedCanonicalIntelligenceProductLoopOwnerV1 {
    inner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1>,
    policy: CanonicalIntelligenceOwnerSupervisorPolicyV1,
    active_workers: Arc<AtomicUsize>,
}

impl SupervisedCanonicalIntelligenceProductLoopOwnerV1 {
    pub fn new(
        inner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1>,
        policy: CanonicalIntelligenceOwnerSupervisorPolicyV1,
    ) -> Self {
        Self {
            inner,
            policy,
            active_workers: Arc::new(AtomicUsize::new(0)),
        }
    }

    fn acquire_worker(&self) -> Result<OwnerWorkerReservation, AgentdError> {
        let mut observed = self.active_workers.load(Ordering::Acquire);
        loop {
            if observed >= self.policy.maximum_workers {
                return Err(AgentdError::Overloaded {
                    retry_after_ms: duration_millis(self.policy.budget),
                });
            }
            match self.active_workers.compare_exchange_weak(
                observed,
                observed + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(OwnerWorkerReservation {
                        active_workers: Arc::clone(&self.active_workers),
                    });
                }
                Err(actual) => observed = actual,
            }
        }
    }
}

impl CanonicalIntelligenceProductLoopOwnerV1
    for SupervisedCanonicalIntelligenceProductLoopOwnerV1
{
    fn prepare_physical_request<'a>(
        &'a self,
        prepared: &'a PreparedAgentdIntelligenceRunV1,
        attached: &'a RunReceipt,
    ) -> CanonicalIntelligencePhysicalRequestFuture<'a> {
        Box::pin(async move {
            let reservation = self.acquire_worker()?;
            let runtime = Handle::try_current().map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence owner supervisor requires a Tokio runtime"
                        .to_string(),
                )
            })?;
            let inner = Arc::clone(&self.inner);
            let owned_prepared = prepared.clone();
            let owned_attached = attached.clone();
            let (sender, receiver) = oneshot::channel();
            std::thread::Builder::new()
                .name("intelligence-product-owner-input".to_string())
                .spawn(move || {
                    let _reservation = reservation;
                    let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
                        runtime.block_on(
                            inner.prepare_physical_request(&owned_prepared, &owned_attached),
                        )
                    }))
                    .unwrap_or_else(|_| {
                        Err(AgentdError::Protocol(
                            "canonical intelligence physical-request owner panicked".to_string(),
                        ))
                    });
                    let _ = sender.send(result);
                })
                .map_err(AgentdError::Io)?;

            let mut request = receive_owner_result(receiver, self.policy.budget).await?;
            if request.admission.maximum_in_flight == 0
                || request.admission.maximum_in_flight > MAX_NATIVE_IN_FLIGHT
            {
                return Err(AgentdError::Invalid(
                    "canonical intelligence native admission is out of bounds".to_string(),
                ));
            }
            request.admission.request_id = canonical_native_request_id_v1(
                &prepared.run_snapshot().run_id,
                intelligence_run_snapshot_digest_v1(prepared).map_err(|error| {
                    AgentdError::Protocol(format!(
                        "canonical intelligence snapshot identity: {error}"
                    ))
                })?,
                prepared.envelope.decision.decision_digest,
                &request.decision.episode_id,
            )?;
            Ok(request)
        })
    }

    fn build_terminal_outcome<'a>(
        &'a self,
        prepared: &'a PreparedAgentdIntelligenceRunV1,
        terminal: &'a RunReceipt,
        output: &'a NativeRunOutput,
        provider_terminal_digest: Digest32,
    ) -> CanonicalIntelligenceOutcomeFuture<'a> {
        Box::pin(async move {
            let reservation = self.acquire_worker()?;
            let runtime = Handle::try_current().map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence owner supervisor requires a Tokio runtime"
                        .to_string(),
                )
            })?;
            let inner = Arc::clone(&self.inner);
            let owned_prepared = prepared.clone();
            let owned_terminal = terminal.clone();
            let owned_output = output.clone();
            let (sender, receiver) = oneshot::channel();
            std::thread::Builder::new()
                .name("intelligence-product-owner-outcome".to_string())
                .spawn(move || {
                    let _reservation = reservation;
                    let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
                        runtime.block_on(inner.build_terminal_outcome(
                            &owned_prepared,
                            &owned_terminal,
                            &owned_output,
                            provider_terminal_digest,
                        ))
                    }))
                    .unwrap_or_else(|_| {
                        Err(AgentdError::Protocol(
                            "canonical intelligence terminal-outcome owner panicked".to_string(),
                        ))
                    });
                    let _ = sender.send(result);
                })
                .map_err(AgentdError::Io)?;
            receive_owner_result(receiver, self.policy.budget).await
        })
    }
}

impl CanonicalIntelligenceProductLoopV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new_supervised(
        driver: Arc<AppServerModelDriver>,
        control: DurableInferenceControl,
        learning: Arc<AgentdIntelligenceLearningHostV1>,
        owner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1>,
        agentd_socket: PathBuf,
        agent_id: AgentId,
        spawn_generation: u64,
        settlement_steps: u32,
        owner_policy: CanonicalIntelligenceOwnerSupervisorPolicyV1,
        maximum_concurrent_loops: usize,
    ) -> Result<Self, AgentdError> {
        let budget = owner_policy.budget;
        let owner: Arc<dyn CanonicalIntelligenceProductLoopOwnerV1> = Arc::new(
            SupervisedCanonicalIntelligenceProductLoopOwnerV1::new(owner, owner_policy),
        );
        Self::new(
            driver,
            control,
            learning,
            owner,
            agentd_socket,
            agent_id,
            spawn_generation,
            settlement_steps,
            budget,
            maximum_concurrent_loops,
        )
    }
}

async fn receive_owner_result<T>(
    receiver: oneshot::Receiver<Result<T, AgentdError>>,
    budget: Duration,
) -> Result<T, AgentdError> {
    match timeout(budget, receiver).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => Err(AgentdError::Protocol(
            "canonical intelligence owner worker terminated without a result".to_string(),
        )),
        Err(_) => Err(AgentdError::Overloaded {
            retry_after_ms: duration_millis(budget),
        }),
    }
}

fn canonical_native_request_id_v1(
    run_id: &str,
    run_snapshot_digest: Digest32,
    decision_digest: Digest32,
    episode_id: &StableId,
) -> Result<String, AgentdError> {
    if run_id.is_empty() || run_snapshot_digest.is_zero() || decision_digest.is_zero() {
        return Err(AgentdError::Invalid(
            "canonical intelligence native request identity is incomplete".to_string(),
        ));
    }
    let mut bytes = b"hepta.intelligence.native-request.v1\0".to_vec();
    push_string(&mut bytes, run_id)?;
    bytes.extend_from_slice(run_snapshot_digest.as_array());
    bytes.extend_from_slice(decision_digest.as_array());
    push_string(&mut bytes, episode_id.as_str())?;
    Ok(format!("intelligence:{}", Digest32::of_bytes(&bytes)))
}

fn push_string(bytes: &mut Vec<u8>, value: &str) -> Result<(), AgentdError> {
    let length = u32::try_from(value.len())
        .map_err(|_| AgentdError::Invalid("canonical identity length".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

fn duration_millis(value: Duration) -> u64 {
    u64::try_from(value.as_millis()).unwrap_or(u64::MAX).max(1)
}

#[cfg(test)]
mod tests {
    use std::sync::Barrier;

    use super::*;

    struct NeverCalledOwner;

    impl CanonicalIntelligenceProductLoopOwnerV1 for NeverCalledOwner {
        fn prepare_physical_request<'a>(
            &'a self,
            _prepared: &'a PreparedAgentdIntelligenceRunV1,
            _attached: &'a RunReceipt,
        ) -> CanonicalIntelligencePhysicalRequestFuture<'a> {
            Box::pin(async {
                Err(AgentdError::Protocol(
                    "not called in reservation tests".to_string(),
                ))
            })
        }

        fn build_terminal_outcome<'a>(
            &'a self,
            _prepared: &'a PreparedAgentdIntelligenceRunV1,
            _terminal: &'a RunReceipt,
            _output: &'a NativeRunOutput,
            _provider_terminal_digest: Digest32,
        ) -> CanonicalIntelligenceOutcomeFuture<'a> {
            Box::pin(async {
                Err(AgentdError::Protocol(
                    "not called in reservation tests".to_string(),
                ))
            })
        }
    }

    fn supervisor() -> SupervisedCanonicalIntelligenceProductLoopOwnerV1 {
        SupervisedCanonicalIntelligenceProductLoopOwnerV1::new(
            Arc::new(NeverCalledOwner),
            CanonicalIntelligenceOwnerSupervisorPolicyV1::new(
                Duration::from_millis(10),
                1,
            )
            .expect("policy"),
        )
    }

    #[test]
    fn owner_worker_reservation_lives_until_physical_exit() {
        let supervisor = supervisor();
        let reservation = supervisor.acquire_worker().expect("first reservation");
        let barrier = Arc::new(Barrier::new(2));
        let worker_barrier = Arc::clone(&barrier);
        let worker = std::thread::spawn(move || {
            let _reservation = reservation;
            worker_barrier.wait();
            std::thread::sleep(Duration::from_millis(20));
        });
        barrier.wait();
        assert!(matches!(
            supervisor.acquire_worker(),
            Err(AgentdError::Overloaded { .. })
        ));
        worker.join().expect("worker exit");
        drop(supervisor.acquire_worker().expect("reservation released"));
    }

    #[test]
    fn owner_worker_panic_releases_reservation() {
        let supervisor = supervisor();
        let reservation = supervisor.acquire_worker().expect("first reservation");
        let worker = std::thread::spawn(move || {
            let _reservation = reservation;
            panic!("expected test panic");
        });
        assert!(worker.join().is_err());
        drop(supervisor.acquire_worker().expect("reservation released"));
    }

    #[test]
    fn physical_request_identity_is_stable_and_run_bound() {
        let snapshot = Digest32::of_bytes(b"snapshot");
        let decision = Digest32::of_bytes(b"decision");
        let episode = StableId::new("episode.test").expect("episode");
        let first = canonical_native_request_id_v1("run.a", snapshot, decision, &episode)
            .expect("first identity");
        assert_eq!(
            first,
            canonical_native_request_id_v1("run.a", snapshot, decision, &episode)
                .expect("repeat identity")
        );
        assert_ne!(
            first,
            canonical_native_request_id_v1("run.b", snapshot, decision, &episode)
                .expect("different run")
        );
    }
}
