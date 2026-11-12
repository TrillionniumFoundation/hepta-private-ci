//! Label release stays private to the Root custodian and its concrete original
//! file-backed runner. A generic CAS proof is not a Root custody capability.
//! The provider cannot be exported to a caller-supplied in-memory owner.

use std::io;

use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::OriginalFinalHoldoutConsumptionV1;
use codex_hepta_intelligence_eval::ProductProviderErrorV1;
use codex_hepta_intelligence_eval::TemporalComparisonInputsV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::CellEvaluationPlanV1;

use super::admission::OriginalBAuthorities;
use super::deployment::OriginalBInputs;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalBReleasedSource {
    source: [u8; 32],
    observed: [u8; 32],
    policy: [u8; 32],
}

impl OriginalBReleasedSource {
    /// Hashes of already authenticated data, not a release capability.
    pub(super) fn from_original_digests(
        source: Digest32,
        observed: Digest32,
        policy: Digest32,
    ) -> Self {
        Self {
            source: source.into_array(),
            observed: observed.into_array(),
            policy: policy.into_array(),
        }
    }

    pub(super) fn require_original(&self, files: &OriginalBInputs) -> io::Result<()> {
        files
            .source
            .require_digest(Digest32::from_array(self.source), 1_048_576)?;
        files
            .observed_statement
            .require_digest(Digest32::from_array(self.observed), 65_536)?;
        files
            .policy_statement
            .require_digest(Digest32::from_array(self.policy), 65_536)?;
        Ok(())
    }
}

pub(super) struct OriginalBProvider<'a> {
    files: &'a OriginalBInputs,
    authorities: &'a OriginalBAuthorities,
    plan: &'a CellEvaluationPlanV1,
    namespace: Digest32,
    unit_profile: Digest32,
    registered_at: u64,
    clock: &'a dyn Fn() -> io::Result<u64>,
    admitted: &'a OriginalBReleasedSource,
    released: Option<OriginalBReleasedSource>,
    attempted: bool,
}

impl<'a> OriginalBProvider<'a> {
    pub(super) fn new(
        files: &'a OriginalBInputs,
        authorities: &'a OriginalBAuthorities,
        plan: &'a CellEvaluationPlanV1,
        namespace: Digest32,
        unit_profile: Digest32,
        registered_at: u64,
        clock: &'a dyn Fn() -> io::Result<u64>,
        admitted: &'a OriginalBReleasedSource,
    ) -> Self {
        Self {
            files,
            authorities,
            plan,
            namespace,
            unit_profile,
            registered_at,
            clock,
            admitted,
            released: None,
            attempted: false,
        }
    }

    pub(super) fn into_original_release(self) -> io::Result<OriginalBReleasedSource> {
        let original = self
            .released
            .ok_or_else(|| io::Error::other("original B release was not completed"))?;
        original.require_original(self.files)?;
        Ok(original)
    }
}

impl FinalHoldoutProviderV1 for OriginalBProvider<'_> {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        // This is the original frozen protocol, not a premature label read.
        Ok(self.plan.product_plan().frozen_plan.final_holdout_digest)
    }

    fn release_after_original_consumption(
        &mut self,
        consumed: OriginalFinalHoldoutConsumptionV1<'_>,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if self.attempted {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.attempted = true;
        consumed.with_current_consumption(|namespace, plan, _receipt| {
            if namespace != self.namespace || plan != &self.plan.product_plan().frozen_plan {
                return Err(ProductProviderErrorV1::Rejected);
            }
            let result = (|| {
                self.files.require_original_files()?;
                self.admitted.require_original(self.files)?;
                let admitted = self.authorities.require_source(
                    &self.files.source,
                    &self.files.observed_statement,
                    &self.files.policy_statement,
                    self.registered_at,
                    (self.clock)()?,
                )?;
                let data = &admitted.data;
                if data.unit_profile != self.unit_profile.into_array()
                    || data.objective != plan.objective_digest.into_array()
                    || data.original_dataset != plan.dataset_digest.into_array()
                    || data.candidate_bundle != self.plan.record().candidate.manifest.bundle_digest
                    || data.baseline_bundle
                        != self.plan.record().fixed_expert.manifest.bundle_digest
                    || data.manifest_digest()? != plan.final_holdout_digest
                {
                    return Err(io::Error::other(
                        "original B source differs from its frozen plan",
                    ));
                }
                let inputs = data.inputs()?;
                let original = OriginalBReleasedSource {
                    source: admitted.source_digest.into_array(),
                    observed: admitted.observed_digest.into_array(),
                    policy: admitted.policy_digest.into_array(),
                };
                original.require_original(self.files)?;
                if &original != self.admitted {
                    return Err(io::Error::other(
                        "released B source differs from original admission",
                    ));
                }
                self.files.require_original_files()?;
                self.released = Some(original);
                Ok(inputs)
            })();
            result.map_err(|_: io::Error| ProductProviderErrorV1::Indeterminate)
        })
    }
}
