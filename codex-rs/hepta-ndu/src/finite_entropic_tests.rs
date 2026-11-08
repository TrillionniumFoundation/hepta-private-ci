use super::FiniteEntropicError;
use super::FiniteEntropicProfileV1;

#[test]
fn duration_discount_and_cost_compose_without_duplicate_terminal_payoff() {
    let profile = FiniteEntropicProfileV1 {
        risk: 0.0,
        discount_per_second: 0.9,
        latency_weight: 0.1,
    };
    let inner = profile.edge(2.0, 0.8).unwrap();
    let outer = profile.edge(1.0, inner).unwrap();
    assert!((inner - 0.448).abs() < 1e-12);
    assert!((outer - 0.3032).abs() < 1e-12);
}

#[test]
fn risk_neutral_and_single_particle_degenerate_to_expected_recursion() {
    let profile = FiniteEntropicProfileV1::default();
    for risk in [0.0, 0.25, 8.0] {
        let profile = FiniteEntropicProfileV1 { risk, ..profile };
        let edge = profile.edge(0.5, 0.6).unwrap();
        assert!((profile.certainty_equivalent(&[edge], &[1.0]).unwrap() - 0.595).abs() < 1e-12);
    }
    let profile = FiniteEntropicProfileV1 {
        risk: 0.0,
        ..profile
    };
    assert!(
        (profile
            .certainty_equivalent(&[0.2, 0.8], &[0.25, 0.75])
            .unwrap()
            - 0.65)
            .abs()
            < 1e-12
    );
}

#[test]
fn positive_risk_penalizes_spread_and_ignores_zero_probability_extrema() {
    let profile = FiniteEntropicProfileV1 {
        risk: 2.0,
        ..Default::default()
    };
    let risky = profile
        .certainty_equivalent(&[0.0, 1.0], &[0.5, 0.5])
        .unwrap();
    assert!(risky > 0.0 && risky < 0.5);
    let shifted = profile
        .certainty_equivalent(&[10.0, 11.0], &[0.5, 0.5])
        .unwrap();
    assert!((shifted - risky - 10.0).abs() < 1e-12);
    let without_zero = profile
        .certainty_equivalent(&[-1e100, 0.8], &[0.0, 1.0])
        .unwrap();
    assert!((without_zero - 0.8).abs() < 1e-12);
}

#[test]
fn invalid_lottery_and_duration_fail_before_planning() {
    let profile = FiniteEntropicProfileV1::default();
    assert_eq!(profile.edge(-1.0, 0.5), Err(FiniteEntropicError::Duration));
    assert_eq!(
        profile.certainty_equivalent(&[0.2], &[0.0]),
        Err(FiniteEntropicError::Lottery)
    );
    assert_eq!(
        profile.certainty_equivalent(&[f64::NAN], &[1.0]),
        Err(FiniteEntropicError::Lottery)
    );
    let invalid = FiniteEntropicProfileV1 {
        risk: f64::NAN,
        ..profile
    };
    assert_eq!(invalid.edge(1.0, 0.5), Err(FiniteEntropicError::Profile));
}

#[test]
fn python_golden_vectors_match_the_native_operator() {
    // Source: scripts/ndu_real_runtime/finite_entropic_golden.json. These
    // independently exercised values keep the public numerical contract small.
    let profile = FiniteEntropicProfileV1::default();
    assert!(
        (profile
            .certainty_equivalent(&[0.2, 0.8], &[0.25, 0.75])
            .unwrap()
            - 0.641_353_841_169_051_4)
            .abs()
            < 1e-12
    );
    let profile = FiniteEntropicProfileV1 {
        discount_per_second: 0.97,
        ..profile
    };
    let edges = [
        profile.edge(2.0, 0.7).unwrap(),
        profile.edge(5.0, 0.9).unwrap(),
    ];
    assert!(
        (profile.certainty_equivalent(&edges, &[0.4, 0.6]).unwrap() - 0.688_955_234_615_172_6)
            .abs()
            < 1e-12
    );
}

#[test]
fn arbitrarily_small_positive_risk_is_continuous_at_the_mean() {
    for risk in [1e-300, 1e-20, 1e-12, 1e-6] {
        let profile = FiniteEntropicProfileV1 {
            risk,
            ..Default::default()
        };
        let value = profile
            .certainty_equivalent(&[0.2, 0.8], &[0.25, 0.75])
            .unwrap();
        assert!((value - 0.65).abs() <= risk * 0.04 + 1e-14);
    }
}
