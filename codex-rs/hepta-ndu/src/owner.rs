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
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;
use codex_hepta_types::numeric_registry_v2::RegistrySnapshotIdentityV1;

use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::NduError;
use crate::NduEvaluationReceiptV2;
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

#[path = "owner_current.rs"]
mod current;
pub use current::NduCurrentProjectionV1;
pub use current::NduProjectionReadRequestV1;

#[path = "owner_numeric_snapshot.rs"]
mod numeric_snapshot;
pub use numeric_snapshot::NduRegisteredUtilitySignalV2;

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
        projection_digest: Digest32,
    },
    /// Explicit compare-and-set selection. The issuer binding also fixes the
    /// complete current journal head, so a value-level ABA cannot reuse a grant.
    SelectProjectionIfCurrent {
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
            | Self::SelectProjectionIfCurrent {
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
            | Self::SelectProjectionIfCurrent {
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
            | Self::SelectProjectionIfCurrent { subject_digest, .. }
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
            | Self::SelectProjectionIfCurrent {
                projection_digest, ..
            }
            | Self::RevokeProjection {
                projection_digest, ..
            } => *projection_digest,
        }
    }

    fn expected_predecessor(&self) -> Option<Digest32> {
        match self {
            Self::SelectProjectionIfCurrent {
                expected_predecessor,
                ..
            } => *expected_predecessor,
            Self::AppendProjection { .. }
            | Self::SelectProjection { .. }
            | Self::RevokeProjection { .. } => None,
        }
    }

    fn tag(&self) -> u8 {
        match self {
            Self::AppendProjection { .. } => 0,
            Self::SelectProjection { .. } | Self::SelectProjectionIfCurrent { .. } => 1,
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
    ReadTrust(codex_hepta_contracts::FinalUseControlError),
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
    numeric_registry: Option<NduNumericRegistryV1>,
    numeric_snapshot: Option<RegistrySnapshotIdentityV1>,
    authority: FinalUseAuthority,
    store: NduProjectionStoreV1,
    current_reads: Option<current::CurrentReadTrust>,
}

impl NduAuthenticatedOwnerV1 {
    pub fn open(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
    ) -> Result<Self, NduOwnerError> {
        Self::open_inner(
            root, authority, context, policy, /*numeric_registry*/ None,
            /*numeric_snapshot*/ None,
        )
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
        Self::open_inner(
            root,
            authority,
            context,
            policy,
            Some(numeric_registry),
            /*numeric_snapshot*/ None,
        )
    }

    fn open_inner(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
        numeric_registry: Option<NduNumericRegistryV1>,
        numeric_snapshot: Option<RegistrySnapshotIdentityV1>,
    ) -> Result<Self, NduOwnerError> {
        validate_context(&context)?;
        if let Some(registry) = &numeric_registry {
            crate::numeric_admission::validate_utility_axis_order(&policy.utility_profile)
                .map_err(|_| NduOwnerError::InvalidContext("numeric axis order"))?;
            registry
                .registry()
                .require_normalization(policy.utility_profile.normalization_manifest_digest)
                .map_err(|_| NduOwnerError::InvalidContext("numeric normalization"))?;
            registry
                .registry()
                .require_numeric_profile(NumericProfileV1::SignedQ32NearestTiesEven)
                .map_err(|_| NduOwnerError::InvalidContext("numeric target profile"))?;
        }
        let production_policy_digest = match (numeric_registry.as_ref(), numeric_snapshot) {
            (Some(registry), Some(snapshot)) => {
                numeric_snapshot::snapshot_policy_digest(&policy, registry, snapshot)?
            }
            (None, Some(_)) => {
                return Err(NduOwnerError::InvalidContext(
                    "numeric snapshot without registry",
                ));
            }
            (Some(registry), None) => {
                production_policy_digest_with_numeric_registry(&policy, registry.registry_digest())?
            }
            (None, None) => production_policy_digest(&policy)?,
        };
        let store = NduProjectionStoreV1::open_durable(root.as_ref())?;
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
            numeric_registry,
            numeric_snapshot,
            authority,
            store,
            current_reads: None,
        })
    }

    #[must_use]
    pub fn storage_ready(&self) -> bool {
        self.store.storage_ready()
    }

    #[must_use]
    pub const fn filesystem_profile(&self) -> &'static str {
        self.store.filesystem_profile()
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
        if self.numeric_snapshot.is_some() {
            return Err(NduOwnerError::InvalidContext(
                "V2 snapshot requires V2 admission",
            ));
        }
        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "numeric registry not configured",
            ))?;
        registry
            .admit_utility_signal(&self.policy.utility_profile, source)
            .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))
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
        if self.numeric_snapshot.is_some() {
            self.admit_snapshot_contributions(&mut contributions)?;
        } else if let Some(registry) = &self.numeric_registry {
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
                    .admit_utility_axes(&self.policy.utility_profile, &contribution.utility)
                    .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))?;
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

    /// Bind the ordinary registered evaluation to the live owner context.
    /// This is evidence only; it does not mint mutation or read authority.
    pub fn evaluate_authenticated(
        &self,
        contributions: ContributionSet,
    ) -> Result<NduAuthenticatedEvaluationReceiptV1, NduOwnerError> {
        self.require_current_frontier()?;
        let objective_digest = contributions.objective_digest;
        let generation = contributions.generation;
        let evaluation = self.evaluate(contributions)?;
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
        let payload_digest = match mutation {
            NduOwnerMutationV1::SelectProjection { .. }
            | NduOwnerMutationV1::SelectProjectionIfCurrent { .. } => {
                // V2 is deliberately distinct from every previously issued V1
                // selection payload. Issuers must prepare and sign a fresh binding.
                Digest32::of_parts(&[
                    b"hepta.ndu.selection-head-bound-mutation.v2\0",
                    payload_digest.as_array(),
                    self.journal_head_digest()?.as_array(),
                ])
            }
            NduOwnerMutationV1::AppendProjection { .. }
            | NduOwnerMutationV1::RevokeProjection { .. } => payload_digest,
        };
        Ok(FinalUseBinding {
            subject_id: self.context.principal_id.to_string(),
            destination_id: self.context.owner_id.to_string(),
            request_sha256: *mutation.identity_digest().as_array(),
            scope_sha256: *scope_digest.as_array(),
            payload_sha256: *payload_digest.as_array(),
        })
    }

    pub fn journal_head_digest(&self) -> Result<Digest32, NduOwnerError> {
        Ok(self
            .store
            .entries()?
            .last()
            .map_or(Digest32::ZERO, |entry| entry.entry_digest))
    }

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

    pub fn apply_mutation_at_head(
        &mut self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
        expected_head: Digest32,
    ) -> Result<NduProjectionEntryV1, NduOwnerError> {
        self.apply_mutation_at_head_guarded(signed, mutation, expected_head, || Ok(()))
    }

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
                        projection_digest,
                    } => {
                        let expected_predecessor = self
                            .store
                            .selected_projection_digest(objective_digest, subject_digest)?;
                        self.store.select_projection_if_current(
                            identity_digest,
                            objective_digest,
                            subject_digest,
                            expected_predecessor,
                            projection_digest,
                        )
                    }
                    NduOwnerMutationV1::SelectProjectionIfCurrent {
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

fn production_policy_digest_with_numeric_registry(
    policy: &NduProductionPolicyV1,
    registry_digest: Digest32,
) -> Result<Digest32, NduOwnerError> {
    if registry_digest.is_zero() {
        return Err(NduOwnerError::InvalidContext("numeric registry digest"));
    }
    let base = production_policy_digest(policy)?;
    Ok(Digest32::of_parts(&[
        b"hepta.ndu.production-policy.numeric-registry.v1\0",
        base.as_array(),
        registry_digest.as_array(),
    ]))
}

#[cfg(all(test, unix))]
#[path = "owner_tests.rs"]
mod tests;
