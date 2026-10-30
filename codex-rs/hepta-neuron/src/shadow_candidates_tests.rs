use super::*;

fn d(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn sample() -> PopulationSparseSignalReceiptV2 {
    PopulationSparseSignalReceiptV2 {
        config_digest: d(b"config"),
        input_digest: d(b"input"),
        checkpoint_before: d(b"before"),
        checkpoint_after: d(b"after"),
        activation_q24: vec![1, 2, 3],
        population_candidate_counts: vec![3],
        active_fraction_ppm: 25_000,
        prediction_error_q24: 1,
        projection_count: 3,
        requires_calibration: false,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn payloads() -> ShadowCellCandidatePayloadsV1 {
    ShadowCellCandidatePayloadsV1 {
        action: d(b"action"),
        routing: d(b"routing"),
        topology: d(b"topology"),
    }
}

#[test]
fn all_four_shadow_candidates_preserve_no_change_and_authority() {
    let build = || {
        propose_shadow_cell_candidates_v1(
            StableId::new("cell:1").unwrap(),
            d(b"objective"),
            d(b"frozen-topology"),
            &sample(),
            payloads(),
        )
        .unwrap()
    };
    let a = build();
    let b = build();
    assert_eq!(a, b);
    assert_eq!(a.no_change.kind, ShadowCellCandidateKindV1::NoChange);
    assert_eq!(a.no_change.payload_digest, d(b"frozen-topology"));
    let candidates = [&a.no_change, &a.action, &a.routing, &a.topology];
    for (index, candidate) in candidates.iter().enumerate() {
        assert!(!candidate.authority.grants_any());
        assert!(candidates[..index].iter().all(|prior| {
            prior.candidate_digest != candidate.candidate_digest
        }));
    }
}

#[test]
fn invalid_or_uncalibrated_signal_never_produces_shadow_candidates() {
    let mut s = sample();
    s.requires_calibration = true;
    assert_eq!(
        propose_shadow_cell_candidates_v1(
            StableId::new("cell:1").unwrap(),
            d(b"objective"),
            d(b"frozen"),
            &s,
            payloads(),
        ),
        Err(ShadowCellCandidateErrorV1::InvalidSignal)
    );
    s.requires_calibration = false;
    let mut p = payloads();
    p.routing = p.action;
    assert_eq!(
        propose_shadow_cell_candidates_v1(
            StableId::new("cell:1").unwrap(),
            d(b"objective"),
            d(b"frozen"),
            &s,
            p,
        ),
        Err(ShadowCellCandidateErrorV1::IdentityCollision)
    );
}
