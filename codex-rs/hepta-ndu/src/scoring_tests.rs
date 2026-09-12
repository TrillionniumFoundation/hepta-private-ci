use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::dominates;
use super::pareto_frontier;
use crate::AxisDirection;
use crate::AxisValue;
use crate::CandidateUtility;
use crate::ContributionSet;
use crate::EvaluationDisposition;
use crate::FeasibilityPosture;
use crate::RequiredOrganSet;
use crate::ScalarizationProfile;
use crate::UtilityContribution;
use crate::UtilityProfile;
use crate::evaluate_candidates_with_policy;
use crate::legacy_evaluation_policy;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test identifier")
}

fn axes() -> [StableId; 3] {
    [id("x"), id("y"), id("z")]
}

fn candidate(name: &str, quarters: [i64; 3]) -> CandidateUtility {
    CandidateUtility {
        candidate_id: id(name),
        utility: axes()
            .into_iter()
            .zip(quarters)
            .map(|(axis, value)| AxisValue {
                axis,
                value: FixedQ32::from_raw(value * (1 << 30)),
            })
            .collect(),
        risk: vec![],
        resource: vec![],
        uncertainty: axes()
            .into_iter()
            .map(|axis| AxisValue {
                axis,
                value: FixedQ32::ZERO,
            })
            .collect(),
        support_digest: Digest32::of_bytes(name.as_bytes()),
        scalar_score: None,
    }
}

#[test]
fn cyclic_tolerance_counterexample_retains_frontier_in_every_input_order() {
    let rows = [
        candidate("a", [2, 1, 0]),
        candidate("b", [0, 2, 1]),
        candidate("c", [1, 0, 2]),
        candidate("abstain", [0, 0, 0]),
    ];
    let profile = UtilityProfile {
        profile_id: id("three-axis-profile"),
        dimensions: axes()
            .into_iter()
            .map(|axis| (axis, AxisDirection::Maximize))
            .collect(),
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("observed-owner")],
        },
    };
    let mut policy = legacy_evaluation_policy(&profile).expect("valid profile");
    for axis in &mut policy.pareto_absolute_tolerances {
        axis.value = FixedQ32::from_raw(1 << 30);
    }
    let contributions: Vec<_> = rows
        .iter()
        .map(|row| UtilityContribution {
            candidate_id: row.candidate_id.clone(),
            organ_id: id("observed-owner"),
            objective_digest: Digest32::of_bytes(b"objective"),
            generation: Generation::new(1).expect("valid generation"),
            feasibility: FeasibilityPosture::Feasible,
            utility: row.utility.clone(),
            risk: vec![],
            resource: vec![],
            uncertainty: row.uncertainty.clone(),
            support_digest: row.support_digest,
        })
        .collect();
    // Also exercise scalarization: the old empty frontier incorrectly returned
    // IncompleteScalarization for this complete one-axis weighting.
    for scalarization in [
        None,
        Some(ScalarizationProfile {
            profile_id: id("x-weighted"),
            weights: axes()
                .into_iter()
                .enumerate()
                .map(|(index, axis)| AxisValue {
                    axis,
                    value: if index == 0 {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    },
                })
                .collect(),
        }),
    ] {
        let mut expected = None;
        for a in 0..4 {
            for b in 0..4 {
                for c in 0..4 {
                    for d in 0..4 {
                        if [a, b, c, d]
                            .into_iter()
                            .collect::<std::collections::BTreeSet<_>>()
                            .len()
                            != 4
                        {
                            continue;
                        }
                        let receipt = evaluate_candidates_with_policy(
                            ContributionSet {
                                objective_digest: Digest32::of_bytes(b"objective"),
                                generation: Generation::new(1).expect("valid generation"),
                                contributions: [a, b, c, d]
                                    .map(|index| contributions[index].clone())
                                    .to_vec(),
                            },
                            profile.clone(),
                            scalarization.clone(),
                            policy.clone(),
                        )
                        .expect("nonempty feasible frontier");
                        assert_eq!(
                            receipt
                                .base
                                .pareto_frontier
                                .iter()
                                .map(|row| row.candidate_id.clone())
                                .collect::<Vec<_>>(),
                            vec![id("a"), id("b"), id("c")]
                        );
                        assert_eq!(
                            receipt.base.disposition,
                            if scalarization.is_some() {
                                EvaluationDisposition::ScalarizedRecommendation
                            } else {
                                EvaluationDisposition::ParetoSetRequiresSlowPath
                            }
                        );
                        if let Some(first) = &expected {
                            assert_eq!(&receipt, first);
                        } else {
                            expected = Some(receipt);
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn mixed_direction_dominance_is_irreflexive_transitive_and_has_maximal_elements() {
    let dimensions = vec![
        (id("x"), AxisDirection::Maximize),
        (id("y"), AxisDirection::Minimize),
        (id("z"), AxisDirection::Maximize),
    ];
    let tolerances: BTreeMap<_, _> = axes()
        .into_iter()
        .map(|axis| (axis, FixedQ32::from_raw(1 << 30)))
        .collect();
    let mut rows = Vec::new();
    for x in -1..=1 {
        for y in -1..=1 {
            for z in -1..=1 {
                rows.push(candidate(&format!("point-{}", rows.len()), [x, y, z]));
            }
        }
    }
    for a in &rows {
        assert!(!dominates(a, a, &dimensions, &tolerances));
        for b in &rows {
            if !dominates(a, b, &dimensions, &tolerances) {
                continue;
            }
            assert!(!dominates(b, a, &dimensions, &tolerances));
            for c in &rows {
                if dominates(b, c, &dimensions, &tolerances) {
                    assert!(dominates(a, c, &dimensions, &tolerances));
                }
            }
        }
    }
    for prefix in 1..=rows.len() {
        assert!(!pareto_frontier(&rows[..prefix], &dimensions, &tolerances).is_empty());
    }
    // A small worsening on the minimize axis cannot buy a large improvement
    // elsewhere, even when that worsening fits the tolerance.
    assert!(!dominates(
        &candidate("tradeoff", [2, 1, 0]),
        &candidate("baseline", [0, 0, 0]),
        &dimensions,
        &tolerances,
    ));
}
