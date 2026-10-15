use super::*;

use std::fs;

use codex_hepta_infer_core::stem_feature_vector_digest_v1;

fn sample_source() -> StemFeatureRefV1 {
    let features = [1_i64 << 22, -(1_i64 << 21)];
    StemFeatureRefV1 {
        scope_id: StableId::new("scope.test").unwrap(),
        principal_id: StableId::new("principal.test").unwrap(),
        stem_model_id: StableId::new("jina-v5-text-nano").unwrap(),
        stem_generation: Generation::new(7).unwrap(),
        authority_epoch: 2,
        lease_expires_at_ms: 10_000,
        stem_weights_digest: Digest32::of_bytes(b"real-weight-blob"),
        tokenizer_digest: Digest32::of_bytes(b"real-tokenizer-blob"),
        preprocessor_digest: Digest32::of_bytes(b"real-preprocessor-blob"),
        projection_digest: Digest32::of_bytes(b"real-matryoshka-blob"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_digest: stem_feature_vector_digest_v1(&features).unwrap(),
        feature_width: features.len(),
    }
}

fn store(root: &Path, source: &StemFeatureRefV1) {
    let entries = [
        (source.stem_weights_digest, &b"real-weight-blob"[..]),
        (source.tokenizer_digest, &b"real-tokenizer-blob"[..]),
        (source.preprocessor_digest, &b"real-preprocessor-blob"[..]),
        (source.projection_digest, &b"real-matryoshka-blob"[..]),
    ];
    for (digest, bytes) in entries {
        fs::write(root.join(digest.to_string()), bytes).unwrap();
    }
}

#[test]
fn actually_reads_cas_bytes_and_issues_non_authoritative_proof() {
    let root = tempfile::tempdir().unwrap();
    let source = sample_source();
    store(root.path(), &source);
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).unwrap();
    let proof = verifier.verify_selected(&source).unwrap();
    assert_eq!(proof.observed_role_bytes(), &[16, 19, 22, 20]);
    assert!(proof.matches_source(&source));
    assert!(!proof.authority().grants_any());
    assert!(!proof.cas_directory_digest().is_zero());
    let mut other = source.clone();
    other.stem_generation = Generation::new(8).unwrap();
    assert!(!proof.matches_source(&other));
    other = source.clone();
    other.authority_epoch += 1;
    assert!(!proof.matches_source(&other));
    other = source.clone();
    other.stem_model_id = StableId::new("different-stem").unwrap();
    assert!(!proof.matches_source(&other));
    // A shareable frozen Stem CAS bundle is independent of request scope.
    other = source.clone();
    other.scope_id = StableId::new("other-scope").unwrap();
    assert!(proof.matches_source(&other));
}

#[test]
fn missing_and_mutated_content_never_become_digest_only_load_receipts() {
    let root = tempfile::tempdir().unwrap();
    let source = sample_source();
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).unwrap();
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::MissingBlob)
    ));
    store(root.path(), &source);
    let target = root.path().join(source.stem_weights_digest.to_string());
    fs::write(&target, b"incorrect-weight-bytes").unwrap();
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::DigestMismatch)
    ));
    fs::write(&target, b"real-weight-blob").unwrap();
    fs::remove_file(root.path().join(source.tokenizer_digest.to_string())).unwrap();
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::MissingBlob)
    ));
}

#[test]
fn too_large_empty_or_unsafe_storage_fails_closed() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let root = tempfile::tempdir().unwrap();
    let source = sample_source();
    store(root.path(), &source);
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 0),
        Err(StemCasError::InvalidBudget)
    ));
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), (1 << 40) + 1),
        Err(StemCasError::InvalidBudget)
    ));
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 2)
            .unwrap()
            .verify_selected(&source),
        Err(StemCasError::ArtifactTooLarge)
    ));
    let link = root.path().with_extension("alias");
    symlink(root.path(), &link).unwrap();
    assert!(matches!(
        StemArtifactCasVerifierV1::open(&link, 4096),
        Err(StemCasError::InvalidRoot)
    ));
    fs::remove_file(&link).unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o755)).unwrap();
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096),
        Err(StemCasError::UnprotectedRoot)
    ));
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();

    let tokenizer_path = root.path().join(source.tokenizer_digest.to_string());
    fs::remove_file(&tokenizer_path).unwrap();
    symlink(
        root.path().join(source.stem_weights_digest.to_string()),
        &tokenizer_path,
    )
    .unwrap();
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .unwrap()
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
}

#[test]
fn writable_or_hardlinked_blob_is_not_a_trusted_immutable_cas_source() {
    use std::os::unix::fs::PermissionsExt;

    let root = tempfile::tempdir().unwrap();
    let source = sample_source();
    store(root.path(), &source);
    let file = root.path().join(source.stem_weights_digest.to_string());
    fs::set_permissions(&file, fs::Permissions::from_mode(0o666)).unwrap();
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .unwrap()
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).unwrap();
    fs::hard_link(&file, root.path().join("extra-hardlink")).unwrap();
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .unwrap()
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
}

#[test]
fn zero_selected_digest_and_epoch_are_refused_before_read() {
    let root = tempfile::tempdir().unwrap();
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).unwrap();
    let mut source = sample_source();
    source.authority_epoch = 0;
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::InvalidSelection)
    ));
    source.authority_epoch = 2;
    source.stem_weights_digest = Digest32::ZERO;
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::InvalidSelection)
    ));
}
