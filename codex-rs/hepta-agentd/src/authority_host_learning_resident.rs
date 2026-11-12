//! Explicit Root-resident LEARN custody, separately authorized from A's writer.
//! A completed ordinary task can enroll later. Only this new profile admits
//! work; V1/V2 snapshots, Root credentials, and existing checkpoints cannot.

use std::io;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use super::HostAuthorityService;

#[path = "authority_host_learning_resident_profile.rs"]
mod profile;
pub use profile::ROOT_RESIDENT_LEARNING_EXECUTE_V3;
pub use profile::ROOT_RESIDENT_LEARNING_READBACK_V3;
pub use profile::RootResidentLearningProfileV3;
pub use profile::RootResidentLearningReadbackAuthorizationV3;

#[path = "authority_host_learning_resident_authority.rs"]
mod authority;
#[path = "authority_host_learning_resident_gate.rs"]
mod gate;
#[path = "authority_host_learning_resident_store.rs"]
mod store;
pub(crate) use gate::RootResidentLearningEffectGateV3;

#[path = "authority_host_learning_resident_runtime.rs"]
mod runtime;
#[path = "authority_host_learning_resident_stages.rs"]
mod stages;
pub use runtime::RootResidentLearningHandleV3;
pub use runtime::RootResidentLearningRuntimeV3;
#[path = "authority_host_learning_resident_auth.rs"]
mod authentication;
#[path = "authority_host_learning_resident_transport.rs"]
mod transport;
#[path = "authority_host_learning_resident_wire.rs"]
mod wire;
pub use transport::AgentdRootResidentLearningClientV3;
pub use transport::RootResidentLearningObservationV3;

use authority::ResidentAuthorizationV3;
use authority::ResidentRootAuthorityV3;
use authority::ResidentStoreActionV3;
use authority::ResidentStoreValueV3;
use gate::ResidentRegisteredStateV3;

/// Original Root file custody plus its independently registered execution or
/// readback intent. No caller receives a writer, mutable stage owner or key.
pub struct RootResidentLearningRegistrationV3 {
    owner: Arc<ResidentRegisteredStateV3>,
}

impl HostAuthorityService {
    /// Explicit registration after actual A completion. The same original
    /// Root factory retained the directory and Registry; public profile data,
    /// an old A writer proof, or root UID cannot construct that custody.
    pub fn register_resident_learning_v3(
        &self,
        profile: RootResidentLearningProfileV3,
    ) -> io::Result<RootResidentLearningRegistrationV3> {
        self.resident_learning_v3(profile, ResidentAuthorizationV3::Fresh)
    }

    /// Open-only cold observation under a separately supplied current Root
    /// readback grant and exact lease. Missing/foreign/partial files fail;
    /// even an existing vacant record can never be promoted to execution.
    pub fn recover_resident_learning_v3(
        &self,
        profile: RootResidentLearningProfileV3,
        authorization: RootResidentLearningReadbackAuthorizationV3,
    ) -> io::Result<RootResidentLearningRegistrationV3> {
        self.resident_learning_v3(profile, ResidentAuthorizationV3::Readback(authorization))
    }

    fn resident_learning_v3(
        &self,
        profile: RootResidentLearningProfileV3,
        authorization: ResidentAuthorizationV3,
    ) -> io::Result<RootResidentLearningRegistrationV3> {
        let root = Arc::clone(
            self.resident_store_root
                .as_ref()
                .ok_or_else(|| profile::invalid("original Root directory custody is absent"))?,
        );
        let registry = Arc::clone(
            self.root_registry
                .as_ref()
                .ok_or_else(|| profile::invalid("original Root Registry custody is absent"))?,
        );
        RootResidentLearningRegistrationV3::from_original_root(
            root,
            Arc::clone(&self.issuer),
            registry,
            profile,
            authorization,
        )
    }
}

impl RootResidentLearningRegistrationV3 {
    /// The original Root runtime factory is the only external caller. Neither
    /// entry creates a grant, lease, issuer, trust key or writable directory.
    pub(crate) fn register_original_root(
        root: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
        issuer: Arc<crate::DeploymentFinalUseIssuer>,
        registry: Arc<codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry>,
        profile: RootResidentLearningProfileV3,
    ) -> io::Result<Self> {
        Self::from_original_root(
            root,
            issuer,
            registry,
            profile,
            ResidentAuthorizationV3::Fresh,
        )
    }

    pub(crate) fn recover_original_root(
        root: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
        issuer: Arc<crate::DeploymentFinalUseIssuer>,
        registry: Arc<codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry>,
        profile: RootResidentLearningProfileV3,
        authorization: RootResidentLearningReadbackAuthorizationV3,
    ) -> io::Result<Self> {
        Self::from_original_root(
            root,
            issuer,
            registry,
            profile,
            ResidentAuthorizationV3::Readback(authorization),
        )
    }

    fn from_original_root(
        root: Arc<codex_hepta_contracts::RootAuthorityDirectory>,
        issuer: Arc<crate::DeploymentFinalUseIssuer>,
        registry: Arc<codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry>,
        profile: RootResidentLearningProfileV3,
        authorization: ResidentAuthorizationV3,
    ) -> io::Result<Self> {
        let authority = ResidentRootAuthorityV3::new(profile, issuer, registry, authorization)?;
        let action = if authority.readonly() {
            ResidentStoreActionV3::Recover(root)
        } else {
            ResidentStoreActionV3::Register(root)
        };
        let record = authority.perform(action, &CancellationToken::new())?;
        let ResidentStoreValueV3::Store(checkpoint) = record.value else {
            return Err(io::Error::other(
                "resident registration produced no original owner",
            ));
        };
        Ok(RootResidentLearningRegistrationV3 {
            owner: Arc::new(ResidentRegisteredStateV3::new(authority, checkpoint)),
        })
    }
}

impl RootResidentLearningRegistrationV3 {
    /// Consume the concrete original role bundle by value. The caller cannot
    /// retain an Arc to invoke its installed gate from another future.
    /// Each role channel was created for the actual resident process, not for
    /// A's UID/PID. This API grants neither version publication nor C execution.
    pub fn into_runtime(
        self,
        stages: crate::OriginalCellQ24NoUpdateStageOwnersV1,
        verifier: codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
        capacity: usize,
    ) -> Result<(RootResidentLearningHandleV3, RootResidentLearningRuntimeV3), crate::AgentdError>
    {
        runtime::compose(
            self.owner,
            stages::ResidentOriginalStageOwnersV3::NoUpdate(stages),
            verifier,
            capacity,
        )
    }
}

impl RootResidentLearningRegistrationV3 {
    /// Consume the concrete Candidate branch under the same registered Root
    /// intent, original Registry and schema-3 checkpoint. This does not issue
    /// an Evaluator, Model, Selector, version-publication or FinalUse capability.
    /// All original role descriptors were held before D/T existed; Root installs
    /// its effect gate only after the existing actual fresh admission CAS.
    pub fn into_candidate_runtime(
        self,
        stages: crate::OriginalCellQ24CandidateStageOwnersV1,
        verifier: codex_hepta_learning_ledger::LearningEvidenceVerifierV1,
        capacity: usize,
    ) -> Result<(RootResidentLearningHandleV3, RootResidentLearningRuntimeV3), crate::AgentdError>
    {
        runtime::compose(
            self.owner,
            stages::ResidentOriginalStageOwnersV3::Candidate(stages),
            verifier,
            capacity,
        )
    }
}
