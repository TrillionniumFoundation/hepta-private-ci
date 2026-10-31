//! Synthetic unit cases, not scientific observations.
use super::*;
use crate::paired_owner_tests::d;
use crate::paired_owner_tests::id;
use crate::paired_owner_tests::paired;
use crate::paired_plan::freeze_paired_plan_v1;

pub(crate) fn fixture() -> (FrozenPairedPlanV1, PairedDataV1) {
    let manifest = PairedManifestV1 {
        cases: (0..2)
            .map(|i| PairedSourceCaseV1 {
                case_id: id(&format!("case-{i}")),
                original_source_units: [d(&format!("pixel-{i}-a")), d(&format!("pixel-{i}-b"))],
                public_context_digest: d(&format!("context-{i}")),
            })
            .collect(),
        versions: [17, 29]
            .iter()
            .map(|seed| PairedVersionV1 {
                seed: *seed,
                candidate_artifact: d(&format!("candidate-{seed}")),
                baseline_artifact: d(&format!("baseline-{seed}")),
                candidate_policy: d("candidate-policy"),
                baseline_policy: d("baseline-policy"),
            })
            .collect(),
        modeled_budget: FixedQ32::from_raw(64 * Q),
    };
    let mut rows = Vec::new();
    for case in &manifest.cases {
        for version in &manifest.versions {
            for arm in [PairedArmV1::Baseline, PairedArmV1::Candidate] {
                let candidate = arm == PairedArmV1::Candidate;
                let token = format!("{}-{}-{arm:?}", case.case_id, version.seed);
                rows.push(PairedObservationV1 {
                    case_id: case.case_id.clone(),
                    seed: version.seed,
                    arm,
                    public_context_digest: case.public_context_digest,
                    model_artifact: if candidate {
                        version.candidate_artifact
                    } else {
                        version.baseline_artifact
                    },
                    policy_digest: if candidate {
                        version.candidate_policy
                    } else {
                        version.baseline_policy
                    },
                    modeled_budget: manifest.modeled_budget,
                    actual_execution_receipt: d(&format!("exec-{token}")),
                    actual_observation_receipt: d(&format!("observation-{token}")),
                    observer_artifact: d("audit-b"),
                    metric_digest: d("metric"),
                    completed_modalities: 3,
                    output_digests: [d(&format!("text-{token}")), d(&format!("image-{token}"))],
                    joint_loss: FixedQ32::from_raw(if candidate { Q / 4 } else { 3 * Q / 4 }),
                    joint_factual_success: candidate,
                });
            }
        }
    }
    let data = PairedDataV1 {
        manifest,
        observations: rows,
    };
    let mut spec = paired("paired-evaluation").spec().clone();
    let (cohort, contexts, versions) = data.manifest.digests().expect("manifest");
    spec.holdout_digest = cohort;
    spec.context_manifest_digest = contexts;
    spec.version_manifest_digest = versions;
    spec.source_cases = 2;
    spec.outcome_bundle_digest = data.canonical_digest().expect("data");
    (freeze_paired_plan_v1(spec).expect("plan"), data)
}
fn rebind(plan: &FrozenPairedPlanV1, data: &PairedDataV1) -> FrozenPairedPlanV1 {
    let mut spec = plan.spec().clone();
    spec.outcome_bundle_digest = data.canonical_digest().expect("census retained");
    freeze_paired_plan_v1(spec).expect("valid new declared bundle")
}

#[test]
fn two_executed_outcomes_are_allowed_but_seeds_are_not_extra_cases() {
    let (plan, data) = fixture();
    let stats = data
        .derive(&plan)
        .expect("genuinely different paired outcomes");
    assert_eq!(stats.source_cases, 2);
    assert_eq!(stats.fixed_seeds, 2);
    assert_eq!(stats.candidate_complete, 4);
    let loss = stats.loss_difference.expect("loss");
    assert_eq!(loss.mean_floor.raw(), -Q / 2);
    assert_eq!(loss.mean_ceiling.raw(), -Q / 2);
    assert_eq!((loss.lower.raw(), loss.upper.raw()), (-Q, Q));
    assert!(!stats.observed_thresholds_pass);
}

#[test]
fn verified_full_census_rejects_context_version_metric_budget_or_receipt_changes() {
    let (plan, data) = fixture();
    for field in 0..7 {
        let mut changed = data.clone();
        match field {
            0 => changed.observations[1].public_context_digest = d("other-context"),
            1 => changed.observations[1].model_artifact = d("other-model"),
            2 => changed.observations[1].metric_digest = d("other-metric"),
            3 => changed.observations[1].modeled_budget = FixedQ32::from_raw(65 * Q),
            4 => {
                changed.observations[1].actual_execution_receipt =
                    changed.observations[0].actual_execution_receipt
            }
            5 => changed.observations[1].observer_artifact = d("reward-a"),
            _ => changed.observations.swap(0, 1),
        }
        assert!(changed.derive(&rebind(&plan, &changed)).is_err());
    }
    let mut omitted = data.clone();
    omitted.observations.pop();
    assert!(omitted.canonical_digest().is_err());
    let mut duplicate = data;
    duplicate.observations[1] = duplicate.observations[0].clone();
    assert!(duplicate.derive(&rebind(&plan, &duplicate)).is_err());
}

#[test]
fn source_cohort_reuse_identity_survives_case_renaming_and_missing_outputs_never_qualify() {
    let (plan, data) = fixture();
    let original = data.manifest.digests().expect("digests").0;
    let mut renamed = data.manifest.clone();
    renamed.cases[0].case_id = id("renamed-a");
    renamed.cases[1].case_id = id("renamed-b");
    assert_eq!(renamed.digests().expect("renamed").0, original);
    let mut remapped = data.manifest.clone();
    let first_pair = remapped.cases[0].original_source_units;
    remapped.cases[0].original_source_units = remapped.cases[1].original_source_units;
    remapped.cases[1].original_source_units = first_pair;
    let remapped_pins = remapped
        .digests()
        .expect("all original sources still unique");
    assert_eq!(remapped_pins.0, original);
    assert_ne!(
        remapped_pins.1,
        data.manifest.digests().expect("original").1
    );
    assert!(remapped.validate(&plan).is_err());
    let mut reused = data.manifest.clone();
    reused.cases[1].original_source_units[0] = reused.cases[0].original_source_units[0];
    assert!(reused.digests().is_err());
    let mut missing = data;
    missing.observations[1].completed_modalities = 1;
    missing.observations[1].output_digests[1] = Digest32::ZERO;
    missing.observations[1].joint_factual_success = false;
    let stats = missing
        .derive(&rebind(&plan, &missing))
        .expect("honest missing output");
    assert_eq!(stats.candidate_complete, 3);
    assert!(stats.loss_difference.is_none() && stats.factual_error_difference.is_none());
    assert!(!stats.observed_thresholds_pass);
}

#[test]
fn bounded_interval_outward_rounding_and_small_sample_clipping_are_conservative() {
    let radius = conservative_radius(60, 50_000, 32);
    let r = radius as i128;
    // ceil(log2(1280)) = 11; exact integer inequalities prove upward sqrt rounding.
    let target = 22_i128 * i128::from(Q).pow(2);
    assert!(r * r * 60 >= target && (r - 1) * (r - 1) * 60 < target);
    let small = interval(i128::from(Q), 1, conservative_radius(1, 50_000, 2));
    assert_eq!((small.lower.raw(), small.upper.raw()), (-Q, Q));
    let negative = interval(-1, 3, 0);
    assert_eq!(
        (negative.mean_floor.raw(), negative.mean_ceiling.raw()),
        (-1, 0)
    );
}
