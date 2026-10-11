//! Memory-owned adapter for the explicit local-development witness seam.
//!
//! The owner is intentionally not an extension contributor.  It validates a
//! closed-world policy and exposes one host-invoked method; callers must hand
//! it the lease/checkpoint/executor handles they already own.  Constructing an
//! owner therefore does not register callbacks, create a scheduler, or add a
//! production caller.

use crate::LocalRehydrationWitnessLifecycleError;
use crate::LocalRehydrationWitnessLifecycleInput;
use crate::LocalRehydrationWitnessLifecycleResult;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicy;
use codex_hepta_memory::LocalDevelopmentLifecyclePolicyError;
use codex_hepta_memory::LocalLease;
use codex_hepta_memory::LocalLeaseOutbox;
use codex_hepta_memory::LocalLeaseOutboxError;

pub const HEPTA_LOCAL_LIFECYCLE_OWNER_RUNTIME_REGISTERED: bool = false;
pub const HEPTA_LOCAL_LIFECYCLE_OWNER_PRODUCTION_CALLER: bool = false;
pub const HEPTA_LOCAL_LIFECYCLE_OWNER_EXTERNAL_EFFECTS: bool = false;
pub const HEPTA_LOCAL_LIFECYCLE_OWNER_KG_WRITE_AUTHORITY: bool = false;

#[derive(Debug)]
pub enum HeptaLocalDevelopmentLifecycleOwnerError {
    Policy(LocalDevelopmentLifecyclePolicyError),
    Lifecycle(LocalRehydrationWitnessLifecycleError),
    Lease(LocalLeaseOutboxError),
    StoreBindingMismatch,
}

impl std::fmt::Display for HeptaLocalDevelopmentLifecycleOwnerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Policy(error) => write!(formatter, "local lifecycle policy rejected: {error}"),
            Self::Lifecycle(error) => write!(formatter, "local lifecycle write failed: {error}"),
            Self::Lease(error) => write!(formatter, "local lease expiry failed: {error}"),
            Self::StoreBindingMismatch => {
                formatter.write_str("local lease does not belong to the supplied Agent-local store")
            }
        }
    }
}

impl std::error::Error for HeptaLocalDevelopmentLifecycleOwnerError {}

impl From<LocalDevelopmentLifecyclePolicyError> for HeptaLocalDevelopmentLifecycleOwnerError {
    fn from(error: LocalDevelopmentLifecyclePolicyError) -> Self {
        Self::Policy(error)
    }
}

impl From<LocalRehydrationWitnessLifecycleError> for HeptaLocalDevelopmentLifecycleOwnerError {
    fn from(error: LocalRehydrationWitnessLifecycleError) -> Self {
        Self::Lifecycle(error)
    }
}

impl From<LocalLeaseOutboxError> for HeptaLocalDevelopmentLifecycleOwnerError {
    fn from(error: LocalLeaseOutboxError) -> Self {
        Self::Lease(error)
    }
}

/// Host-owned, qualification-only lifecycle owner.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HeptaLocalDevelopmentLifecycleOwner {
    policy: LocalDevelopmentLifecyclePolicy,
}

impl HeptaLocalDevelopmentLifecycleOwner {
    pub fn new(
        policy: LocalDevelopmentLifecyclePolicy,
    ) -> Result<Self, HeptaLocalDevelopmentLifecycleOwnerError> {
        policy.validate()?;
        Ok(Self { policy })
    }

    pub fn qualification_only() -> Self {
        // The canonical constructor is statically known to satisfy the gate;
        // keep the checked constructor above for untrusted embedding input.
        Self::new(LocalDevelopmentLifecyclePolicy::qualification_only()).unwrap_or_else(|error| {
            panic!("canonical local-development policy must validate: {error:?}")
        })
    }

    pub const fn policy(&self) -> LocalDevelopmentLifecyclePolicy {
        self.policy
    }

    pub const fn runtime_registered(&self) -> bool {
        HEPTA_LOCAL_LIFECYCLE_OWNER_RUNTIME_REGISTERED
    }

    pub const fn production_caller(&self) -> bool {
        HEPTA_LOCAL_LIFECYCLE_OWNER_PRODUCTION_CALLER
    }

    /// Invoke the extension seam exactly once for this host call.
    ///
    /// The input's policy is replaced with the owner's validated policy so a
    /// host cannot accidentally downgrade the gate between owner creation and
    /// the write.  No callback or background task is installed here.
    pub async fn write_local_rehydration_witness(
        &self,
        mut input: LocalRehydrationWitnessLifecycleInput<'_>,
    ) -> Result<LocalRehydrationWitnessLifecycleResult, HeptaLocalDevelopmentLifecycleOwnerError>
    {
        self.policy.validate()?;
        input.policy = self.policy;
        Ok(crate::write_local_rehydration_witness_at_lifecycle(input).await?)
    }

    /// Explicitly terminalize an expired bound lease owned by the host.
    ///
    /// The host supplies the exact store and lease handle it owns.  The owner
    /// checks the qualification-only policy and the handle's path+Agent
    /// binding before delegating to E20's single-transaction `expire_lease`.
    /// No callback, scheduler, retry loop, provider call, or external effect
    /// is created by this method.
    pub async fn expire_local_lease(
        &self,
        store: &CognitiveStore,
        lease: &LocalLeaseOutbox,
    ) -> Result<LocalLease, HeptaLocalDevelopmentLifecycleOwnerError> {
        self.policy.validate()?;
        if !lease.is_bound_to_store(store) {
            return Err(HeptaLocalDevelopmentLifecycleOwnerError::StoreBindingMismatch);
        }
        if !lease.is_explicitly_bound() {
            return Err(HeptaLocalDevelopmentLifecycleOwnerError::Lease(
                LocalLeaseOutboxError::Invalid(
                    "explicit authority/owner/expiry binding is required to expire a local lease"
                        .to_string(),
                ),
            ));
        }
        Ok(lease.expire_lease().await?)
    }
}

#[cfg(test)]
#[path = "local_development_owner_tests.rs"]
mod tests;
