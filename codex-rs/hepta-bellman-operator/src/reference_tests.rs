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

#[test]
fn sensor_geometry_rounds_coverage_and_mesh_ratio_conservatively() {
    let mut design = SensorCoreDesignV1 {
        sensor_core_id: id("sensor-core"),
        state_axis_digest: digest("axis"),
        candidate_design_digest: digest("design"),
        seed_digest: digest("seed"),
        requested_count: 2,
        candidates: vec![point("a", /*raw*/ 0), point("b", /*raw*/ 4), point("c", /*raw*/ 8)],
    };
    for candidate in &mut design.candidates {
        candidate.coordinates.push(candidate.coordinates[0]);
    }
    let manifest = build_sensor_core(design.clone()).expect("valid finite design");
    assert_eq!(
        (
            manifest.fill_distance_q32,
            manifest.separation_radius_q32,
            manifest.mesh_ratio_q32,
        ),
        (
            FixedQ32::from_raw(6),
            FixedQ32::from_raw(5),
            FixedQ32::from_raw(5_153_960_756),
        )
    );
    design.candidates.reverse();
    assert_eq!(build_sensor_core(design), Ok(manifest));
}

#[test]
fn sensor_manifest_binds_unselected_candidate_coordinates() {
    let design = SensorCoreDesignV1 {
        sensor_core_id: id("sensor-core"),
        state_axis_digest: digest("axis"),
        candidate_design_digest: digest("claimed-design"),
        seed_digest: digest("seed"),
        requested_count: 2,
        candidates: vec![
            point("a", /*raw*/ 0),
            point("b", FixedQ32::ONE.raw() / 4),
            point("c", FixedQ32::ONE.raw()),
        ],
    };
    let original = build_sensor_core(design.clone()).expect("valid design");
    let mut changed = design.clone();
    changed.candidates[1].coordinates[0] = FixedQ32::from_raw(3 * FixedQ32::ONE.raw() / 4);
    let altered = build_sensor_core(changed).expect("valid changed design");
    assert_eq!(original.selected_points, altered.selected_points);
    assert_eq!(original.fill_distance_q32, altered.fill_distance_q32);
    assert_ne!(original.manifest_digest, altered.manifest_digest);

    let mut duplicate = design;
    duplicate.candidates[1].coordinates = duplicate.candidates[0].coordinates.clone();
    assert_eq!(
        build_sensor_core(duplicate),
        Err(OperatorClosureError::DuplicateSensorCoordinates)
    );
}

#[test]
fn sensor_separation_tracks_all_prior_selected_points() {
    let design = SensorCoreDesignV1 {
        sensor_core_id: id("sensor-core"),
        state_axis_digest: digest("axis"),
        candidate_design_digest: digest("design"),
        seed_digest: digest("seed"),
        requested_count: 3,
        candidates: vec![
            point("a", /*raw*/ 0),
            point("b", /*raw*/ 4),
            point("c", /*raw*/ 6),
            point("d", /*raw*/ 12),
        ],
    };
    let manifest = build_sensor_core(design).expect("valid design");
    assert_eq!(
        (
            manifest.selected_points,
            manifest.fill_distance_q32,
            manifest.separation_radius_q32,
            manifest.mesh_ratio_q32,
        ),
        (
            vec![point("a", /*raw*/ 0), point("d", /*raw*/ 12), point("c", /*raw*/ 6)],
            FixedQ32::from_raw(2),
            FixedQ32::from_raw(3),
            FixedQ32::from_raw(2_863_311_531),
        )
    );
}

#[test]
fn reference_receipt_binds_source_evidence_and_equal_output_inputs() {
    let plan = BellmanReferencePlanV1 {
        plan_id: id("reference-plan"),
        objective_digest: digest("objective"),
        sensor_core_digest: digest("sensor-core"),
        gamma: FixedQ32::ONE,
        sensor_ids: vec![id("sensor")],
        action_ids: vec![id("a"), id("b")],
        cells: vec![
            cell("sensor", "a", /*reward*/ 10, /*continuation*/ 0),
            cell("sensor", "b", /*reward*/ 20, /*continuation*/ 0),
        ],
    };
    let original = evaluate_bellman_reference(plan.clone()).expect("valid reference");
    let mut reordered = plan.clone();
    reordered.action_ids.reverse();
    reordered.cells.reverse();
    assert_eq!(evaluate_bellman_reference(reordered), Ok(original.clone()));

    let mut altered_evidence = plan.clone();
    altered_evidence.cells[0].evidence_digest = digest("replacement-evidence");
    let mut altered_decomposition = plan.clone();
    altered_decomposition.cells[0].reward = FixedQ32::from_raw(1);
    altered_decomposition.cells[0].continuation_value = FixedQ32::from_raw(9);
    let mut altered_terminal = plan;
    altered_terminal.cells[0].terminal = true;
    for altered_plan in [altered_evidence, altered_decomposition, altered_terminal] {
        let altered = evaluate_bellman_reference(altered_plan).expect("same valid targets");
        assert_eq!(original.targets, altered.targets);
        assert_eq!(original.greedy_actions, altered.greedy_actions);
        assert_ne!(original.evidence_digest, altered.evidence_digest);
    }
}
