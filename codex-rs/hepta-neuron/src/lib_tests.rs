use super::*;

fn id(value: &str) -> StableId {
    let Ok(value) = StableId::new(value) else {
        panic!("test identifier must be valid");
    };
    value
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn request(generation: u64) -> StepRequest {
    let Ok(generation) = Generation::new(generation) else {
        panic!("test generation must be non-zero");
    };
    StepRequest {
        run_id: id("run:1"),
        model_digest: digest(b"model"),
        source_digest: digest(b"source"),
        generation,
        decay: FixedQ32::from_raw(FixedQ32::ONE.raw() / 2),
        features: vec![FixedQ32::ONE, FixedQ32::ZERO],
    }
}

#[test]
fn step_is_deterministic_and_authority_free() {
    let Ok((left_state, left_receipt)) = step(request(1), None) else {
        panic!("first deterministic step must succeed");
    };
    let Ok((right_state, right_receipt)) = step(request(1), None) else {
        panic!("second deterministic step must succeed");
    };
    assert_eq!(left_state, right_state);
    assert_eq!(left_receipt, right_receipt);
    assert!(!left_receipt.authority.grants_any());
}

#[test]
fn model_drift_is_rejected() {
    let Ok((state, _)) = step(request(1), None) else {
        panic!("initial step must succeed");
    };
    let mut next = request(2);
    next.model_digest = digest(b"other-model");
    assert_eq!(step(next, Some(&state)), Err(Error::ModelDrift));
}

#[test]
fn generation_must_advance() {
    let Ok((state, _)) = step(request(1), None) else {
        panic!("initial step must succeed");
    };
    assert_eq!(
        step(request(1), Some(&state)),
        Err(Error::GenerationNotAdvanced)
    );
}

#[test]
fn width_drift_is_rejected() {
    let Ok((state, _)) = step(request(1), None) else {
        panic!("initial step must succeed");
    };
    let mut next = request(2);
    next.features.push(FixedQ32::ZERO);
    assert_eq!(step(next, Some(&state)), Err(Error::WidthDrift));
}
