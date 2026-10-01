//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use std::panic::AssertUnwindSafe;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;

/// Exact durable RunStart identity inherited by the prepared intelligence run.
///
/// The request digest is a domain-separated digest of the complete immutable
/// RunStart publication, not a digest reconstructed by the cognition runner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRunIdentityV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub objective_digest: Digest32,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub authority_epoch: u64,
    pub generation: u64,
    pub fence_digest: Digest32,
    pub deadline_ms: u64,
}

impl AgentdIntelligenceRunIdentityV1 {
    /// Derive the only accepted physical-run identity from the durable record.
    pub fn from_run_start(
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<Self, AgentdError> {
        if record.disposition != RunStartObjectiveDispositionV1::Compiled
            || record.admission.authority.grants_any()
            || record.snapshot.objective_digest.is_zero()
            || record.runtime_body_digest.is_zero()
            || record.snapshot.artifact_set_digest.is_zero()
            || record.snapshot.authority_epoch == 0
            || record.snapshot.generation == 0
            || record.objective_semantic_bytes.is_empty()
            || record.objective_function_v1_bytes.is_empty()
            || record.objective_function_v1_digest.is_zero()
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence requires one complete deny-all compiled RunStart"
                    .to_string(),
            ));
        }
        let running_generation = identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))?;
        if record.snapshot.generation != running_generation {
            return Err(AgentdError::GenerationFenced(format!(
                "canonical intelligence RunStart generation {} does not match Running generation {running_generation}",
                record.snapshot.generation
            )));
        }
        let expected_fence = objective_run_fence_digest_v1(
            identity.agent_id.as_str(),
            identity.spawn_generation,
            record.snapshot.generation,
        );
        if record.snapshot.fence_digest != expected_fence {
            return Err(AgentdError::GenerationFenced(
                "canonical intelligence RunStart fence does not match agent process identity"
                    .to_string(),
            ));
        }
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .filter(|value| *value != 0)
            .ok_or_else(|| AgentdError::Invalid("RunStart deadline overflow".to_string()))?;
        Ok(Self {
            run_id: record.snapshot.run_id.clone(),
            request_digest: run_start_identity_digest_v1(record)?,
            objective_digest: record.snapshot.objective_digest,
            body_digest: record.runtime_body_digest,
            artifact_set_digest: record.snapshot.artifact_set_digest,
            authority_epoch: record.snapshot.authority_epoch,
            generation: record.snapshot.generation,
            fence_digest: record.snapshot.fence_digest,
            deadline_ms,
        })
    }

    pub(crate) fn validate_process_binding(
        &self,
        agent_id: &str,
        spawn_generation: u64,
    ) -> Result<(), AgentdError> {
        let running_generation = spawn_generation
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid("agent generation overflow".to_string()))?;
        if self.generation != running_generation
            || self.fence_digest
                != objective_run_fence_digest_v1(agent_id, spawn_generation, self.generation)
        {
            return Err(AgentdError::GenerationFenced(
                "prepared intelligence run is not bound to this Agentd generation".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) fn validate_request(
        &self,
        request: &CanonicalIntelligenceRunRequestV1,
    ) -> Result<(), AgentdError> {
        if self.run_id != request.run_id
            || self.objective_digest != request.snapshot.objective_digest()
            || self.authority_epoch != request.snapshot.authority_epoch()
            || self.generation != request.snapshot.body_generation().get()
            || self.objective_digest != request.legal_candidates.state_digest
        {
            return Err(AgentdError::Invalid(
                "canonical request does not inherit its durable RunStart identity".to_string(),
            ));
        }
        Ok(())
    }
}

/// One canonical fence algorithm for ObjectiveStart publication, invocation
/// validation, runner preparation and coordinator-bound admission.
#[must_use]
pub fn objective_run_fence_digest_v1(
    agent_id: &str,
    spawn_generation: u64,
    current_generation: u64,
) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(agent_id.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn run_start_identity_digest_v1(record: &RunStartRecordV1) -> Result<Digest32, AgentdError> {
    let mut bytes = b"hepta.agentd.intelligence-run-start-identity.v1\0".to_vec();
    push_id(&mut bytes, &record.authentication.issuer_id)?;
    bytes.extend_from_slice(&record.authentication.key_epoch.to_be_bytes());
    push_id(&mut bytes, &record.authentication.message_id)?;
    bytes.extend_from_slice(&record.authentication.sequence.to_be_bytes());
    bytes.extend_from_slice(&record.authentication.expires_at_ms.to_be_bytes());
    bytes.extend_from_slice(record.authentication.scope_digest.as_array());
    bytes.extend_from_slice(record.authentication.signed_body_digest.as_array());
    bytes.extend_from_slice(&record.authentication.signature);

    push_id(&mut bytes, &record.admission.profile_id)?;
    bytes.extend_from_slice(&record.admission.profile_revision.to_be_bytes());
    for digest in [
        record.admission.profile_digest,
        record.admission.supplied_source_digest,
        record.admission.intent_digest,
        record.admission.admitted_source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&record.admission.observed_at_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&record.admission.deadline_unix_micros.to_be_bytes());

    push_id(&mut bytes, &record.snapshot.run_id)?;
    for digest in [
        record.snapshot.objective_digest,
        record.snapshot.hard_constraint_digest,
        record.snapshot.preference_state_digest,
        record.snapshot.model_tuple_digest,
        record.snapshot.prompt_registry_digest,
        record.snapshot.artifact_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&record.snapshot.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&record.snapshot.generation.to_be_bytes());
    bytes.extend_from_slice(record.snapshot.fence_digest.as_array());
    bytes.extend_from_slice(record.runtime_body_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&record.objective_semantic_bytes).as_array());
    bytes.extend_from_slice(record.objective_function_v1_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&record.objective_function_v1_bytes).as_array());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), AgentdError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| AgentdError::Invalid("stable identity is too large".to_string()))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

pub struct AgentdIntelligenceInvocationV1 {
    pub request: CanonicalIntelligenceRunRequestV1,
    pub inputs: AgentdIntelligenceOwnerInputsV1,
}

impl AgentdIntelligenceInvocationV1 {
    pub(crate) fn validate(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<(), AgentdError> {
        let expected = AgentdIntelligenceRunIdentityV1::from_run_start(identity, record)?;
        let Some(actual) = self.inputs.run_identity.as_ref() else {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation omitted durable RunStart identity".to_string(),
            ));
        };
        if actual != &expected {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation substituted durable RunStart identity"
                    .to_string(),
            ));
        }
        actual.validate_request(&self.request)
    }
}

const MIN_INVOCATION_TIMEOUT: Duration = Duration::from_millis(1);
const MAX_INVOCATION_TIMEOUT: Duration = Duration::from_secs(300);
const MAX_INVOCATION_FACTORY_CALLS: usize = 64;
const DEFAULT_INVOCATION_FACTORY_CALLS: usize = 4;
const DEFAULT_INVOCATION_TIMEOUT: Duration = Duration::from_secs(30);

/// Bounded execution policy for the host-owned seven-owner invocation factory.
///
/// Standalone `build` runs the factory on a dedicated OS thread with this
/// policy's optional process-exit observer. Canonical invocation executes the
/// factory directly in the runner's supervised worker, using the shorter
/// configured timeout and process-exit grace from the provider and runner.
/// A timed-out call keeps its slot until actual work finishes; dropping the
/// ObjectiveStart future cannot free capacity or disarm its observer. A missing
/// provider grace never disables the canonical runner's required process fence.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceInvocationPolicyV1 {
    pub timeout: Duration,
    pub max_in_flight: usize,
    pub hard_timeout_process_exit_grace: Option<Duration>,
}

impl Default for AgentdIntelligenceInvocationPolicyV1 {
    fn default() -> Self {
        Self {
            timeout: DEFAULT_INVOCATION_TIMEOUT,
            max_in_flight: DEFAULT_INVOCATION_FACTORY_CALLS,
            hard_timeout_process_exit_grace: None,
        }
    }
}

impl AgentdIntelligenceInvocationPolicyV1 {
    fn validate(self) -> Result<(), AgentdError> {
        if !(MIN_INVOCATION_TIMEOUT..=MAX_INVOCATION_TIMEOUT).contains(&self.timeout)
            || !(1..=MAX_INVOCATION_FACTORY_CALLS).contains(&self.max_in_flight)
            || self.hard_timeout_process_exit_grace.is_some_and(|grace| {
                !(MIN_INVOCATION_TIMEOUT..=MAX_INVOCATION_TIMEOUT).contains(&grace)
            })
        {
            return Err(AgentdError::Invalid(
                "canonical intelligence invocation policy is outside bounded limits".to_string(),
            ));
        }
        Ok(())
    }
}

struct InvocationFactoryPermit {
    active: Arc<AtomicUsize>,
}

impl Drop for InvocationFactoryPermit {
    fn drop(&mut self) {
        self.active.fetch_sub(1, Ordering::AcqRel);
    }
}

/// Concrete host-owned provider backed by one typed factory.
///
/// The factory supplies the seven owner values. The provider overwrites the run
/// identity with the exact durable RunStart binding, validates the completed
/// invocation and only then returns it to Agentd. Factory execution is bounded
/// independently from the caller future.
pub struct HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    factory: Arc<F>,
    policy: AgentdIntelligenceInvocationPolicyV1,
    active: Arc<AtomicUsize>,
}

impl<F> HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    #[must_use]
    pub fn new(factory: F) -> Self {
        Self {
            factory: Arc::new(factory),
            policy: AgentdIntelligenceInvocationPolicyV1::default(),
            active: Arc::new(AtomicUsize::new(0)),
        }
    }

    pub fn with_policy(
        factory: F,
        policy: AgentdIntelligenceInvocationPolicyV1,
    ) -> Result<Self, AgentdError> {
        policy.validate()?;
        Ok(Self {
            factory: Arc::new(factory),
            policy,
            active: Arc::new(AtomicUsize::new(0)),
        })
    }

    #[must_use]
    pub const fn policy(&self) -> AgentdIntelligenceInvocationPolicyV1 {
        self.policy
    }

    #[must_use]
    pub fn active_factory_calls(&self) -> usize {
        self.active.load(Ordering::Acquire)
    }

    fn acquire_factory_slot(&self) -> Result<InvocationFactoryPermit, AgentdError> {
        loop {
            let current = self.active.load(Ordering::Acquire);
            if current >= self.policy.max_in_flight {
                return Err(AgentdError::Protocol(
                    "canonical intelligence invocation factory is saturated".to_string(),
                ));
            }
            if self
                .active
                .compare_exchange_weak(current, current + 1, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                return Ok(InvocationFactoryPermit {
                    active: Arc::clone(&self.active),
                });
            }
        }
    }

    fn supervise_factory(&self, budget: Duration) -> Result<FactoryCompletion, AgentdError> {
        let (complete, observed) = mpsc::sync_channel(1);
        let grace = self.policy.hard_timeout_process_exit_grace;
        let observer = std::thread::Builder::new()
            .name("agentd-intelligence-invocation-watchdog".to_string())
            .spawn(move || {
                if observed.recv_timeout(budget).is_ok() {
                    return;
                }
                if let Some(grace) = grace
                    && observed.recv_timeout(grace).is_err()
                {
                    std::process::exit(70);
                }
            })
            .map_err(|error| AgentdError::Protocol(format!("factory watchdog: {error}")))?;
        Ok(FactoryCompletion {
            complete,
            observer: Some(observer),
        })
    }
}

struct FactoryCompletion {
    complete: mpsc::SyncSender<()>,
    observer: Option<std::thread::JoinHandle<()>>,
}

enum InvocationFactoryExecutionV1 {
    Dedicated,
    CanonicalWorker,
}

impl Drop for FactoryCompletion {
    fn drop(&mut self) {
        let _ = self.complete.send(());
        if let Some(observer) = self.observer.take() {
            let _ = observer.join();
        }
    }
}

impl<F> HostOwnedAgentdIntelligenceInvocationProviderV1<F>
where
    F: Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>
        + Send
        + Sync
        + 'static,
{
    fn build_with_execution(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        execution: InvocationFactoryExecutionV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let permit = self.acquire_factory_slot()?;
        let durable_identity = AgentdIntelligenceRunIdentityV1::from_run_start(identity, record)?;
        let factory = Arc::clone(&self.factory);
        let identity = identity.clone();
        let record = record.clone();
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| AgentdError::Protocol(error.to_string()))?
            .as_millis();
        let now =
            u64::try_from(now).map_err(|_| AgentdError::Invalid("factory clock".to_string()))?;
        let remaining = durable_identity
            .deadline_ms
            .checked_sub(now)
            .filter(|value| *value != 0)
            .ok_or_else(|| AgentdError::Protocol("factory run deadline elapsed".to_string()))?;
        let budget = self.policy.timeout.min(Duration::from_millis(remaining));
        let work = move || {
            std::panic::catch_unwind(AssertUnwindSafe(|| {
                let mut invocation = (factory)(&identity, &record)?;
                invocation.inputs.run_identity = Some(durable_identity);
                invocation.validate(&identity, &record)?;
                Ok(invocation)
            }))
            .unwrap_or_else(|_| {
                Err(AgentdError::Protocol(
                    "canonical intelligence invocation factory panicked".to_string(),
                ))
            })
        };
        if matches!(execution, InvocationFactoryExecutionV1::CanonicalWorker) {
            // The actual factory shares the caller's supervised worker. Its
            // completion guard and this slot survive a dropped or timed-out
            // request until the factory itself returns or the process exits.
            let _permit = permit;
            return work();
        }
        let completion = self.supervise_factory(budget)?;
        let (sender, receiver) = mpsc::sync_channel(1);
        std::thread::Builder::new()
            .name("agentd-intelligence-invocation-factory".to_string())
            .spawn(move || {
                let _permit = permit;
                let _completion = completion;
                let result = work();
                let _ = sender.send(result);
            })
            .map_err(|error| {
                AgentdError::Protocol(format!(
                    "canonical intelligence invocation worker failed to start: {error}"
                ))
            })?;
        match receiver.recv_timeout(budget) {
            Ok(result) => result,
            Err(mpsc::RecvTimeoutError::Timeout) => Err(AgentdError::Protocol(
                "canonical intelligence invocation factory timed out".to_string(),
            )),
            Err(mpsc::RecvTimeoutError::Disconnected) => Err(AgentdError::Protocol(
                "canonical intelligence invocation factory disconnected".to_string(),
            )),
        }
    }
}

impl<F> AgentdIntelligenceInvocationProviderV1
    for HostOwnedAgentdIntelligenceInvocationProviderV1<F>
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
        self.build_with_execution(identity, record, InvocationFactoryExecutionV1::Dedicated)
    }

    fn build_in_canonical_worker(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        self.build_with_execution(
            identity,
            record,
            InvocationFactoryExecutionV1::CanonicalWorker,
        )
    }

    fn canonical_worker_timeout(&self) -> Duration {
        self.policy.timeout
    }

    fn canonical_worker_exit_grace(&self) -> Option<Duration> {
        self.policy.hard_timeout_process_exit_grace
    }
}

/// Composition seam for the seven canonical intelligence owners.
///
/// Implementations are host-owned and must derive current stage inputs from
/// their authoritative owners. Request/wire callers cannot provide this object
/// and therefore cannot substitute policy, model, artifact, trust, currentness
/// or physical-run identity inputs.
pub trait AgentdIntelligenceInvocationProviderV1: Send + Sync {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>;

    /// Build inside an actual supervised canonical worker, whose completion
    /// guard must survive request timeout or cancellation. Implementations must
    /// retain all factory work in that lifetime, rather than detach threads that
    /// can outlive the guard. The default preserves existing trusted providers;
    /// the built-in host-owned provider executes its factory directly here.
    /// Calling this method alone installs no watchdog or runtime authority.
    fn build_in_canonical_worker(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        self.build(identity, record)
    }

    /// Pure, nonblocking timeout policy for the supervised worker. The runner
    /// also caps this value by its existing 30-second and durable RunStart
    /// budgets. Built-in providers retain a shorter configured factory timeout.
    fn canonical_worker_timeout(&self) -> Duration {
        DEFAULT_INVOCATION_TIMEOUT
    }

    /// Pure, nonblocking optional process-exit grace for the supervised worker.
    /// The runner uses the shorter configured grace; `None` preserves its own
    /// mandatory canonical fence rather than disabling process containment.
    fn canonical_worker_exit_grace(&self) -> Option<Duration> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invocation_policy_rejects_unbounded_values() {
        let invalid = AgentdIntelligenceInvocationPolicyV1 {
            timeout: Duration::ZERO,
            max_in_flight: 0,
            hard_timeout_process_exit_grace: None,
        };
        assert!(invalid.validate().is_err());
        let invalid = AgentdIntelligenceInvocationPolicyV1 {
            timeout: Duration::from_secs(301),
            max_in_flight: 1,
            hard_timeout_process_exit_grace: None,
        };
        assert!(invalid.validate().is_err());
        let invalid = AgentdIntelligenceInvocationPolicyV1 {
            timeout: Duration::from_secs(1),
            max_in_flight: 65,
            hard_timeout_process_exit_grace: None,
        };
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn invocation_factory_slot_is_owned_until_real_worker_retirement() {
        let provider = HostOwnedAgentdIntelligenceInvocationProviderV1::with_policy(
            |_identity: &AgentdIdentity, _record: &RunStartRecordV1| {
                unreachable!("factory is not called by this admission test")
            },
            AgentdIntelligenceInvocationPolicyV1 {
                timeout: Duration::from_secs(1),
                max_in_flight: 1,
                hard_timeout_process_exit_grace: None,
            },
        )
        .expect("bounded provider");
        let permit = provider.acquire_factory_slot().expect("first slot");
        assert_eq!(provider.active_factory_calls(), 1);
        assert!(provider.acquire_factory_slot().is_err());
        drop(permit);
        assert_eq!(provider.active_factory_calls(), 0);
        assert!(provider.acquire_factory_slot().is_ok());
    }
}
