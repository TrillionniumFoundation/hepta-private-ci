//! Host-owned canonical intelligence invocation at the existing ObjectiveStart boundary.
//!
//! The daemon wire carries the authenticated objective. It never carries the
//! seven owners' internal profiles, model state, current artifacts, or trust
//! material. A composition owner derives those inputs from the already-durable
//! RunStart record and the current owner generation.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::mpsc::RecvTimeoutError;
use std::sync::mpsc::sync_channel;
use std::time::Duration;

use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceOwnerInputsV1;
use crate::PreparedAgentdIntelligenceRunV1;
use crate::RunReceipt;

const DEFAULT_INVOCATION_FACTORY_BUDGET: Duration = Duration::from_millis(250);
const MAX_INVOCATION_FACTORY_BUDGET: Duration = Duration::from_secs(30);
const DEFAULT_INVOCATION_FACTORY_WORKERS: usize = 4;
const MAX_INVOCATION_FACTORY_WORKERS: usize = 64;

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdIntelligenceProductLoopDispositionV1 {
    Completed,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceProductLoopReceiptV1 {
    pub run_id: StableId,
    pub decision_operation_id: StableId,
    pub outcome_operation_id: Option<StableId>,
    pub physical_terminal_digest: Option<Digest32>,
    pub disposition: AgentdIntelligenceProductLoopDispositionV1,
}

pub type AgentdIntelligenceProductContinuationFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<AgentdIntelligenceProductLoopReceiptV1, AgentdError>>
            + Send
            + 'a,
    >,
>;

/// Product embedding continuation invoked only after Agentd has frozen the
/// exact prepared intelligence envelope into `ContextAttached`. Implementations
/// must reuse the existing runtime.codex/App Server spine and the canonical
/// learning outbox; they may not invent a second physical executor or writer.
pub trait AgentdIntelligenceProductContinuationV1: Send + Sync {
    fn continue_ready<'a>(
        &'a self,
        prepared: PreparedAgentdIntelligenceRunV1,
        run_receipt: RunReceipt,
    ) -> AgentdIntelligenceProductContinuationFuture<'a>;
}

/// Concrete host-owned provider backed by one typed factory.
///
/// The factory supplies the seven owner values. The provider overwrites the run
/// identity with the exact durable RunStart binding. Factory execution occurs in
/// a separately supervised bounded worker: a timed-out factory cannot publish
/// an invocation and continues to hold its worker slot until it really exits.
pub struct HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    factory: Arc<F>,
    budget: Duration,
    active_workers: Arc<AtomicUsize>,
    max_workers: usize,
    continuation: Option<Arc<dyn AgentdIntelligenceProductContinuationV1>>,
}

impl<F> HostOwnedAgentdIntelligenceInvocationProviderV1<F> {
    #[must_use]
    pub fn new(factory: F) -> Self {
        Self {
            factory: Arc::new(factory),
            budget: DEFAULT_INVOCATION_FACTORY_BUDGET,
            active_workers: Arc::new(AtomicUsize::new(0)),
            max_workers: DEFAULT_INVOCATION_FACTORY_WORKERS,
            continuation: None,
        }
    }

    pub fn with_worker_policy(
        mut self,
        budget: Duration,
        max_workers: usize,
    ) -> Result<Self, AgentdError> {
        if budget.is_zero()
            || budget > MAX_INVOCATION_FACTORY_BUDGET
            || max_workers == 0
            || max_workers > MAX_INVOCATION_FACTORY_WORKERS
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

    fn acquire_worker(&self) -> Result<(), AgentdError> {
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
                Ok(_) => return Ok(()),
                Err(actual) => observed = actual,
            }
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
        self.acquire_worker()?;
        let factory = Arc::clone(&self.factory);
        let active_workers = Arc::clone(&self.active_workers);
        let identity = identity.clone();
        let record = record.clone();
        let (sender, receiver) = sync_channel(1);
        let spawn = std::thread::Builder::new()
            .name("agentd-intelligence-invocation".to_string())
            .spawn(move || {
                let result = (factory)(&identity, &record);
                active_workers.fetch_sub(1, Ordering::AcqRel);
                let _ = sender.send(result);
            });
        if let Err(error) = spawn {
            self.active_workers.fetch_sub(1, Ordering::AcqRel);
            return Err(AgentdError::Io(error));
        }

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

    fn product_continuation(
        &self,
    ) -> Option<Arc<dyn AgentdIntelligenceProductContinuationV1>> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn provider() -> HostOwnedAgentdIntelligenceInvocationProviderV1<
        impl Fn(
            &AgentdIdentity,
            &RunStartRecordV1,
        ) -> Result<AgentdIntelligenceInvocationV1, AgentdError>,
    > {
        HostOwnedAgentdIntelligenceInvocationProviderV1::new(
            |_: &AgentdIdentity,
             _: &RunStartRecordV1|
             -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
                unreachable!("policy test never invokes the factory")
            },
        )
    }

    #[test]
    fn invocation_factory_policy_is_bounded() {
        assert!(
            provider()
                .with_worker_policy(Duration::from_millis(1), 1)
                .is_ok()
        );
        assert!(
            provider()
                .with_worker_policy(Duration::ZERO, 1)
                .is_err()
        );
        assert!(
            provider()
                .with_worker_policy(Duration::from_secs(31), 1)
                .is_err()
        );
        assert!(
            provider()
                .with_worker_policy(Duration::from_millis(1), 0)
                .is_err()
        );
        assert!(
            provider()
                .with_worker_policy(Duration::from_millis(1), 65)
                .is_err()
        );
    }

    #[test]
    fn invocation_factory_worker_slots_are_not_overcommitted() {
        let provider = provider()
            .with_worker_policy(Duration::from_millis(10), 1)
            .expect("valid policy");
        provider.acquire_worker().expect("first slot");
        assert!(matches!(
            provider.acquire_worker(),
            Err(AgentdError::Overloaded { .. })
        ));
        provider.active_workers.fetch_sub(1, Ordering::AcqRel);
        provider.acquire_worker().expect("released slot");
        provider.active_workers.fetch_sub(1, Ordering::AcqRel);
    }
}
