//! Explicit V2 numeric admission inside the existing authenticated NDU owner.
//! Snapshot provisioning is external; an owner never learns freshness from a receipt.

use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;
use codex_hepta_types::numeric_registry_v2::RegisteredNumericConversionReceiptV2;
use codex_hepta_types::numeric_registry_v2::RegistrySnapshotIdentityV1;
use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_v2;

use super::NduAuthenticatedOwnerV1;
use super::NduOwnerContextV1;
use super::NduOwnerError;
use super::NduProductionPolicyV1;
use crate::AxisValue;
use crate::ContributionSet;
use crate::NduError;
use crate::NduNumericRegistryV1;
use crate::numeric_admission::utility_axis_values;
use crate::numeric_admission::utility_signal_from_axes;
use crate::numeric_admission::utility_target_schema;

/// Verified numeric evidence, never a writer capability or final-use grant.
/// Private fields prevent substituting axis values after owner admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduRegisteredUtilitySignalV2 {
    signal: NumericSignalV1,
    axis_values: Vec<AxisValue>,
    admission: RegisteredNumericConversionReceiptV2,
}

impl NduRegisteredUtilitySignalV2 {
    #[must_use]
    pub fn signal(&self) -> &NumericSignalV1 {
        &self.signal
    }

    #[must_use]
    pub fn axis_values(&self) -> &[AxisValue] {
        &self.axis_values
    }

    #[must_use]
    pub fn admission(&self) -> &RegisteredNumericConversionReceiptV2 {
        &self.admission
    }
}

impl NduAuthenticatedOwnerV1 {
    /// Pin a separately provisioned snapshot for this immutable owner lifetime.
    /// Validation precedes opening the existing store. This neither authenticates
    /// the supplied snapshot nor publishes, advances or persists a current generation.
    pub fn open_with_numeric_registry_snapshot(
        root: impl AsRef<Path>,
        authority: FinalUseAuthority,
        context: NduOwnerContextV1,
        policy: NduProductionPolicyV1,
        numeric_registry: NduNumericRegistryV1,
        expected_snapshot: RegistrySnapshotIdentityV1,
    ) -> Result<Self, NduOwnerError> {
        Self::open_inner(
            root,
            authority,
            context,
            policy,
            Some(numeric_registry),
            Some(expected_snapshot),
        )
    }

    #[must_use]
    pub const fn numeric_registry_snapshot(&self) -> Option<RegistrySnapshotIdentityV1> {
        self.numeric_snapshot
    }

    /// Issue V2 evidence through the shared converter, using only the owner's pin.
    /// Fresh locally constructed receipts need no second arithmetic conversion.
    pub fn admit_utility_signal_v2(
        &self,
        source: &NumericSignalV1,
    ) -> Result<NduRegisteredUtilitySignalV2, NduOwnerError> {
        let snapshot = self.numeric_snapshot.ok_or(NduOwnerError::InvalidContext(
            "numeric V2 snapshot not configured",
        ))?;
        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "numeric registry not configured",
            ))?;
        snapshot
            .verify_registry(registry.registry())
            .map_err(|_| NduOwnerError::InvalidContext("numeric snapshot registry"))?;
        let target = utility_target_schema(&self.policy.utility_profile, source)
            .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))?;
        let (signal, admission) = rescale_signal_registered_v2(
            source,
            &target,
            registry.registry(),
            snapshot.generation(),
        )
        .map_err(|_| NduOwnerError::InvalidContext("numeric V2 admission"))?;
        let axis_values = utility_axis_values(&self.policy.utility_profile, &signal);
        Ok(NduRegisteredUtilitySignalV2 {
            signal,
            axis_values,
            admission,
        })
    }

    /// Recompute received evidence against this owner's pin, never the receipt's
    /// embedded generation. Old-generation, wrong-registry and substituted-input
    /// receipts reject even when they pass self-contained verification.
    pub fn verify_utility_signal_v2(
        &self,
        source: &NumericSignalV1,
        receipt: &RegisteredNumericConversionReceiptV2,
    ) -> Result<NduRegisteredUtilitySignalV2, NduOwnerError> {
        let snapshot = self.numeric_snapshot.ok_or(NduOwnerError::InvalidContext(
            "numeric V2 snapshot not configured",
        ))?;
        let registry = self
            .numeric_registry
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "numeric registry not configured",
            ))?;
        let target = utility_target_schema(&self.policy.utility_profile, source)
            .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))?;
        let signal = receipt
            .verify_for_snapshot(source, &target, registry.registry(), snapshot)
            .map_err(|_| NduOwnerError::InvalidContext("numeric snapshot receipt"))?;
        let axis_values = utility_axis_values(&self.policy.utility_profile, &signal);
        Ok(NduRegisteredUtilitySignalV2 {
            signal,
            axis_values,
            admission: receipt.clone(),
        })
    }

    pub(super) fn admit_snapshot_contributions(
        &self,
        contributions: &mut ContributionSet,
    ) -> Result<(), NduOwnerError> {
        let support_type = StableId::with_profile(
            "utility.ndu:registered-contribution-support-v2",
            codex_hepta_types::IdProfileV1::Namespaced,
        )
        .map_err(|_| NduOwnerError::InvalidContext("numeric support type"))?;
        for contribution in &mut contributions.contributions {
            if contribution.support_digest.is_zero() {
                return Err(NduError::EmptySupportDigest {
                    candidate: contribution.candidate_id.to_string(),
                    organ: contribution.organ_id.to_string(),
                }
                .into());
            }
            let source =
                utility_signal_from_axes(&self.policy.utility_profile, &contribution.utility)
                    .map_err(|_| NduOwnerError::InvalidContext("numeric admission"))?;
            let admitted = self.admit_utility_signal_v2(&source)?;
            let fields = [
                CanonicalFieldV1 {
                    name: "numeric_admission",
                    value: CanonicalValueV1::Digest(admitted.admission.admission_digest()),
                },
                CanonicalFieldV1 {
                    name: "source_support",
                    value: CanonicalValueV1::Digest(contribution.support_digest),
                },
            ];
            contribution.support_digest =
                canonical_digest_v1(&support_type, /*schema_version*/ 2, &fields)
                    .map_err(|_| NduOwnerError::InvalidContext("numeric support encoding"))?;
            contribution.utility = admitted.axis_values;
        }
        Ok(())
    }
}

pub(super) fn snapshot_policy_digest(
    policy: &NduProductionPolicyV1,
    registry: &NduNumericRegistryV1,
    snapshot: RegistrySnapshotIdentityV1,
) -> Result<Digest32, NduOwnerError> {
    snapshot
        .verify_registry(registry.registry())
        .map_err(|_| NduOwnerError::InvalidContext("numeric snapshot registry"))?;
    let policy_digest = super::production_policy_digest(policy)?;
    let type_id = StableId::with_profile(
        "utility.ndu:production-policy-numeric-snapshot-v2",
        codex_hepta_types::IdProfileV1::Namespaced,
    )
    .map_err(|_| NduOwnerError::InvalidContext("numeric snapshot policy type"))?;
    let fields = [
        CanonicalFieldV1 {
            name: "policy_digest",
            value: CanonicalValueV1::Digest(policy_digest),
        },
        CanonicalFieldV1 {
            name: "registry_digest",
            value: CanonicalValueV1::Digest(snapshot.registry_digest()),
        },
        CanonicalFieldV1 {
            name: "registry_generation",
            value: CanonicalValueV1::U64(snapshot.generation().get()),
        },
    ];
    canonical_digest_v1(&type_id, /*schema_version*/ 2, &fields)
        .map_err(|_| NduOwnerError::InvalidContext("numeric snapshot policy encoding"))
}

#[cfg(all(test, unix))]
#[path = "owner_numeric_snapshot_tests.rs"]
mod tests;
