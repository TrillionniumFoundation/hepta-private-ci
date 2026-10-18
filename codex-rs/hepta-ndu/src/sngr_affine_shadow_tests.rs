use super::*;

fn request(
    initial_state: f64,
    durations: Vec<f64>,
    terminal: SngrAffineBoundaryShadowV1,
) -> SngrAffineShootingRequestShadowV1 {
    SngrAffineShootingRequestShadowV1 {
        initial_state,
        durations,
        terminal,
        tolerance: 1e-10,
    }
}

fn assert_close(actual: f64, expected: f64) {
    assert!(
        (actual - expected).abs() < 1e-9,
        "actual {actual}, expected {expected}"
    );
}

#[test]
fn correct_continuation_recovers_global_two_slice_solution() {
    let problem = request(
        /*initial_state*/ 1.0,
        vec![0.5, 0.5],
        SngrAffineBoundaryShadowV1 {
            slope: 0.5,
            intercept: 0.0,
        },
    );
    let receipt = solve_sngr_affine_shadow(&problem).expect("solvable affine fixture");
    assert!(receipt.accepted);
    assert_close(receipt.initial_utility, 1.0);
    assert_close(receipt.final_state, 2.0);
    assert_close(receipt.slices[0].state_out, 1.5);
    assert!(receipt.maximum_interface_residual < 1e-12);
    assert!(receipt.terminal_residual < 1e-12);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn local_terminal_reset_has_zero_terminal_error_but_fails_gluing() {
    let problem = request(
        /*initial_state*/ 1.0,
        vec![0.5, 0.5],
        SngrAffineBoundaryShadowV1 {
            slope: 0.5,
            intercept: 0.0,
        },
    );
    let wrong = naive_sngr_terminal_reset_shadow(&problem).expect("each short slice is solvable");
    assert!(!wrong.accepted);
    assert_close(wrong.initial_utility, 2.0 / 3.0);
    assert_close(wrong.maximum_interface_residual, 2.0 / 9.0);
    assert!(wrong.terminal_residual < 1e-12);
    assert_ne!(
        wrong.evidence_digest,
        solve_sngr_affine_shadow(&problem)
            .expect("global solution")
            .evidence_digest
    );
}

#[test]
fn one_shot_and_ten_short_slices_agree_with_nonzero_intercept() {
    let terminal = SngrAffineBoundaryShadowV1 {
        slope: 0.25,
        intercept: 0.75,
    };
    let full = solve_sngr_affine_shadow(&request(/*initial_state*/ 0.2, vec![1.0], terminal))
        .expect("one-shot solution");
    let split = solve_sngr_affine_shadow(&request(
        /*initial_state*/ 0.2,
        vec![0.1; 10],
        terminal,
    ))
    .expect("split solution");
    assert!(full.accepted && split.accepted);
    assert_close(full.initial_utility, split.initial_utility);
    assert_close(full.final_state, split.final_state);
}

#[test]
fn local_existence_does_not_certify_global_existence() {
    let terminal = SngrAffineBoundaryShadowV1 {
        slope: 1.0,
        intercept: 1.0,
    };
    let local = sngr_affine_continuation_shadow(terminal, /*duration*/ 0.25)
        .expect("short horizon supports local field");
    assert_close(local.intercept, 4.0 / 3.0);
    let invalid = solve_sngr_affine_shadow(&request(
        /*initial_state*/ 0.0,
        vec![0.25; 4],
        terminal,
    ));
    assert_eq!(invalid, Err(SngrAffineShadowError::IllPosed));
}

#[test]
fn rejects_zero_and_crossed_decoupling_denominators() {
    let terminal = SngrAffineBoundaryShadowV1 {
        slope: 2.0,
        intercept: 0.0,
    };
    for duration in [0.5, 1.0] {
        assert_eq!(
            sngr_affine_continuation_shadow(terminal, duration),
            Err(SngrAffineShadowError::IllPosed)
        );
    }
}

#[test]
fn negative_slope_and_intercept_keep_interface_continuity() {
    let result = solve_sngr_affine_shadow(&request(
        /*initial_state*/ 1.3,
        vec![0.1, 0.2, 0.3],
        SngrAffineBoundaryShadowV1 {
            slope: -0.7,
            intercept: 1.9,
        },
    ))
    .expect("negative slope supported");
    assert!(result.accepted);
    assert!(result.maximum_interface_residual < 1e-12);
}

#[test]
fn fail_closed_on_bad_inputs_instead_of_nan_receipts() {
    let valid_terminal = SngrAffineBoundaryShadowV1 {
        slope: 0.1,
        intercept: 0.2,
    };
    for duration in [0.0, -1.0, f64::NAN, f64::INFINITY, 4000.0] {
        assert!(
            solve_sngr_affine_shadow(&request(
                /*initial_state*/ 0.0,
                vec![duration],
                valid_terminal,
            ))
            .is_err()
        );
    }
    for count in [0_usize, 65] {
        assert_eq!(
            solve_sngr_affine_shadow(&request(
                /*initial_state*/ 0.0,
                vec![0.1; count],
                valid_terminal,
            )),
            Err(SngrAffineShadowError::InvalidHorizon)
        );
    }
    let mut nan_state = request(/*initial_state*/ f64::NAN, vec![0.1], valid_terminal);
    assert_eq!(
        solve_sngr_affine_shadow(&nan_state),
        Err(SngrAffineShadowError::NonFinite)
    );
    nan_state.initial_state = 0.0;
    nan_state.tolerance = 0.0;
    assert_eq!(
        solve_sngr_affine_shadow(&nan_state),
        Err(SngrAffineShadowError::InvalidTolerance)
    );
}

#[test]
fn synthetic_receipts_replay_without_runtime_authority() {
    let problem = request(
        /*initial_state*/ 0.5,
        vec![0.2, 0.3],
        SngrAffineBoundaryShadowV1 {
            slope: 0.25,
            intercept: 0.1,
        },
    );
    let a = solve_sngr_affine_shadow(&problem).expect("fixture");
    let b = solve_sngr_affine_shadow(&problem).expect("replay");
    assert_eq!(a, b);
    assert_ne!(a.evidence_digest, Digest32::ZERO);
    assert_eq!(a.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn native_conditional_z_regression_matches_affine_diffusion_sensitivity() {
    use crate::ConditionalMomentSampleV1;
    use crate::CovarianceConventionV1;
    use crate::NduCovarianceProfileV1;
    use crate::admit_covariance_profile;
    use crate::estimate_conditional_moments;
    use crate::solve_backward_regression;

    // At t=0, slope is 0.5 / (1 - 0.5*0.5) = 2/3.
    // With two correlated Wiener drivers and sigma=[0.3,-0.15],
    // the manufactured noise sensitivity is Z=[0.2,-0.1].
    let field = sngr_affine_continuation_shadow(
        SngrAffineBoundaryShadowV1 {
            slope: 0.5,
            intercept: 0.0,
        },
        /*duration*/ 0.5,
    )
    .expect("regular affine domain");
    let expected = [field.slope * 0.3, field.slope * -0.15];
    let profile = admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: Digest32::of_bytes(b"sngr-stochastic-driver-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        convention: CovarianceConventionV1::RatePerSecond,
        minimum_increment_eigenvalue: 1e-12,
        maximum_condition: 1e6,
        maximum_absolute_sample: 100.0,
        maximum_absolute_z: 100.0,
        maximum_relative_residual: 1e-10,
    })
    .expect("registered numeric fixture profile");
    let mut samples = Vec::new();
    for a in [-1.0, 1.0] {
        for b in [-1.0, 1.0] {
            for c in [-1.0, 1.0] {
                let m0 = (a + b) * 0.5;
                let m1 = (a + c) * 0.5;
                samples.push(ConditionalMomentSampleV1 {
                    conditioning_digest: Digest32::of_bytes(b"fixed-pre-boundary-stratum"),
                    duration_micros: 250_000,
                    increment: vec![m0, m1],
                    utility: vec![expected[0] * m0 + expected[1] * m1],
                });
            }
        }
    }
    let moments = estimate_conditional_moments(
        &samples,
        Digest32::of_bytes(b"external-synthetic-source"),
        &profile,
    )
    .expect("conditional moments");
    let recovered = solve_backward_regression(&moments, &profile).expect("native Z solve");
    assert_close(recovered.z[0][0], expected[0]);
    assert_close(recovered.z[0][1], expected[1]);
    assert_eq!(recovered.authority, AuthorityPosture::DENY_ALL);
}
