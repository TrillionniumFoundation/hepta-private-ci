use crate::kernels::Kernel;
use crate::kernels::cdf;

#[test]
fn normal_tail_does_not_cancel() {
    let expected = 7.619_853_024_160_47e-24;
    assert!((cdf(-10.0) / expected - 1.0).abs() < 2e-14);
    assert!(cdf(-12.0) > 0.0);
}

#[test]
fn absorbing_transition_preserves_mass_and_horizon_order() {
    let kernel = Kernel::new(15, "first_passage", [0.0; 6]).expect("kernel");
    let short = kernel.transition(/*drive*/ 0.7, /*dt*/ 0.1).expect("short");
    let long = kernel.transition(/*drive*/ 0.7, /*dt*/ 1.0).expect("long");
    for i in 0..15 {
        assert!((long[i].iter().sum::<f64>() - 1.0).abs() < 1e-13);
        assert!(long[i][15] + long[i][16] >= short[i][15] + short[i][16]);
    }
}

#[test]
fn refractory_release_retains_tick_contract() {
    let kernel = Kernel::new(15, "clocked", [0.0; 6]).expect("kernel");
    let a = kernel.transition(/*drive*/ -1.0, /*dt*/ 0.01).expect("short");
    let b = kernel.transition(/*drive*/ 1.0, /*dt*/ 8.0).expect("long");
    assert_eq!(&a[15..], &b[15..]);
    assert_eq!(a[15][16], 0.0);
    assert!((a[15][..15].iter().sum::<f64>() - kernel.recovery).abs() < 1e-14);
}

#[test]
fn continuous_and_clocked_share_endpoint_probabilities() {
    let a = Kernel::new(15, "clocked", [0.0; 6])
        .expect("clocked")
        .transition(/*drive*/ 0.2, /*dt*/ 0.6)
        .expect("transition");
    let b = Kernel::new(15, "continuous", [0.0; 6])
        .expect("continuous")
        .transition(/*drive*/ 0.2, /*dt*/ 0.6)
        .expect("transition");
    for i in 0..15 {
        assert!((b[i][0] - a[i][0] - a[i][16]).abs() < 2e-15);
        assert!((b[i][14] - a[i][14] - a[i][15]).abs() < 2e-15);
        assert_eq!(&a[i][1..14], &b[i][1..14]);
    }
}
