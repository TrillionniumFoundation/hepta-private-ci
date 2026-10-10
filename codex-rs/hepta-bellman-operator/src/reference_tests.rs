use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn point(name: &str, raw: i64) -> SensorPointV1 {
    SensorPointV1 {
        point_id: id(name),
        coordinates: vec![FixedQ32::from_raw(raw)],
    }
}

#[test]
fn op_01_farthest_point_sensor_core_is_deterministic() {
    let design = SensorCoreDesignV1 {
        sensor_core_id: id("sensor-core-1"),
        state_axis_digest: digest("axis"),
        candidate_design_digest: digest("candidate-design"),
        seed_digest: digest("seed"),
        requested_count: 2,
        candidates: vec![
            point("point-2", FixedQ32::ONE.raw()),
            point("point-1", FixedQ32::ONE.raw() / 2),
            point("point-0", 0),
        ],
    };
    let manifest = match build_sensor_core(design) {
        Ok(manifest) => manifest,
        Err(error) => panic!("valid sensor design failed: {error}"),
    };
    assert_eq!(
        manifest
            .selected_points
            .iter()
            .map(|point| point.point_id.as_str())
            .collect::<Vec<_>>(),
        vec!["point-0", "point-2"]
    );
    assert_eq!(
        manifest.fill_distance_q32,
        FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)
    );
    assert_eq!(
        manifest.separation_radius_q32,
        FixedQ32::from_raw(FixedQ32::ONE.raw() / 2)
    );
    assert_eq!(manifest.mesh_ratio_q32, FixedQ32::ONE);
    assert!(!manifest.authority.grants_any());
}

fn cell(sensor: &str, action: &str, reward: i64, continuation: i64) -> BellmanReferenceCellV1 {
    BellmanReferenceCellV1 {
        sensor_id: id(sensor),
        action_id: id(action),
        reward: FixedQ32::from_raw(reward),
        continuation_value: FixedQ32::from_raw(continuation),
        terminal: false,
        evidence_digest: digest(&format!("evidence-{sensor}-{action}")),
    }
}

#[test]
fn op_01_tabular_reference_produces_exact_targets_and_gaps() {
    let plan = BellmanReferencePlanV1 {
        plan_id: id("reference-plan"),
        objective_digest: digest("objective"),
        sensor_core_digest: digest("sensor-core"),
        gamma: FixedQ32::ONE,
        sensor_ids: vec![id("sensor-1"), id("sensor-0")],
        action_ids: vec![id("action-1"), id("action-0")],
        cells: vec![
            cell("sensor-0", "action-0", 0, 10),
            cell("sensor-0", "action-1", 0, 20),
            cell("sensor-1", "action-0", 5, 5),
            cell("sensor-1", "action-1", 0, 8),
        ],
    };
    let receipt = match evaluate_bellman_reference(plan) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid reference grid failed: {error}"),
    };
    assert_eq!(receipt.targets[0].target, FixedQ32::from_raw(10));
    assert_eq!(receipt.targets[1].target, FixedQ32::from_raw(20));
    assert_eq!(receipt.greedy_actions[0].action_id, id("action-1"));
    assert_eq!(receipt.greedy_actions[0].action_gap, FixedQ32::from_raw(10));
    assert_eq!(receipt.greedy_actions[1].action_id, id("action-0"));
    assert_eq!(receipt.greedy_actions[1].action_gap, FixedQ32::from_raw(2));
    assert!(!receipt.evidence_digest.is_zero());
}

#[test]
fn op_02_applicability_rejects_degenerate_diffusion() {
    let certificate = OperatorApplicabilityCertificateV1 {
        certificate_id: id("certificate-1"),
        axis_partition_digest: digest("axis-partition"),
        domain_digest: digest("domain"),
        action_space_digest: digest("action-space"),
        holder_exponents_digest: digest("holder-exponents"),
        holder_constants_digest: digest("holder-constants"),
        state_lipschitz_digest: digest("state-lipschitz"),
        action_lipschitz_digest: digest("action-lipschitz"),
        ellipticity_nu_lcb: FixedQ32::ZERO,
        control_interval_millis: 100,
        evaluator_id: id("evaluator"),
        evaluator_credential_digest: digest("evaluator-credential"),
        fallback_digest: digest("fallback"),
        expires_at: 100,
        decision: ApplicabilityDecisionV1::Pass,
    };
    assert_eq!(
        validate_applicability_certificate(&certificate, 50),
        Err(OperatorClosureError::EllipticityUnsupported)
    );
}

#[test]
fn op_02_regularity_admission_enforces_gain_shape_ood_and_error_budget() {
    let assessment = OperatorRegularityAssessmentV1 {
        artifact_id: id("operator-artifact"),
        measured_rank: 8,
        reconstruction_gain_q32: FixedQ32::ONE,
        monotonicity_violations: 0,
        positivity_violations: 0,
        holder_residual_q32: FixedQ32::from_raw(10),
        action_lipschitz_residual_q32: FixedQ32::from_raw(10),
        ood_false_acceptance_q32: FixedQ32::from_raw(10),
        error_components: vec![
            OperatorErrorComponentV1 {
                component_id: id("model"),
                normalized_error: FixedQ32::from_raw(10),
                evidence_digest: digest("model-error"),
            },
            OperatorErrorComponentV1 {
                component_id: id("sensor"),
                normalized_error: FixedQ32::from_raw(10),
                evidence_digest: digest("sensor-error"),
            },
        ],
        dominant_component_approved: false,
        evaluator_id: id("evaluator"),
        evaluator_credential_digest: digest("evaluator-credential"),
    };
    let admission = match admit_operator_regularity(assessment.clone()) {
        Ok(admission) => admission,
        Err(error) => panic!("valid regularity assessment failed: {error}"),
    };
    assert_eq!(admission.total_normalized_error, FixedQ32::from_raw(20));
    assert!(!admission.assessment_digest.is_zero());

    let mut excessive_gain = assessment;
    excessive_gain.reconstruction_gain_q32 =
        FixedQ32::from_raw(FixedQ32::ONE.raw() + FixedQ32::ONE.raw() / 40);
    assert_eq!(
        admit_operator_regularity(excessive_gain),
        Err(OperatorClosureError::ReconstructionGain)
    );
}
