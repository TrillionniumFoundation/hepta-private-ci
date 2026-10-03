//! Inactive host-only admission boundary. This does not install host trust,
//! advertise a wire capability, mutate a run, or grant a physical effect permit.
//! NativeBoundSourceProof preserves a checked payload fact, not live source-owner
//! currentness. A future mutation host must separately authenticate the source
//! journal incarnation, retirement/reconciliation status and current authority.
use std::sync::Arc;

use super::{AgentRunCoordinator, AgentRunError, RunPhase, RunRecord, RuntimeComposition};
use codex_hepta_contracts::{AgentId, RunBridgeBindingV1, Sha256Digest};
use codex_hepta_infer_core::control_contracts::{
    ControlTrustStore, SignedExecutionAuthorityBundle, verify_execution_plan,
};
use codex_hepta_infer_core::durable_control::native::NativeBoundSourceProof;

/// Host-authenticated observation. No request may select this trust or clock.
/// The host must advance trust_revision whenever any pinned key or revocation
/// changes, and authenticate both generation values against its live owner.
pub struct RunBridgeHostObservation {
    pub trust: ControlTrustStore,
    pub trust_revision: u64,
    pub now_unix_ms: u64,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub current_generation: u64,
    pub authority_epoch: u64,
    pub configuration_sha256: Sha256Digest,
    pub ports_sha256: Sha256Digest,
}

/// The runtime host must provide an independently trusted current source.
/// There is deliberately no default, wire constructor or installed provider.
/// Return an error unless the live destination is ready, unfenced and accepting
/// this operation; generation numbers alone do not establish lifecycle readiness.
pub trait RunBridgeHostCurrentness: Send + Sync {
    fn observe(&self) -> Result<RunBridgeHostObservation, RunBridgeAdmissionError>;
}

#[derive(Debug, Eq, PartialEq)]
pub enum RunBridgeAdmissionError {
    Owner(AgentRunError),
    HostUnavailable,
    InvalidAuthority,
    BindingMismatch,
    CurrentnessChanged,
}

impl std::fmt::Display for RunBridgeAdmissionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for RunBridgeAdmissionError {}

pub(super) mod sealed {
    pub trait Sealed {}
}

/// Implemented only by the existing retained Agentd run coordinator. Each read
/// must verify its retained file before returning the immutable owner view.
pub trait RunBridgeRetainedOwner: sealed::Sealed {
    fn bridge_snapshot(&mut self, run_id: &str) -> Result<RunBridgeRetainedView, AgentRunError>;
}

/// Opaque observation of the real retained owner, not a caller-built snapshot.
#[derive(Clone, Eq, PartialEq)]
pub struct RunBridgeRetainedView {
    composition: RuntimeComposition,
    record: RunRecord,
    admissions_open: bool,
}
impl RunBridgeRetainedView {
    pub(super) fn new(owner: &AgentRunCoordinator, record: &RunRecord) -> Self {
        Self {
            composition: owner.composition().clone(),
            record: record.clone(),
            admissions_open: owner.admissions_open(),
        }
    }
}

pub struct RunBridgeAdmissionHost {
    currentness: Arc<dyn RunBridgeHostCurrentness>,
}

/// A scoped validation result, never a send or store-mutation permit. It cannot
/// be cloned, serialized or retained beyond its exclusive borrow of the owner.
/// Future mutation code must perform a new under-lock final-use check. Rechecking
/// a snapshot is not an atomic cross-process generation lease.
pub struct RunBridgeDestinationAdmission<'a> {
    host: &'a RunBridgeAdmissionHost,
    owner: &'a mut dyn RunBridgeRetainedOwner,
    signed: &'a SignedExecutionAuthorityBundle,
    source: &'a NativeBoundSourceProof,
    binding: &'a RunBridgeBindingV1,
    retained: RunBridgeRetainedView,
    current: RunBridgeHostObservation,
    invalidated: bool,
}

impl RunBridgeAdmissionHost {
    /// Accept only a source already authenticated and owned by the runtime host.
    /// Construction itself does not make that source trusted or install it.
    pub fn new(currentness: Arc<dyn RunBridgeHostCurrentness>) -> Self {
        Self { currentness }
    }

    pub fn validate<'a>(
        &'a self,
        owner: &'a mut dyn RunBridgeRetainedOwner,
        signed: &'a SignedExecutionAuthorityBundle,
        source: &'a NativeBoundSourceProof,
        binding: &'a RunBridgeBindingV1,
    ) -> Result<RunBridgeDestinationAdmission<'a>, RunBridgeAdmissionError> {
        let (retained, current) = self.check(owner, signed, source, binding)?;
        Ok(RunBridgeDestinationAdmission {
            host: self,
            owner,
            signed,
            source,
            binding,
            retained,
            current,
            invalidated: false,
        })
    }

    fn check(
        &self,
        owner: &mut dyn RunBridgeRetainedOwner,
        signed: &SignedExecutionAuthorityBundle,
        source: &NativeBoundSourceProof,
        binding: &RunBridgeBindingV1,
    ) -> Result<(RunBridgeRetainedView, RunBridgeHostObservation), RunBridgeAdmissionError> {
        use RunBridgeAdmissionError as Error;
        binding.validate().map_err(|_| Error::BindingMismatch)?;
        let current = self.currentness.observe()?;
        if current.trust_revision == 0 || current.authority_epoch == 0 {
            return Err(Error::HostUnavailable);
        }
        let plan = verify_execution_plan(current.now_unix_ms, &current.trust, signed)
            .map_err(|_| Error::InvalidAuthority)?;
        let retained = owner
            .bridge_snapshot(&binding.identity.run_id)
            .map_err(Error::Owner)?;
        if !retained.admissions_open {
            return Err(Error::Owner(AgentRunError::AdmissionClosed));
        }
        let record = &retained.record;
        let composition = &retained.composition;
        let source = source.record();
        let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
        fence.extend_from_slice(current.agent_id.as_str().as_bytes());
        fence.extend_from_slice(&current.spawn_generation.to_be_bytes());
        fence.extend_from_slice(&current.current_generation.to_be_bytes());
        if current.agent_id.as_str() != composition.agent_id
            || current.configuration_sha256.as_str() != composition.configuration_digest
            || current.ports_sha256.as_str() != composition.ports_digest
            || current.spawn_generation != composition.agentd_generation
            || composition.supervisor_generation != composition.agentd_generation
            || Some(current.current_generation) != current.spawn_generation.checked_add(1)
            || record.snapshot.generation != current.current_generation
            || record.snapshot.fence_digest != Sha256Digest::for_bytes(&fence).as_str()
            || record.snapshot.authority_epoch != current.authority_epoch
        {
            return Err(Error::CurrentnessChanged);
        }
        if record.phase != RunPhase::ContextAttached
            || current.now_unix_ms >= record.snapshot.deadline_ms
        {
            return Err(Error::Owner(AgentRunError::InvalidTransition));
        }
        if binding.identity.agent_id != current.agent_id
            || binding.identity.owner_generation != current.current_generation
            || binding.identity.fence_sha256.as_str() != record.snapshot.fence_digest
            || Some(binding.identity.owner_dispatch_revision) != record.revision.checked_add(1)
            || source.owner_pre_dispatch_revision != record.revision
            || source.run_id != record.snapshot.run_id
            || source.request_id != binding.identity.request_id
            || source.context_sha256 != binding.identity.context_sha256.as_str()
            || source.envelope_sha256 != binding.identity.envelope_sha256.as_str()
            || record.context_digest.as_deref() != Some(source.context_sha256.as_str())
            || record.compilation_receipt_digest.as_deref() != Some(source.envelope_sha256.as_str())
            || plan.request_id() != source.request_id
            || plan.principal_id() != current.agent_id.as_str()
            || plan.authority_epoch() != current.authority_epoch
            || plan.resource_lease().worker_generation != current.spawn_generation
            || plan.manifest().payload_digest != source.request_payload_sha256
            || plan.execution_binding_digest() != binding.identity.execution_binding_sha256.as_str()
        {
            return Err(Error::BindingMismatch);
        }
        // Detect host movement during signature and retained-file validation.
        // The result still grants no lease beyond this synchronous observation.
        let after = self.currentness.observe()?;
        if !same_host(&current, &after)
            || after.now_unix_ms < current.now_unix_ms
            || after.now_unix_ms >= record.snapshot.deadline_ms
            || plan.assert_valid_at(after.now_unix_ms).is_err()
        {
            return Err(Error::CurrentnessChanged);
        }
        let final_view = owner
            .bridge_snapshot(&binding.identity.run_id)
            .map_err(Error::Owner)?;
        if final_view != retained {
            return Err(Error::CurrentnessChanged);
        }
        Ok((retained, after))
    }
}

impl RunBridgeDestinationAdmission<'_> {
    /// Re-read retained integrity, signatures, trusted clock and currentness.
    /// This result is observational only; it cannot be passed to a mutation API.
    pub fn revalidate(&mut self) -> Result<(), RunBridgeAdmissionError> {
        if self.invalidated {
            return Err(RunBridgeAdmissionError::CurrentnessChanged);
        }
        // A failed final-use observation cannot be repaired by restoring old
        // host values. The caller must drop this result and validate afresh.
        self.invalidated = true;
        let (retained, current) =
            self.host
                .check(self.owner, self.signed, self.source, self.binding)?;
        if retained != self.retained
            || !same_host(&current, &self.current)
            || current.now_unix_ms < self.current.now_unix_ms
        {
            return Err(RunBridgeAdmissionError::CurrentnessChanged);
        }
        self.current = current;
        self.invalidated = false;
        Ok(())
    }
}

fn same_host(left: &RunBridgeHostObservation, right: &RunBridgeHostObservation) -> bool {
    left.agent_id == right.agent_id
        && left.spawn_generation == right.spawn_generation
        && left.current_generation == right.current_generation
        && left.authority_epoch == right.authority_epoch
        && left.trust_revision == right.trust_revision
        && left.configuration_sha256 == right.configuration_sha256
        && left.ports_sha256 == right.ports_sha256
}

#[cfg(all(test, unix))]
#[path = "run_bridge_admission_tests.rs"]
mod tests;
