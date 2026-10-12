use super::*;

fn test_request() -> ShadowStemCellRequest {
    ShadowStemCellRequest {
        scope_id: "scope.a".into(),
        principal_id: "principal.a".into(),
        purpose_id: "purpose.decision".into(),
        cell_id: "cell.a".into(),
        generation: 3,
        authority_epoch: 2,
        input: ShadowStemInput {
            question: "选择什么？".into(),
            options: vec!["A".into(), "B".into()],
            state: "情境".into(),
        },
    }
}

#[test]
fn rust_joint_question_options_state_digest_matches_python_golden() {
    assert_eq!(
        input_hash(&test_request().input).expect("canonical JSON"),
        "4ef9abd544c12919d1eb3a2e85cee9b90ae5a99f712c633deb755c541b3a2f62"
    );
    let mut different = test_request();
    different.input.options.swap(0, 1);
    assert_ne!(
        input_hash(&different.input).expect("swapped"),
        input_hash(&test_request().input).expect("original"),
    );
}

#[test]
fn shadow_worker_refuses_unpinned_sidecar_before_any_execution() {
    let config = PinnedShadowStemConfig {
        python_executable: PathBuf::from("/usr/bin/python3"),
        reviewed_script: PathBuf::from("/not/a/real/reviewed/script.py"),
        reviewed_script_sha256: "a".repeat(64),
        manifest: PathBuf::from("/not/a/real/model.json"),
        manifest_sha256: "b".repeat(64),
        expected_pipeline_digest: "c".repeat(64),
    };
    assert!(matches!(
        run_pinned_shadow_stem_batch(&config, &[test_request()]),
        Err(Error::FeatureContract)
    ));
    assert!(matches!(
        run_pinned_shadow_stem_batch(&config, &[]),
        Err(Error::RequestCapacity)
    ));
}

fn shadow_pipeline() -> ShadowSnapshotPipeline {
    ShadowSnapshotPipeline {
        encoder_digest: Digest32::of_bytes(b"exact-pinned-encoder-pipeline"),
        tokenizer_digest: Digest32::of_bytes(b"exact-tokenizer"),
        normalizer_digest: Digest32::of_bytes(b"exact-preprocessor"),
        quantization_digest: Digest32::of_bytes(b"exact-q24-quantization"),
    }
}

fn shadow_row(cell: &str, scope: &str) -> CheckedShadowStemRow {
    let values = vec![1_i64 << 23, -(1_i64 << 22)];
    CheckedShadowStemRow {
        scope_id: scope.to_string(),
        principal_id: "principal.a".to_string(),
        purpose_id: "purpose.decision".to_string(),
        cell_id: cell.to_string(),
        generation: 3,
        authority_epoch: 2,
        input_digest: Digest32::of_bytes(b"complete-joint-input").to_string(),
        feature_digest: feature_content_digest_v2(&values).to_string(),
        features_q24: values,
    }
}

fn shadow_batch(rows: Vec<CheckedShadowStemRow>) -> CheckedShadowStemBatch {
    CheckedShadowStemBatch {
        pipeline_digest: shadow_pipeline().encoder_digest,
        unique_inputs: 1,
        actual_forward_calls_reported: 1,
        backend_latency_micros_reported: 10,
        rows,
        authority: NonAuthorizingPosture::DENY_ALL,
    }
}

#[test]
fn accepted_shadow_rows_share_one_immutable_arc_across_cells() {
    let mut cache = SharedFeatureCacheV2::new(8, 4096).expect("cache");
    let snapshots = stage_shadow_feature_snapshots(
        &mut cache,
        &shadow_batch(vec![
            shadow_row("cell.a", "scope.a"),
            shadow_row("cell.b", "scope.a"),
        ]),
        shadow_pipeline(),
        10,
        1000,
    )
    .expect("typed shadow stage");
    assert_eq!(cache.len(), 1);
    assert_eq!(snapshots.len(), 2);
    assert!(Arc::ptr_eq(&snapshots[0], &snapshots[1]));
    assert_eq!(snapshots[0].identity.scope_id.as_str(), "scope.a");
    assert_eq!(
        snapshots[0].features_q24.as_ref(),
        &[1_i64 << 23, -(1_i64 << 22)]
    );
}

#[test]
fn shadow_snapshot_batch_failure_is_atomic_and_scope_is_part_of_key() {
    let mut cache = SharedFeatureCacheV2::new(4, 4096).expect("cache");
    let base = shadow_batch(vec![shadow_row("cell.a", "scope.a")]);
    stage_shadow_feature_snapshots(&mut cache, &base, shadow_pipeline(), 10, 1000)
        .expect("initial stage");
    let initial_len = cache.len();
    let mut poisoned = shadow_row("cell.b", "scope.a");
    poisoned.feature_digest = Digest32::of_bytes(b"forged-content").to_string();
    let rows = shadow_batch(vec![shadow_row("cell.new", "scope.b"), poisoned]);
    assert!(matches!(
        stage_shadow_feature_snapshots(&mut cache, &rows, shadow_pipeline(), 10, 1000),
        Err(Error::FeatureContract)
    ));
    assert_eq!(cache.len(), initial_len);

    let separate = stage_shadow_feature_snapshots(
        &mut cache,
        &shadow_batch(vec![shadow_row("cell.c", "scope.b")]),
        shadow_pipeline(),
        10,
        1000,
    )
    .expect("different scope gets separate key");
    assert_eq!(cache.len(), 2);
    assert_eq!(separate[0].identity.scope_id.as_str(), "scope.b");
    let mut wrong_model = base.clone();
    wrong_model.pipeline_digest = Digest32::of_bytes(b"other-encoder");
    assert!(matches!(
        stage_shadow_feature_snapshots(&mut cache, &wrong_model, shadow_pipeline(), 10, 1000),
        Err(Error::FeatureContract)
    ));
    assert_eq!(cache.len(), 2);
    let bad_ttl = stage_shadow_feature_snapshots(&mut cache, &base, shadow_pipeline(), 10, 600_000);
    assert!(matches!(bad_ttl, Err(Error::FeatureContract)));
}
