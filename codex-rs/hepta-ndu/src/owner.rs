#[path = "owner_digests.rs"]
mod digests;
use digests::authenticated_evaluation_receipt_digest;
use digests::evaluation_source_context_digest;
use digests::mutation_payload_digest;
use digests::owner_scope_digest;
use digests::production_policy_digest;
use digests::validate_context;

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
    RevocationFrontierMismatch,
    JournalHeadMismatch,
    OperationAlreadyCommitted,
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
        let store = NduProjectionStoreV1::open(root.as_ref())?;
        super::owner_binding::bind_owner(
            root.as_ref(),
            &context,
            production_policy_digest,
            store.entries()?.is_empty(),
        )?;
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

    pub fn refresh_revocation_frontier(
        &mut self,
        revocation_frontier_digest: Digest32,
    ) -> Result<(), NduOwnerError> {
        if revocation_frontier_digest.is_zero() {
            return Err(NduOwnerError::InvalidContext("revocation frontier"));
        }
        self.context.revocation_frontier_digest = revocation_frontier_digest;
        Ok(())
    }

    pub fn evaluate(
        &self,
        contributions: ContributionSet,
    ) -> Result<NduAuthenticatedEvaluationReceiptV1, NduOwnerError> {
        self.require_current_frontier()?;
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
        self.require_current_frontier()?;
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
        match mutation.expected_predecessor() {
            Some(expected_predecessor) if expected_predecessor.is_zero() => {
                return Err(NduOwnerError::InvalidContext("selection predecessor"));
            }
            Some(_) | None => {}
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

    /// Current committed journal identity, including every selection and revocation.
    /// Binding this head, not only the selected content, prevents ABA admission.
    pub fn journal_head_digest(&self) -> Result<Digest32, NduOwnerError> {
        Ok(self
            .store
            .entries()?
            .last()
            .map_or(Digest32::ZERO, |entry| entry.entry_digest))
    }

    /// Historical committed result only; this does not authorize current use.
    pub fn mutation_result(
        &self,
        identity: Digest32,
    ) -> Result<Option<NduProjectionEntryV1>, NduOwnerError> {
        Ok(self
            .store
            .entries()?
            .iter()
            .find(|entry| entry.identity_digest == identity)
            .cloned())
    }

    pub fn final_use_binding_at_head(
        &self,
        mutation: &NduOwnerMutationV1,
        expected_head: Digest32,
    ) -> Result<FinalUseBinding, NduOwnerError> {
        let mut binding = self.final_use_binding(mutation)?;
        binding.payload_sha256 = *Digest32::of_parts(&[
            b"hepta.ndu.head-bound-mutation.v1\0",
            &binding.payload_sha256,
            expected_head.as_array(),
        ])
        .as_array();
        Ok(binding)
    }

    /// The product ingress uses this entry exclusively. A lost acknowledgement
    /// must be reconciled with `mutation_result`; it is not a new admission.
    pub fn apply_mutation_at_head(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
        expected_head: Digest32,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        self.apply_mutation_at_head_guarded(signed, mutation, expected_head, || Ok(()))
    }

    /// Rechecks the named product lifecycle after authority admission, at the
    /// actual mutation entry. The host supplies the current generation fence.
    pub fn apply_mutation_at_head_guarded(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
        expected_head: Digest32,
        final_guard: impl FnOnce() -> Result<(), NduOwnerError>,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        if self.journal_head_digest()? != expected_head {
            return Err(NduOwnerError::JournalHeadMismatch);
        }
        if self.mutation_result(mutation.identity_digest())?.is_some() {
            return Err(NduOwnerError::OperationAlreadyCommitted);
        }
        let expected = self.final_use_binding_at_head(&mutation, expected_head)?;
        self.apply_bound_mutation(signed, mutation, expected, final_guard)
    }

    fn require_current_frontier(&self) -> Result<(), NduOwnerError> {
        if Digest32::from_array(self.authority.revocation_head_sha256()?)
            != self.context.revocation_frontier_digest
        {
            return Err(NduOwnerError::RevocationFrontierMismatch);
        }
        Ok(())
    }

    pub fn apply_mutation(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        let expected = self.final_use_binding(&mutation)?;
        self.apply_bound_mutation(signed, mutation, expected, || Ok(()))
    }

    fn apply_bound_mutation(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
        expected: FinalUseBinding,
        final_guard: impl FnOnce() -> Result<(), NduOwnerError>,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        let authority = self.authority.clone();
        let token = authority.claim(signed, &expected)?;
        if Digest32::from_array(token.claimed_revocation_head_sha256())
            != self.context.revocation_frontier_digest
        {
            return Err(NduOwnerError::RevocationFrontierMismatch);
        }
        authority
            .with_verified_effect(token, &expected, || {
                final_guard()?;
                self.require_current_frontier()?;
                let result = match mutation {
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
                };
                result.map_err(NduOwnerError::Store)
            })
            .map_err(NduOwnerError::Authority)?
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

#[cfg(all(test, unix))]
#[path = "owner_tests.rs"]
mod tests;
