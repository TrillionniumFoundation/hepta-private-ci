//! Bounded host-owned canonical intelligence invocation provider.
//!
//! The registry is populated only by trusted in-process composition code after
//! the exact durable `RunStartRecordV1` has been published. Wire callers cannot
//! construct or mutate it. Each invocation is consumed once; an exact duplicate
//! registration is idempotent while semantic drift for the same run is rejected.

use std::collections::BTreeMap;
use std::sync::Mutex;

use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;

pub const MAX_PENDING_INTELLIGENCE_INVOCATIONS: usize = 256;

struct PendingInvocationV1 {
    binding_digest: Digest32,
    invocation: AgentdIntelligenceInvocationV1,
}

/// Concrete composition seam for the canonical seven-owner product profile.
///
/// A product host derives owner inputs from authoritative owners, registers the
/// resulting invocation against the already durable `RunStartRecordV1`, and
/// then lets `ObjectiveStart` consume it. The registry never accepts serialized
/// request data and never fabricates a compatibility invocation.
pub struct RegisteredAgentdIntelligenceInvocationProviderV1 {
    profile_digest: Digest32,
    pending: Mutex<BTreeMap<StableId, PendingInvocationV1>>,
}

impl RegisteredAgentdIntelligenceInvocationProviderV1 {
    pub fn new(profile_digest: Digest32) -> Result<Self, AgentdError> {
        if profile_digest.is_zero() {
            return Err(AgentdError::Invalid(
                "canonical intelligence profile digest must be non-zero".to_string(),
            ));
        }
        Ok(Self {
            profile_digest,
            pending: Mutex::new(BTreeMap::new()),
        })
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    pub fn pending_count(&self) -> Result<usize, AgentdError> {
        Ok(self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .len())
    }

    /// Register a single exact invocation after validating it against the
    /// durable ObjectiveStart identity. Re-registering the same run/binding is
    /// idempotent; changing semantics under an existing run id is a conflict.
    pub fn register(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        invocation: AgentdIntelligenceInvocationV1,
    ) -> Result<(), AgentdError> {
        invocation.validate(identity, record)?;
        let run_id = record.snapshot.run_id.clone();
        let binding_digest = invocation.inputs.run_start.run_start_binding_digest;
        let mut pending = self.pending.lock().map_err(|_| {
            AgentdError::Protocol(
                "canonical intelligence invocation registry is poisoned".to_string(),
            )
        })?;
        if let Some(existing) = pending.get(&run_id) {
            if existing.binding_digest == binding_digest {
                return Ok(());
            }
            return Err(AgentdError::Invalid(format!(
                "canonical intelligence invocation conflict for run {run_id}"
            )));
        }
        if pending.len() >= MAX_PENDING_INTELLIGENCE_INVOCATIONS {
            return Err(AgentdError::Protocol(
                "canonical intelligence invocation registry capacity exceeded".to_string(),
            ));
        }
        pending.insert(
            run_id,
            PendingInvocationV1 {
                binding_digest,
                invocation,
            },
        );
        Ok(())
    }

    pub fn discard(&self, run_id: &StableId) -> Result<bool, AgentdError> {
        Ok(self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .remove(run_id)
            .is_some())
    }
}

impl AgentdIntelligenceInvocationProviderV1 for RegisteredAgentdIntelligenceInvocationProviderV1 {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        let run_id = record.snapshot.run_id.clone();
        let pending = self
            .pending
            .lock()
            .map_err(|_| {
                AgentdError::Protocol(
                    "canonical intelligence invocation registry is poisoned".to_string(),
                )
            })?
            .remove(&run_id)
            .ok_or_else(|| {
                AgentdError::Invalid(format!(
                    "no host-owned canonical intelligence invocation is registered for run {run_id}"
                ))
            })?;
        pending.invocation.validate(identity, record)?;
        Ok(pending.invocation)
    }
}
