use super::*;
fn fixture() -> (SparseConfig, SparseTick, SparseCheckpoint) {
    let cfg = SparseConfig {
        model_digest: Digest32::of_bytes(b"head"),
        normalization_digest: Digest32::of_bytes(b"norm"),
        generation: Generation::new(1).expect("generation"),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    let tick = SparseTick {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(b"input"),
        sequence: 1,
        monotonic_micros: 1000,
        drive_q24: vec![Q, 0, 0, 0, 0],
        prediction_q24: vec![0; 5],
    };
    let (first, _) = sparse_tick(&cfg, &tick, None).expect("first actual tick");
    (cfg, tick, first)
}
fn decode(
    cfg: &SparseConfig,
    tick: &SparseTick,
    checkpoint: &SparseCheckpoint,
    bytes: &[u8],
) -> Result<SparseCheckpoint, SparseError> {
    SparseCheckpoint::decode_observation_v1(
        bytes,
        Digest32::of_bytes(bytes),
        cfg,
        JournalScope {
            scope_digest: tick.scope_digest,
            objective_digest: tick.objective_digest,
        },
        tick.body_digest,
        JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        },
    )
}
#[test]
fn whole_sparse_state_round_trips_and_preserves_next_tick_exactly() {
    let (cfg, mut tick, first) = fixture();
    let bytes = first.encode_observation_v1().expect("whole observation");
    let reopened = decode(&cfg, &tick, &first, &bytes).expect("read whole checkpoint");
    assert_eq!(reopened, first);
    tick.sequence = 2;
    tick.monotonic_micros = 2000;
    assert_eq!(
        sparse_tick(&cfg, &tick, Some(&reopened)),
        sparse_tick(&cfg, &tick, Some(&first))
    );
    assert!(bytes.len() <= MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1);
}
#[test]
fn whole_checkpoint_rejects_repin_tamper_truncation_foreign_body_scope_anchor_and_width() {
    let (cfg, tick, first) = fixture();
    let bytes = first.encode_observation_v1().expect("whole");
    for index in [8, 40, 100, bytes.len() - 1] {
        let mut changed = bytes.clone();
        changed[index] ^= 1;
        assert!(decode(&cfg, &tick, &first, &changed).is_err());
    }
    for length in [0, 7, 31, bytes.len() - 1] {
        assert!(decode(&cfg, &tick, &first, &bytes[..length]).is_err());
    }
    let oversized = vec![0; MAX_SPARSE_CHECKPOINT_OBSERVATION_BYTES_V1 + 1];
    assert!(decode(&cfg, &tick, &first, &oversized).is_err());
    for field in 0..4 {
        let mut changed = tick.clone();
        let mut changed_cfg = cfg.clone();
        let mut changed_anchor = first.clone();
        match field {
            0 => changed.body_digest = Digest32::of_bytes(b"foreign"),
            1 => changed.scope_digest = Digest32::of_bytes(b"foreign"),
            2 => changed_anchor.sequence += 1,
            _ => changed_cfg.width = 10,
        }
        assert!(decode(&changed_cfg, &changed, &changed_anchor, &bytes).is_err());
    }
    // Even a new transport checksum cannot substitute malformed state. A
    // whole digest alone does not verify the independently chosen body/scope.
    let mut changed = bytes;
    changed[8] ^= 1;
    let end = changed.len() - 32;
    let checksum = Digest32::of_parts(&[DOMAIN, &changed[..end]]);
    changed[end..].copy_from_slice(checksum.as_array());
    assert!(decode(&cfg, &tick, &first, &changed).is_err());
}
