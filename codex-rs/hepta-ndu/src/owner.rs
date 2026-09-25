use std::error::Error as StdError;
use std::fmt;
use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;

use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::NduError;
use crate::NduEvaluationReceiptV2;
use crate::NduNumericAdmissionErrorV1;
use crate::NduNumericRegistryV1;
use crate::NduProjectionEntryV1;
use crate::NduProjectionKindV1;
use crate::NduProjectionStoreError;
use crate::NduProjectionStoreV1;
use crate::NduRegisteredUtilitySignalV1;
use crate::ScalarizationProfile;
use crate::UtilityProfile;
use crate::canonical_evaluation_policy_digest;
use crate::canonical_scalarization_digest;
use crate::canonical_utility_profile_digest;
use crate::evaluate_candidates_with_policy;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduOwnerContextV1 {
    pub principal_id: StableId,
    pub owner_id: StableId,
    pub host_generation: u64,
    pub principal_scope_digest: Digest32,
    pub fence_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduProductionPolicyV1 {
    pub utility_profile: UtilityProfile,
    pub evaluation_policy: EvaluationPolicyV1,
    pub scalarization: Option<ScalarizationProfile>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduOwnerMutationV1 {
    AppendProjection {
        kind: NduProjectionKindV1,
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    },
    SelectProjection {
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    },
    RevokeProjection {
        identity_digest: Digest32,
        objective_digest: Digest32,
        subject_digest: Digest32,
        projection_digest: Digest32,
    },
}

impl NduOwnerMutationV1 {
    fn identity_digest(&self) -> Digest32 {
        match self {
            Self::AppendProjection {
                identity_digest, ..
            }
            | Self::SelectProjection {
                identity_digest, ..
            }
            | Self::RevokeProjection {
                identity_digest, ..
            } => *identity_digest,
        }
    }

    fn objective_digest(&self) -> Digest32 {
        match self {
            Self::AppendProjection {
                objective_digest, ..
            }
            | Self::SelectProjection {
                objective_digest, ..
            }
            | Self::RevokeProjection {
                objective_digest, ..
            } => *objective_digest,
        }
    }

    fn subject_digest(&self) -> Digest32 {
        match self {
            Self::AppendProjection { subject_digest, .. }
            | Self::SelectProjection { subject_digest, .. }
            | Self::RevokeProjection { subject_digest, .. } => *subject_digest,
        }
    }

    fn projection_digest(&self) -> Digest32 {
        match self {
            Self::AppendProjection {
                projection_digest, ..
            }
            | Self::SelectProjection {
                projection_digest, ..
            }
            | Self::RevokeProjection {
                projection_digest, ..
            } => *projection_digest,
        }
    }

    fn tag(&self) -> u8 {
        match self {
            Self::AppendProjection { .. } => 0,
            Self::SelectProjection { .. } => 1,
            Self::RevokeProjection { .. } => 2,
        }
    }
}

#[derive(Debug)]
pub enum NduOwnerError {
    InvalidContext(&'static str),
    Ndu(NduError),
    NumericAdmission(NduNumericAdmissionErrorV1),
    Authority(FinalUseError),
    Store(NduProjectionStoreError),
}

impl fmt::Display for NduOwnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduOwnerError {}

impl From<NduError> for NduOwnerError {
    fn from(error: NduError) -> Self {
        Self::Ndu(error)
    }
}

impl From<NduNumericAdmissionErrorV1> for NduOwnerError {
    fn from(error: NduNumericAdmissionErrorV1) -> Self {
        Self::NumericAdmission(error)
    }
}

impl From<FinalUseError> for NduOwnerError {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

impl From<NduProjectionStoreError> for NduOwnerError {
    fn from(error: NduProjectionStoreError) -> Self {
        Self::Store(error)
    }
}

/// One authenticated NDU owner generation.
///
/// The owner freezes policy/profile semantics for its lifetime. Durable
/// mutations consume kernel.authority final-use grants that bind the principal,
/// owner, current fence/revocation frontier and exact mutation bytes. The NDU
/// module never mints those grants and cannot widen their authority.
pub struct NduAuthenticatedOwnerV1 {
    context: NduOwnerContextV1,
    policy: NduProductionPolicyV1,
    production_policy_digest: Digest32,
    numeric_registry: Option<NduNumericRegistryV1>,
    authority: FinalUseAuthority,
    store: NduProjectionStoreV1,
}

impl NduAuthenticatedOwnerV1 {
    pub fn open(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
    ) -> Result<Self, NduOwnerError> {
        Self::open_inner(root, authority, context, policy, None)
    }

    /// Open an owner with one immutable, caller-provisioned platform.types
    /// registry generation.  The registry digest is frozen into the production
    /// policy identity before any signal admission or durable mutation occurs.
    pub fn open_with_numeric_registry(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
        numeric_registry: NduNumericRegistryV1,
    ) -> Result<Self, NduOwnerError> {
        Self::open_inner(root, authority, context, policy, Some(numeric_registry))
    }

    fn open_inner(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
        numeric_registry: Option<NduNumericRegistryV1>,
    ) -> Result<Self, NduOwnerError> {
        validate_context(&context)?;
        let production_policy_digest = match numeric_registry.as_ref() {
            Some(registry) => {
                production_policy_digest_with_numeric_registry(&policy, registry.registry_digest())?
            }
            None => production_policy_digest(&policy)?,
        };
        let store = NduProjectionStoreV1::open(root)?;
        Ok(Self {
            context,
            policy,
            production_policy_digest,
            numeric_registry,
            authority,
            store,
        })
    }

    #[must_use]
    pub fn context(&self) -> &NduOwnerContextV1 {
        &self.context
    }

    #[must_use]
    pub const fn production_policy_digest(&self) -> Digest32 {
        self.production_policy_digest
    }

    #[must_use]
    pub fn numeric_registry_digest(&self) -> Option<Digest32> {
        self.numeric_registry
            .as_ref()
            .map(NduNumericRegistryV1::registry_digest)
    }

    pub fn admit_utility_signal(
        &self,
        source: &NumericSignalV1,
    ) -> Result<NduRegisteredUtilitySignalV1, NduOwnerError> {
        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduNumericAdmissionErrorV1::RegistryNotConfigured)?;
        registry
            .admit_utility_signal(&self.policy.utility_profile, source)
            .map_err(NduOwnerError::NumericAdmission)
    }

    /// The ordinary owner evaluation path cannot bypass its configured registry.
    /// Legacy owners opened without one retain advisory-only V2 compatibility;
    /// their receipt does not acquire registered-admission evidence.
    pub fn evaluate(
        &self,
        mut contributions: ContributionSet,
    ) -> Result<NduEvaluationReceiptV2, NduOwnerError> {
        if contributions.contributions.len() > crate::evaluator::MAX_CONTRIBUTIONS {
            return Err(NduError::ContributionLimitExceeded.into());
        }
        if let Some(registry) = &self.numeric_registry {
            let support_type = StableId::new("utility.ndu:registered-contribution-support-v1")
                .map_err(|_| NduOwnerError::InvalidContext("numeric support type"))?;
            for contribution in &mut contributions.contributions {
                // Never turn an absent source proof into a nonzero generated digest.
                if contribution.support_digest.is_zero() {
                    return Err(NduError::EmptySupportDigest {
                        candidate: contribution.candidate_id.to_string(),
                        organ: contribution.organ_id.to_string(),
                    }
                    .into());
                }
                let admitted = registry
                    .admit_utility_axes(&self.policy.utility_profile, &contribution.utility)?;
                let fields = [
                    CanonicalFieldV1 {
                        name: "source_support",
                        value: CanonicalValueV1::Digest(contribution.support_digest),
                    },
                    CanonicalFieldV1 {
                        name: "numeric_admission",
                        value: CanonicalValueV1::Digest(admitted.admission.admission_digest),
                    },
                ];
                contribution.support_digest = canonical_digest_v1(&support_type, 1, &fields)
                    .map_err(|_| NduOwnerError::InvalidContext("numeric support encoding"))?;
                contribution.utility = admitted.axis_values;
            }
        }
        evaluate_candidates_with_policy(
            contributions,
            self.policy.utility_profile.clone(),
            self.policy.scalarization.clone(),
            self.policy.evaluation_policy.clone(),
        )
        .map_err(NduOwnerError::Ndu)
    }

    pub fn final_use_binding(
        &self,
        mutation: &NduOwnerMutationV1,
    ) -> Result<FinalUseBinding, NduOwnerError> {
        for (name, digest) in [
            ("mutation identity", mutation.identity_digest()),
            ("objective", mutation.objective_digest()),
            ("subject", mutation.subject_digest()),
            ("projection", mutation.projection_digest()),
        ] {
            if digest.is_zero() {
                return Err(NduOwnerError::InvalidContext(name));
            }
        }

        let scope_digest = owner_scope_digest(
            &self.context,
            self.production_policy_digest,
            mutation.objective_digest(),
            mutation.subject_digest(),
            mutation.tag(),
        );
        let payload_digest = mutation_payload_digest(mutation, self.production_policy_digest);
        Ok(FinalUseBinding {
            subject_id: self.context.principal_id.to_string(),
            destination_id: self.context.owner_id.to_string(),
            request_sha256: *mutation.identity_digest().as_array(),
            scope_sha256: *scope_digest.as_array(),
            payload_sha256: *payload_digest.as_array(),
        })
    }

    pub fn apply_mutation(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        let expected = self.final_use_binding(&mutation)?;
        let authority = self.authority.clone();
        let token = authority.claim(signed, &expected)?;
        authority
            .with_verified_use(token, &expected, || match mutation {
                NduOwnerMutationV1::AppendProjection {
                    kind,
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                } => self.store.append_projection(
                    kind,
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                ),
                NduOwnerMutationV1::SelectProjection {
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                } => self.store.select_projection(
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                ),
                NduOwnerMutationV1::RevokeProjection {
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                } => self.store.revoke_projection(
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    projection_digest,
                ),
            })
            .map_err(NduOwnerError::Authority)?
            .map_err(NduOwnerError::Store)
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, NduOwnerError> {
        self.store
            .selected_projection_digest(objective_digest, subject_digest)
            .map_err(NduOwnerError::Store)
    }
}

fn validate_context(context: &NduOwnerContextV1) -> Result<(), NduOwnerError> {
    if context.host_generation == 0 {
        return Err(NduOwnerError::InvalidContext("host generation"));
    }
    for (name, digest) in [
        ("principal scope", context.principal_scope_digest),
        ("fence", context.fence_digest),
        ("revocation frontier", context.revocation_frontier_digest),
    ] {
        if digest.is_zero() {
            return Err(NduOwnerError::InvalidContext(name));
        }
    }
    Ok(())
}

fn production_policy_digest(policy: &NduProductionPolicyV1) -> Result<Digest32, NduOwnerError> {
    let utility = canonical_utility_profile_digest(&policy.utility_profile)?;
    let evaluation =
        canonical_evaluation_policy_digest(&policy.utility_profile, &policy.evaluation_policy)?;
    let scalarization = policy
        .scalarization
        .as_ref()
        .map(canonical_scalarization_digest)
        .transpose()?;

    let mut bytes = b"hepta.ndu.production-policy.v1\0".to_vec();
    bytes.extend_from_slice(utility.as_array());
    bytes.extend_from_slice(evaluation.as_array());
    match scalarization {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn production_policy_digest_with_numeric_registry(
    policy: &NduProductionPolicyV1,
    registry_digest: Digest32,
) -> Result<Digest32, NduOwnerError> {
    if registry_digest.is_zero() {
        return Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::EmptyRegistryDigest,
        ));
    }
    let base = production_policy_digest(policy)?;
    Ok(Digest32::of_parts(&[
        b"hepta.ndu.production-policy.numeric-registry.v1\0",
        base.as_array(),
        registry_digest.as_array(),
    ]))
}

fn owner_scope_digest(
    context: &NduOwnerContextV1,
    production_policy_digest: Digest32,
    objective_digest: Digest32,
    subject_digest: Digest32,
    mutation_tag: u8,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-owner-scope.v1\0".to_vec();
    push_id(&mut bytes, &context.principal_id);
    push_id(&mut bytes, &context.owner_id);
    bytes.extend_from_slice(&context.host_generation.to_be_bytes());
    bytes.extend_from_slice(context.principal_scope_digest.as_array());
    bytes.extend_from_slice(context.fence_digest.as_array());
    bytes.extend_from_slice(context.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    bytes.push(mutation_tag);
    Digest32::of_bytes(&bytes)
}

fn mutation_payload_digest(
    mutation: &NduOwnerMutationV1,
    production_policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-owner-mutation.v1\0".to_vec();
    bytes.push(mutation.tag());
    if let NduOwnerMutationV1::AppendProjection { kind, .. } = mutation {
        bytes.push(match kind {
            NduProjectionKindV1::Preference => 0,
            NduProjectionKindV1::Utility => 1,
            NduProjectionKindV1::SelectedProjection => 2,
            NduProjectionKindV1::Revocation => 3,
        });
    }
    bytes.extend_from_slice(mutation.identity_digest().as_array());
    bytes.extend_from_slice(mutation.objective_digest().as_array());
    bytes.extend_from_slice(mutation.subject_digest().as_array());
    bytes.extend_from_slice(mutation.projection_digest().as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(all(test, unix))]
#[path = "owner_tests.rs"]
mod tests;
