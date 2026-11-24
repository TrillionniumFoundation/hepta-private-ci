use super::compile;

#[test]
fn rounding_at_negative_weight_box_edge_moves_inward() {
    let (weights, bounds) = compile(&[-0.41], &[-0.1], 0.1).unwrap();
    assert!((weights[0] + 0.41).abs() < 0.1);
    assert!(bounds[0] <= 0.1);
    assert!(weights[0] > -0.51);
}

#[test]
fn zero_edits_preserve_exact_parameters() {
    let base = [0.32, 0.63, -0.41, -0.0];
    let (weights, bounds) = compile(&base, &[0.0; 4], 0.1).unwrap();
    assert_eq!(weights, base);
    assert_eq!(weights[3].to_bits(), base[3].to_bits());
    assert_eq!(bounds, vec![0.0; 4]);
}

#[test]
fn requests_outside_box_are_rejected() {
    assert!(compile(&[0.32], &[0.11], 0.1).is_err());
    assert!(compile(&[0.32], &[f64::NAN], 0.1).is_err());
}
