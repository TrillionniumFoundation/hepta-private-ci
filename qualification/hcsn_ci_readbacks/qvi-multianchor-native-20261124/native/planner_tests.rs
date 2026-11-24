use super::{Problem, cost_edit, solve};

#[test]
fn underdetermined_reachable_target_is_preserved() {
    let plan = solve(&Problem {
        matrix: vec![vec![1.0, 1.0, 0.0], vec![1.0, 0.0, 1.0]],
        target: vec![0.02, -0.01],
        budget: 0.1,
        tolerance: 1e-10,
    })
    .unwrap();
    assert_eq!(plan.status, "FitFeasibleNeedsFullValidation");
    assert!(plan.residual_upper < 1e-14);
    assert_eq!(plan.rank, 2);
}

#[test]
fn contradictory_anchors_return_infeasible_not_an_edit() {
    let plan = solve(&Problem {
        matrix: vec![vec![1.0], vec![1.0]],
        target: vec![0.0, 0.1],
        budget: 0.1,
        tolerance: 1e-10,
    })
    .unwrap();
    assert_eq!(plan.status, "NoEditInfeasible");
    assert!(plan.infeasible_lower > 0.049999999999);
    assert!(plan.infeasible_lower <= 0.05);
}

#[test]
fn box_restriction_is_part_of_infeasibility() {
    let plan = solve(&Problem {
        matrix: vec![vec![1.0]],
        target: vec![0.2],
        budget: 0.1,
        tolerance: 1e-10,
    })
    .unwrap();
    assert_eq!(plan.status, "NoEditInfeasible");
    assert_eq!(plan.delta, vec![0.1]);
    assert!(plan.infeasible_lower > 0.099999999999);
    assert!(plan.infeasible_lower <= 0.1);
}

#[test]
fn analytic_cost_reopens_at_prescribed_original_fixture_root() {
    let theta = [-0.15, 0.35, 0.2, 1.0, 0.25, 1.0, 0.4, 0.3];
    let (cost, error) = cost_edit(&theta, 0.536649206678534, 0.1).unwrap();
    assert!((cost - 0.31934555401888893).abs() < 2e-15);
    assert!(error < 2e-15);
    assert!(cost_edit(&theta, 0.536649206678534, 0.001).is_err());
}

#[test]
fn nonfinite_input_cannot_generate_candidate() {
    assert!(
        solve(&Problem {
            matrix: vec![vec![f64::NAN]],
            target: vec![0.0],
            budget: 0.1,
            tolerance: 1e-10
        })
        .is_err()
    );
}
