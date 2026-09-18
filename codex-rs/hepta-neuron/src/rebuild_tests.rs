use super::*;
use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: digest(b"model"),
        normalization_digest: digest(b"normalization"),
        generation: checked(Generation::new(2)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn event(sequence: u64, source: &'static [u8], drive: i64) -> RecomputedSparseEventV1 {
    let source_digest = digest(source);
    RecomputedSparseEventV1 {
        source_digest,
        recomputation_receipt_digest: digest(format!("recomputed:{sequence}").as_bytes()),
        tick: SparseTick {
            scope_digest: digest(b"scope"),
            objective_digest: digest(b"objective"),
            ndu_digest: digest(b"ndu"),
            body_digest: digest(b"body"),
            input_digest: source_digest,
            sequence,
            monotonic_micros: sequence * 1_000,
            drive_q24: vec![drive, 0, 0, 0, 0],
            prediction_q24: vec![0; 5],
        },
    }
}

#[test]
fn revoked_source_is_removed_before_state_mutation() {
    let events = vec![
        event(1, b"source-a", Q),
        event(2, b"source-b", -Q),
        event(3, b"source-c", Q / 2),
    ];
    let baseline = checked(rebuild_after_deletion(
        &config(),
        &DeletionRebuildRequestV1 {
            events: events.clone(),
            revoked_source_digests: BTreeSet::new(),
        },
    ));
    let revoked = events[1].source_digest;
    let rebuilt = checked(rebuild_after_deletion(
        &config(),
        &DeletionRebuildRequestV1 {
            events,
            revoked_source_digests: BTreeSet::from([revoked]),
        },
    ));
    assert_eq!(rebuilt.receipt.removed_count, 1);
    assert_eq!(rebuilt.receipt.survivor_count, 2);
    assert_ne!(
        baseline.receipt.final_checkpoint_digest,
        rebuilt.receipt.final_checkpoint_digest
    );
    assert_eq!(rebuilt.receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn all_revoked_sources_clear_state() {
    let first = event(1, b"source-a", Q);
    let source = first.source_digest;
    let rebuilt = checked(rebuild_after_deletion(
        &config(),
        &DeletionRebuildRequestV1 {
            events: vec![first],
            revoked_source_digests: BTreeSet::from([source]),
        },
    ));
    assert!(rebuilt.checkpoint.is_none());
    assert!(rebuilt.receipt.cleared);
    assert_eq!(rebuilt.receipt.final_checkpoint_digest, Digest32::ZERO);
}

#[test]
fn caller_supplied_old_output_without_recomputation_receipt_is_rejected() {
    let mut invalid = event(1, b"source-a", Q);
    invalid.recomputation_receipt_digest = Digest32::ZERO;
    assert_eq!(
        rebuild_after_deletion(
            &config(),
            &DeletionRebuildRequestV1 {
                events: vec![invalid],
                revoked_source_digests: BTreeSet::new(),
            },
        ),
        Err(RebuildError::InvalidRecomputationReceipt)
    );
}
