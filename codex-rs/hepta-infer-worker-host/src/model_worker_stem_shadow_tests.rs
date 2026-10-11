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
