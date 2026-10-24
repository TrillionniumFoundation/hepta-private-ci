//! Full-information pairing, with no OPE or propensity field.
//! Seeds are repeated observations inside source cases, never independent cases.
use crate::paired_plan::FrozenPairedPlanV1;
use crate::paired_plan::PairedProfileError;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

const Q: i64 = 1_i64 << 32;
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedSourceCaseV1 {
    pub case_id: StableId,
    pub original_source_units: [Digest32; 2],
    pub public_context_digest: Digest32,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedVersionV1 {
    pub seed: u64,
    /// Whole model/checkpoint artifacts include inference configuration.
    pub candidate_artifact: Digest32,
    pub baseline_artifact: Digest32,
    /// Exact policy/configuration/forecaster manifests, not just display names.
    pub candidate_policy: Digest32,
    pub baseline_policy: Digest32,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedManifestV1 {
    pub cases: Vec<PairedSourceCaseV1>,
    pub versions: Vec<PairedVersionV1>,
    pub modeled_budget: FixedQ32,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum PairedArmV1 {
    Baseline,
    Candidate,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedObservationV1 {
    pub case_id: StableId,
    pub seed: u64,
    pub arm: PairedArmV1,
    pub public_context_digest: Digest32,
    pub model_artifact: Digest32,
    pub policy_digest: Digest32,
    pub modeled_budget: FixedQ32,
    pub actual_execution_receipt: Digest32,
    pub actual_observation_receipt: Digest32,
    pub observer_artifact: Digest32,
    pub metric_digest: Digest32,
    /// Bit0 text, bit1 image; absence is zero hash and never repaired.
    pub completed_modalities: u8,
    pub output_digests: [Digest32; 2],
    pub joint_loss: FixedQ32,
    pub joint_factual_success: bool,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedDataV1 {
    pub manifest: PairedManifestV1,
    /// Canonical complete order: case ID, seed, baseline then candidate.
    pub observations: Vec<PairedObservationV1>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedBoundedIntervalV1 {
    pub mean_floor: FixedQ32,
    pub mean_ceiling: FixedQ32,
    pub lower: FixedQ32,
    pub upper: FixedQ32,
    pub conservative_radius: FixedQ32,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedStatisticsV1 {
    pub source_cases: u32,
    pub fixed_seeds: u32,
    pub candidate_complete: u32,
    pub baseline_complete: u32,
    /// Absent if either arm did not actually deliver every required modality.
    pub loss_difference: Option<PairedBoundedIntervalV1>,
    pub factual_error_difference: Option<PairedBoundedIntervalV1>,
    /// Descriptive gate only; this engineering profile never qualifies a model.
    pub observed_thresholds_pass: bool,
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
fn put_digests(bytes: &mut Vec<u8>, values: &[Digest32]) {
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
}

impl PairedManifestV1 {
    /// Validate and hash context/version lists BEFORE any outcome release.
    pub fn digests(&self) -> Result<(Digest32, Digest32, Digest32), PairedProfileError> {
        if !(1..=4096).contains(&self.cases.len())
            || !(1..=32).contains(&self.versions.len())
            || self.modeled_budget.raw() <= 0
            || self.cases.windows(2).any(|p| p[0].case_id >= p[1].case_id)
            || self.versions.windows(2).any(|p| p[0].seed >= p[1].seed)
        {
            return Err(PairedProfileError("manifest order or bounds"));
        }
        let mut cohort = b"hepta.paired-full-information.source-cohort.v1".to_vec();
        let mut contexts = b"hepta.paired-full-information.contexts.v1".to_vec();
        let mut versions = b"hepta.paired-full-information.versions.v1".to_vec();
        let mut sources = BTreeSet::new();
        for case in &self.cases {
            if case.public_context_digest.is_zero()
                || case
                    .original_source_units
                    .iter()
                    .any(|d| d.is_zero() || !sources.insert(*d))
            {
                return Err(PairedProfileError("source units reused or absent"));
            }
            put_id(&mut contexts, &case.case_id);
            put_digests(&mut contexts, &case.original_source_units);
            put_digests(&mut contexts, &[case.public_context_digest]);
        }
        // Cohort reuse identity is independent of arm, labels, case names,
        // ordering, grouping, observation transform and measured outcomes.
        for source in sources {
            cohort.extend_from_slice(source.as_array());
        }
        contexts.extend_from_slice(&self.modeled_budget.raw().to_be_bytes());
        for version in &self.versions {
            let pins = [
                version.candidate_artifact,
                version.baseline_artifact,
                version.candidate_policy,
                version.baseline_policy,
            ];
            if pins.iter().any(|d| d.is_zero()) {
                return Err(PairedProfileError("missing version pin"));
            }
            versions.extend_from_slice(&version.seed.to_be_bytes());
            put_digests(&mut versions, &pins);
        }
        Ok((
            Digest32::of_bytes(&cohort),
            Digest32::of_bytes(&contexts),
            Digest32::of_bytes(&versions),
        ))
    }
    pub fn validate(&self, plan: &FrozenPairedPlanV1) -> Result<(), PairedProfileError> {
        plan.validate()?;
        let (cohort, contexts, versions) = self.digests()?;
        let spec = plan.spec();
        if self.cases.len() != spec.source_cases as usize
            || self.versions.len() != spec.seeds as usize
            || cohort != spec.holdout_digest
            || contexts != spec.context_manifest_digest
            || versions != spec.version_manifest_digest
        {
            return Err(PairedProfileError("frozen manifest binding"));
        }
        Ok(())
    }
}

impl PairedDataV1 {
    pub fn canonical_digest(&self) -> Result<Digest32, PairedProfileError> {
        let (cohort, contexts, versions) = self.manifest.digests()?;
        let expected = self.manifest.cases.len() * self.manifest.versions.len() * 2;
        if self.observations.len() != expected {
            return Err(PairedProfileError("complete paired census"));
        }
        let mut bytes = b"hepta.paired-full-information.actual-outcomes.v1".to_vec();
        put_digests(&mut bytes, &[cohort, contexts, versions]);
        for row in &self.observations {
            put_id(&mut bytes, &row.case_id);
            bytes.extend_from_slice(&row.seed.to_be_bytes());
            bytes.push(match row.arm {
                PairedArmV1::Baseline => 0,
                PairedArmV1::Candidate => 1,
            });
            put_digests(
                &mut bytes,
                &[
                    row.public_context_digest,
                    row.model_artifact,
                    row.policy_digest,
                    row.actual_execution_receipt,
                    row.actual_observation_receipt,
                    row.observer_artifact,
                    row.metric_digest,
                ],
            );
            bytes.extend_from_slice(&row.modeled_budget.raw().to_be_bytes());
            bytes.push(row.completed_modalities);
            put_digests(&mut bytes, &row.output_digests);
            bytes.extend_from_slice(&row.joint_loss.raw().to_be_bytes());
            bytes.push(u8::from(row.joint_factual_success));
        }
        Ok(Digest32::of_bytes(&bytes))
    }
    pub(crate) fn derive(
        &self,
        plan: &FrozenPairedPlanV1,
    ) -> Result<PairedStatisticsV1, PairedProfileError> {
        self.manifest.validate(plan)?;
        if self.canonical_digest()? != plan.spec().outcome_bundle_digest {
            return Err(PairedProfileError("frozen outcome bytes"));
        }
        let cases: BTreeMap<_, _> = self
            .manifest
            .cases
            .iter()
            .map(|x| (&x.case_id, x))
            .collect();
        let versions: BTreeMap<_, _> = self.manifest.versions.iter().map(|x| (x.seed, x)).collect();
        let mut executions = BTreeSet::new();
        let mut observations = BTreeSet::new();
        let mut complete = [0_u32; 2];
        let mut total_loss = 0_i128;
        let mut total_fact = 0_i128;
        let expected = self.manifest.cases.iter().flat_map(|case| {
            self.manifest.versions.iter().flat_map(move |v| {
                [
                    (&case.case_id, v.seed, PairedArmV1::Baseline),
                    (&case.case_id, v.seed, PairedArmV1::Candidate),
                ]
            })
        });
        for (row, key) in self.observations.iter().zip(expected) {
            if (&row.case_id, row.seed, row.arm) != key {
                return Err(PairedProfileError("missing duplicated or swapped pair"));
            }
            let case = cases[&row.case_id];
            let version = versions[&row.seed];
            let candidate = row.arm == PairedArmV1::Candidate;
            let model = if candidate {
                version.candidate_artifact
            } else {
                version.baseline_artifact
            };
            let policy = if candidate {
                version.candidate_policy
            } else {
                version.baseline_policy
            };
            if row.public_context_digest != case.public_context_digest
                || row.model_artifact != model
                || row.policy_digest != policy
                || row.modeled_budget != self.manifest.modeled_budget
                || row.observer_artifact != plan.spec().audit_observer_digest
                || row.metric_digest != plan.spec().metric_digest
                || row.completed_modalities & !3 != 0
                || row.actual_execution_receipt.is_zero()
                || row.actual_observation_receipt.is_zero()
                || !executions.insert(row.actual_execution_receipt)
                || !observations.insert(row.actual_observation_receipt)
                || !(0..=Q).contains(&row.joint_loss.raw())
            {
                return Err(PairedProfileError(
                    "paired context version budget observer or score binding",
                ));
            }
            for (slot, digest) in row.output_digests.iter().enumerate() {
                if digest.is_zero() == (row.completed_modalities & (1 << slot) != 0) {
                    return Err(PairedProfileError("required output evidence mismatch"));
                }
            }
            if row.joint_factual_success && row.completed_modalities != 3 {
                return Err(PairedProfileError("factual success without outputs"));
            }
            complete[usize::from(candidate)] += u32::from(row.completed_modalities == 3);
            let sign = if candidate { 1_i128 } else { -1 };
            total_loss += sign * i128::from(row.joint_loss.raw());
            total_fact += sign * i128::from(u8::from(!row.joint_factual_success)) * i128::from(Q);
        }
        let n = plan.spec().source_cases;
        let seeds = plan.spec().seeds;
        let mut result = PairedStatisticsV1 {
            source_cases: n,
            fixed_seeds: seeds,
            baseline_complete: complete[0],
            candidate_complete: complete[1],
            loss_difference: None,
            factual_error_difference: None,
            observed_thresholds_pass: false,
        };
        if complete == [n * seeds; 2] {
            let radius = conservative_radius(
                n,
                plan.spec().family_alpha_ppm,
                plan.spec().simultaneous_comparisons,
            );
            let loss = interval(total_loss, n * seeds, radius);
            let fact = interval(total_fact, n * seeds, radius);
            result.observed_thresholds_pass = loss.upper.raw()
                < -plan.spec().minimum_loss_improvement.raw()
                && fact.upper.raw() <= plan.spec().maximum_fact_error_increase.raw();
            result.loss_difference = Some(loss);
            result.factual_error_difference = Some(fact);
        }
        Ok(result)
    }
}

/// Conservative integer Hoeffding bound: ceil(log2(2m/alpha)) >= ln(2m/alpha).
/// Binary search rounds sqrt(2*k/n)*Q UP; there is no floating-point certificate.
fn conservative_radius(n: u32, alpha_ppm: u32, comparisons: u32) -> i64 {
    let ratio = (2_u64 * u64::from(comparisons) * 1_000_000).div_ceil(u64::from(alpha_ppm));
    let k = u128::from(64 - (ratio - 1).leading_zeros());
    // Radius >= 2 already yields the deterministic full [-1,1] range.
    // Saturating at 1 would be invalid near an observed mean of +/-1.
    if 2 * k >= 4 * u128::from(n) {
        return 2 * Q;
    }
    let target = 2 * k * (Q as u128).pow(2);
    let (mut low, mut high) = (0_u128, 2 * Q as u128);
    while low < high {
        let middle = (low + high) / 2;
        if middle * middle * u128::from(n) >= target {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    high as i64
}
fn interval(total: i128, count: u32, radius: i64) -> PairedBoundedIntervalV1 {
    let low = total.div_euclid(i128::from(count)) as i64;
    let high = -(-total).div_euclid(i128::from(count)) as i64;
    PairedBoundedIntervalV1 {
        mean_floor: FixedQ32::from_raw(low),
        mean_ceiling: FixedQ32::from_raw(high),
        lower: FixedQ32::from_raw((low - radius).max(-Q)),
        upper: FixedQ32::from_raw((high + radius).min(Q)),
        conservative_radius: FixedQ32::from_raw(radius),
    }
}

#[cfg(test)]
#[path = "paired_data_tests.rs"]
pub(crate) mod tests;
