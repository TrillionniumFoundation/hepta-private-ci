//! Conservative cluster intervals for finite-horizon sequential point estimates.
//!
//! The underlying PDIS/DR implementation remains unchanged. This layer requires
//! a preregistered absolute trajectory-return envelope and treats cluster labels
//! as supplied evidence, not proof of independence. It is fixed-analysis only:
//! no anytime-valid, adaptive-stopping or causal-identification claim is added.

use std::collections::BTreeMap;

use super::*;
use crate::ClusterConfidencePlan;
use crate::OpeInterval;

impl SequentialPlan {
    /// Return `(point, PDIS interval, DR interval, confidence evidence digest)`.
    pub fn estimate_cluster_intervals_v1(
        &self,
        confidence: &ClusterConfidencePlan,
        maximum_absolute_trajectory_return: FixedQ32,
        trajectories: &[Trajectory],
    ) -> Result<(SequentialEstimate, OpeInterval, OpeInterval, Digest32), SequentialError> {
        if confidence.plan_digest.is_zero()
            || confidence.assumptions_digest.is_zero()
            || !(1..=100_000).contains(&confidence.family_alpha_ppm)
            || !(1..=1_024).contains(&confidence.simultaneous_comparisons)
            || confidence.minimum_clusters < 2
            || maximum_absolute_trajectory_return <= FixedQ32::ZERO
            || i128::from(maximum_absolute_trajectory_return.raw()) > 129 * SCALE
        {
            return Err(SequentialError::InvalidPlan);
        }
        let point = estimate_sequential(self, trajectories)?;
        let mut cluster_by_trajectory = BTreeMap::new();
        let mut sizes = BTreeMap::<StableId, usize>::new();
        for trajectory in trajectories {
            if cluster_by_trajectory
                .insert(
                    trajectory.trajectory_id.clone(),
                    trajectory.cluster_id.clone(),
                )
                .is_some()
            {
                return Err(SequentialError::DuplicateIdentity);
            }
            *sizes.entry(trajectory.cluster_id.clone()).or_default() += 1;
        }
        if sizes.len() < confidence.minimum_clusters {
            return Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::InsufficientClusters,
            ));
        }
        let envelope = i128::from(maximum_absolute_trajectory_return.raw());
        if point.trajectories.iter().any(|row| {
            i128::from(row.per_decision_importance_sampling.raw()).abs() > envelope
                || i128::from(row.doubly_robust.raw()).abs() > envelope
        }) {
            return Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::ConfidenceEnvelope,
            ));
        }
        let count = u128::try_from(trajectories.len()).map_err(|_| SequentialError::Arithmetic)?;
        let mut sum_squares = 0_u128;
        for size in sizes.values().copied() {
            let size = u128::try_from(size).map_err(|_| SequentialError::Arithmetic)?;
            sum_squares = sum_squares
                .checked_add(size * size)
                .ok_or(SequentialError::Arithmetic)?;
        }
        let probability_ratio = (4_000_000_u128 * u128::from(confidence.simultaneous_comparisons))
            .div_ceil(u128::from(confidence.family_alpha_ppm));
        let log_upper = u128::from((probability_ratio - 1).ilog2() + 1);
        let range = u128::try_from(envelope)
            .map_err(|_| SequentialError::Arithmetic)?
            .checked_mul(2)
            .ok_or(SequentialError::Arithmetic)?;
        let radius = confidence_radius(range, log_upper, sum_squares, count)?;
        let pdis = confidence_interval(point.per_decision_importance_sampling, radius)?;
        let dr = confidence_interval(point.doubly_robust, radius)?;

        let mut bytes = b"hepta.sequential.cluster-confidence.v1".to_vec();
        for digest in [
            point.evidence_digest,
            confidence.plan_digest,
            confidence.assumptions_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&confidence.family_alpha_ppm.to_be_bytes());
        bytes.extend_from_slice(&confidence.simultaneous_comparisons.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(confidence.minimum_clusters)
                .map_err(|_| SequentialError::Arithmetic)?
                .to_be_bytes(),
        );
        bytes.extend_from_slice(&maximum_absolute_trajectory_return.raw().to_be_bytes());
        for (trajectory, cluster) in cluster_by_trajectory {
            push_id(&mut bytes, &trajectory);
            push_id(&mut bytes, &cluster);
        }
        for interval in [pdis, dr] {
            bytes.extend_from_slice(&interval.lower.raw().to_be_bytes());
            bytes.extend_from_slice(&interval.upper.raw().to_be_bytes());
        }
        Ok((point, pdis, dr, Digest32::of_bytes(&bytes)))
    }
}

fn confidence_radius(
    range: u128,
    log_upper: u128,
    sum_squares: u128,
    count: u128,
) -> Result<i128, SequentialError> {
    let numerator = range
        .checked_mul(range)
        .and_then(|value| value.checked_mul(log_upper))
        .and_then(|value| value.checked_mul(sum_squares))
        .ok_or(SequentialError::Arithmetic)?;
    let denominator = count
        .checked_mul(count)
        .and_then(|value| value.checked_mul(2))
        .filter(|value| *value > 0)
        .ok_or(SequentialError::Arithmetic)?;
    let squared = numerator.div_ceil(denominator);
    let floor = squared.isqrt();
    let outward = floor
        .checked_add(u128::from(floor * floor < squared))
        .and_then(|value| value.checked_add(8))
        .ok_or(SequentialError::Arithmetic)?;
    i128::try_from(outward).map_err(|_| SequentialError::Arithmetic)
}

fn confidence_interval(center: FixedQ32, radius: i128) -> Result<OpeInterval, SequentialError> {
    Ok(OpeInterval {
        lower: fixed(i128::from(center.raw()) - radius)?,
        upper: fixed(i128::from(center.raw()) + radius)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn probability_one() -> ProbabilityQ32 {
        ProbabilityQ32::ONE
    }

    fn plan() -> SequentialPlan {
        SequentialPlan {
            plan_digest: digest("sequential-confidence-plan"),
            estimand: FiniteHorizonEstimand {
                horizon: 1,
                terminal_reward: TerminalRewardConvention::IncludedInLastReward,
                scope: TrajectoryClaimScope::Qualification,
            },
            behavior_policy: digest("behavior"),
            evaluation_policy: digest("evaluation"),
            observation_generation: Generation::new(1).expect("generation"),
            outcome_watermark: 20,
            minimum_trajectories: 2,
            minimum_depth_ess: FixedQ32::ONE,
            maximum_step_ratio: FixedQ32::ONE,
            maximum_cumulative_ratio: FixedQ32::ONE,
        }
    }

    fn confidence() -> ClusterConfidencePlan {
        ClusterConfidencePlan {
            plan_digest: digest("sequential-confidence"),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 100_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        }
    }

    fn trajectory(name: &str, cluster: &str, reward: FixedQ32) -> Trajectory {
        Trajectory {
            trajectory_id: id(name),
            cluster_id: id(cluster),
            initial_history: digest(&format!("history:{name}:0")),
            behavior_policy: digest("behavior"),
            evaluation_policy: digest("evaluation"),
            terminal_value: FixedQ32::ZERO,
            steps: vec![TrajectoryStep {
                decision_id: id(&format!("decision:{name}")),
                history_digest: digest(&format!("history:{name}:0")),
                next_history_digest: digest(&format!("history:{name}:1")),
                observation_generation: Generation::new(1).expect("generation"),
                complete_actions: true,
                actions: vec![TrajectoryAction {
                    action_id: id("action"),
                    behavior_probability: probability_one(),
                    evaluation_probability: probability_one(),
                    predicted_return: FixedQ32::ZERO,
                }],
                chosen_action: id("action"),
                reward: Some(reward),
                discount: probability_one(),
                boundary: TrajectoryBoundary::Terminal,
                observed_at: 10,
                outcome_evidence: digest(&format!("outcome:{name}")),
                prediction_evidence: digest(&format!("prediction:{name}")),
            }],
        }
    }

    fn rows() -> Vec<Trajectory> {
        vec![
            trajectory("a", "cluster-a", FixedQ32::from_raw(1_i64 << 30)),
            trajectory("b", "cluster-b", FixedQ32::from_raw(3_i64 << 30)),
        ]
    }

    #[test]
    fn cluster_intervals_cover_the_fixed_sequential_point_and_are_canonical() {
        let rows = rows();
        let result = plan()
            .estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &rows)
            .expect("intervals");
        assert!(result.1.lower <= result.0.per_decision_importance_sampling);
        assert!(result.1.upper >= result.0.per_decision_importance_sampling);
        assert!(result.2.lower <= result.0.doubly_robust);
        assert!(result.2.upper >= result.0.doubly_robust);
        let mut reversed = rows;
        reversed.reverse();
        assert_eq!(
            plan()
                .estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &reversed)
                .expect("reordered"),
            result
        );
    }

    #[test]
    fn insufficient_clusters_and_violated_envelopes_fail_closed() {
        let mut same_cluster = rows();
        same_cluster[1].cluster_id = same_cluster[0].cluster_id.clone();
        assert_eq!(
            plan().estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &same_cluster,),
            Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::InsufficientClusters,
            ))
        );
        assert_eq!(
            plan().estimate_cluster_intervals_v1(
                &confidence(),
                FixedQ32::from_raw(1_i64 << 29),
                &rows(),
            ),
            Err(SequentialError::InsufficientEvidence(
                SequentialEvidenceGap::ConfidenceEnvelope,
            ))
        );
    }
}
