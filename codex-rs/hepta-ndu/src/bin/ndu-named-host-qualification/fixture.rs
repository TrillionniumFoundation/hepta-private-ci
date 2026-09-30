use super::*;

pub(super) fn fixture(
    candidate_count: usize,
    organ_count: usize,
    utility_axes: usize,
    risk_resource_axes: usize,
) -> Result<EvaluationFixture, Box<dyn Error>> {
    let objective = digest("benchmark-objective");
    let generation = Generation::new(1)?;
    let organs = (0..organ_count)
        .map(|index| stable(&format!("organ-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let utility_ids = (0..utility_axes)
        .map(|index| stable(&format!("utility-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let risk_ids = (0..risk_resource_axes)
        .map(|index| stable(&format!("risk-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;
    let resource_ids = (0..risk_resource_axes)
        .map(|index| stable(&format!("resource-{index:02}")))
        .collect::<Result<Vec<_>, _>>()?;

    let mut contributions = Vec::with_capacity(candidate_count * organ_count);
    for candidate_index in 0..candidate_count {
        let candidate = if candidate_index == 0 {
            stable("abstain")?
        } else {
            stable(&format!("candidate-{candidate_index:03}"))?
        };
        for organ in &organs {
            let score = if candidate_index == 0 {
                FixedQ32::ZERO
            } else {
                q32(candidate_index as i64)
            };
            contributions.push(UtilityContribution {
                candidate_id: candidate.clone(),
                organ_id: organ.clone(),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: utility_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue { axis, value: score })
                    .collect(),
                risk: risk_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                resource: resource_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                uncertainty: utility_ids
                    .iter()
                    .cloned()
                    .map(|axis| AxisValue {
                        axis,
                        value: FixedQ32::ZERO,
                    })
                    .collect(),
                support_digest: digest(&format!("{candidate_index}-{}", organ.as_str())),
            });
        }
    }

    let profile = UtilityProfile {
        profile_id: stable("named-host-benchmark-v1")?,
        axis_registry_digest: digest("named-host-benchmark-axis-registry"),
        normalization_manifest_digest: digest("named-host-benchmark-normalization"),
        dimensions: utility_ids
            .iter()
            .cloned()
            .map(|axis| (axis, AxisDirection::Maximize))
            .collect(),
        risk_ceilings: risk_ids
            .iter()
            .cloned()
            .map(|axis| AxisLimit {
                axis,
                maximum: FixedQ32::ZERO,
            })
            .collect(),
        resource_ceilings: resource_ids
            .iter()
            .cloned()
            .map(|axis| AxisLimit {
                axis,
                maximum: FixedQ32::ZERO,
            })
            .collect(),
        required_organs: RequiredOrganSet { organ_ids: organs },
    };
    let policy = EvaluationPolicyV1 {
        policy_id: stable("named-host-benchmark-policy-v1")?,
        utility_rules: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Sum,
            })
            .collect(),
        risk_rules: risk_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Maximum,
            })
            .collect(),
        resource_rules: resource_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Sum,
            })
            .collect(),
        uncertainty_rules: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisAggregationRule {
                axis,
                operator: AggregationOperator::Maximum,
            })
            .collect(),
        pareto_absolute_tolerances: utility_ids
            .iter()
            .cloned()
            .map(|axis| AxisValue {
                axis,
                value: FixedQ32::ZERO,
            })
            .collect(),
    };
    Ok(EvaluationFixture {
        set: ContributionSet {
            objective_digest: objective,
            generation,
            contributions,
        },
        profile,
        policy,
    })
}

fn stable(value: &str) -> Result<StableId, Box<dyn Error>> {
    StableId::new(value).map_err(|error| format!("invalid id {value}: {error:?}").into())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
