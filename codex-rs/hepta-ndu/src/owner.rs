use std::error::Error as StdError;
use std::fmt;
use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::NduError;
use crate::NduEvaluationReceiptV2;
use crate::NduProjectionEntryV1;
use crate::NduProjectionKindV1;
use crate::NduProjectionStoreError;
use crate::NduProjectionStoreV1;
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

/// Evaluation evidence created inside the authenticated owner from its frozen
/// policy and owner context. Fields are private so a caller cannot take an
/// authority-free evaluation and attach a claimed host/fence/frontier after the
/// numerical decision has already been made.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduAuthenticatedEvaluationReceiptV1 {
    evaluation: NduEvaluationReceiptV2,
    source_context_digest: Digest32,
    receipt_digest: Digest32,
}

impl NduAuthenticatedEvaluationReceiptV1 {
    #[must_use]
    pub const fn evaluation(&self) -> &NduEvaluationReceiptV2 {
        &self.evaluation
    }

    #[must_use]
    pub const fn source_context_digest(&self) -> Digest32 {
        self.source_context_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }
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
        expected_predecessor: Option<Digest32>,
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

    fn expected_predecessor(&self) -> Option<Digest32> {
        match self {
            Self::SelectProjection {
                expected_predecessor,
                ..
            } => *expected_predecessor,
            Self::AppendProjection { .. } | Self::RevokeProjection { .. } => None,
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
        validate_context(&context)?;
        let production_policy_digest = production_policy_digest(&policy)?;
        let store = NduProjectionStoreV1::open(root)?;
        Ok(Self {
            context,
            policy,
            production_policy_digest,
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

    pub fn evaluate(
        &self,
        contributions: ContributionSet,
    ) -> Result<NduAuthenticatedEvaluationReceiptV1, NduOwnerError> {
        let objective_digest = contributions.objective_digest;
        let generation = contributions.generation;
        let evaluation = evaluate_candidates_with_policy(
            contributions,
            self.policy.utility_profile.clone(),
            self.policy.scalarization.clone(),
            self.policy.evaluation_policy.clone(),
        )?;
        let source_context_digest = evaluation_source_context_digest(
            &self.context,
            self.production_policy_digest,
            objective_digest,
            generation,
        );
        let receipt_digest =
            authenticated_evaluation_receipt_digest(source_context_digest, &evaluation);
        Ok(NduAuthenticatedEvaluationReceiptV1 {
            evaluation,
            source_context_digest,
            receipt_digest,
        })
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
        if let Some(expected_predecessor) = mutation.expected_predecessor() {
            if expected_predecessor.is_zero() {
                return Err(NduOwnerError::InvalidContext("selection predecessor"));
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
                    expected_predecessor,
                    projection_digest,
                } => self.store.select_projection_if_current(
                    identity_digest,
                    objective_digest,
                    subject_digest,
                    expected_predecessor,
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

fn evaluation_source_context_digest(
    context: &NduOwnerContextV1,
    production_policy_digest: Digest32,
    objective_digest: Digest32,
    generation: Generation,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-evaluation-context.v1\0".to_vec();
    push_id(&mut bytes, &context.principal_id);
    push_id(&mut bytes, &context.owner_id);
    bytes.extend_from_slice(&context.host_generation.to_be_bytes());
    bytes.extend_from_slice(context.principal_scope_digest.as_array());
    bytes.extend_from_slice(context.fence_digest.as_array());
    bytes.extend_from_slice(context.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn authenticated_evaluation_receipt_digest(
    source_context_digest: Digest32,
    evaluation: &NduEvaluationReceiptV2,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-evaluation-receipt.v1\0".to_vec();
    bytes.extend_from_slice(source_context_digest.as_array());
    bytes.extend_from_slice(evaluation.evaluation_policy_digest.as_array());
    bytes.extend_from_slice(evaluation.evaluation_digest_v2.as_array());
    Digest32::of_bytes(&bytes)
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
    match mutation.expected_predecessor() {
        Some(expected_predecessor) => {
            bytes.push(1);
            bytes.extend_from_slice(expected_predecessor.as_array());
        }
        None => bytes.push(0),
    }
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