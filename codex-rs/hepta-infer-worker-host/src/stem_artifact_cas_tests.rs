use super::*;

use std::fs;
use std::os::unix::fs::PermissionsExt;

// The production verifier deliberately refuses a group/world-accessible CAS root.
// tempfile defaults vary with the host umask; pin the test root's mode instead.
fn protected_root() -> tempfile::TempDir {
    let root = tempfile::tempdir().expect("create CAS fixture root");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700))
        .expect("protect CAS fixture root");
    root
}

use codex_hepta_infer_core::stem_feature_vector_digest_v1;

fn sample_source() -> StemFeatureRefV1 {
    let features = [1_i64 << 22, -(1_i64 << 21)];
    StemFeatureRefV1 {
        scope_id: StableId::new("scope.test").expect("valid CAS fixture operation"),
        principal_id: StableId::new("principal.test").expect("valid CAS fixture operation"),
        stem_model_id: StableId::new("jina-v5-text-nano").expect("valid CAS fixture operation"),
        stem_generation: Generation::new(7).expect("valid CAS fixture operation"),
        authority_epoch: 2,
        lease_expires_at_ms: 10_000,
        stem_weights_digest: Digest32::of_bytes(b"real-weight-blob"),
        tokenizer_digest: Digest32::of_bytes(b"real-tokenizer-blob"),
        preprocessor_digest: Digest32::of_bytes(b"real-preprocessor-blob"),
        projection_digest: Digest32::of_bytes(b"real-matryoshka-blob"),
        input_digest: Digest32::of_bytes(b"input"),
        feature_digest: stem_feature_vector_digest_v1(&features).expect("valid CAS fixture operation"),
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
        fs::write(root.join(digest.to_string()), bytes).expect("valid CAS fixture operation");
    }
}

#[test]
fn actually_reads_cas_bytes_and_issues_non_authoritative_proof() {
    let root = protected_root();
    let source = sample_source();
    store(root.path(), &source);
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).expect("valid CAS fixture operation");
    let proof = verifier.verify_selected(&source).expect("valid CAS fixture operation");
    assert_eq!(proof.observed_role_bytes(), &[16, 19, 22, 20]);
    assert!(proof.matches_source(&source));
    assert!(!proof.authority().grants_any());
    assert!(!proof.cas_directory_digest().is_zero());
    let mut other = source.clone();
    other.stem_generation = Generation::new(8).expect("valid CAS fixture operation");
    assert!(!proof.matches_source(&other));
    other = source.clone();
    other.authority_epoch += 1;
    assert!(!proof.matches_source(&other));
    other = source.clone();
    other.stem_model_id = StableId::new("different-stem").expect("valid CAS fixture operation");
    assert!(!proof.matches_source(&other));
    // A shareable frozen Stem CAS bundle is independent of request scope.
    other = source;
    other.scope_id = StableId::new("other-scope").expect("valid CAS fixture operation");
    assert!(proof.matches_source(&other));
}

#[test]
fn missing_and_mutated_content_never_become_digest_only_load_receipts() {
    let root = protected_root();
    let source = sample_source();
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).expect("valid CAS fixture operation");
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::MissingBlob)
    ));
    store(root.path(), &source);
    let target = root.path().join(source.stem_weights_digest.to_string());
    fs::write(&target, b"incorrect-weight-bytes").expect("valid CAS fixture operation");
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::DigestMismatch)
    ));
    fs::write(&target, b"real-weight-blob").expect("valid CAS fixture operation");
    fs::remove_file(root.path().join(source.tokenizer_digest.to_string())).expect("valid CAS fixture operation");
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::MissingBlob)
    ));
}

#[test]
fn too_large_empty_or_unsafe_storage_fails_closed() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let root = protected_root();
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
            .expect("valid CAS fixture operation")
            .verify_selected(&source),
        Err(StemCasError::ArtifactTooLarge)
    ));
    let link = root.path().with_extension("alias");
    symlink(root.path(), &link).expect("valid CAS fixture operation");
    assert!(matches!(
        StemArtifactCasVerifierV1::open(&link, 4096),
        Err(StemCasError::InvalidRoot)
    ));
    fs::remove_file(&link).expect("valid CAS fixture operation");
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o755)).expect("valid CAS fixture operation");
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096),
        Err(StemCasError::UnprotectedRoot)
    ));
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).expect("valid CAS fixture operation");

    let tokenizer_path = root.path().join(source.tokenizer_digest.to_string());
    fs::remove_file(&tokenizer_path).expect("valid CAS fixture operation");
    symlink(
        root.path().join(source.stem_weights_digest.to_string()),
        &tokenizer_path,
    )
    .expect("valid CAS fixture operation");
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .expect("valid CAS fixture operation")
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
}

#[test]
fn writable_or_hardlinked_blob_is_not_a_trusted_immutable_cas_source() {
    use std::os::unix::fs::PermissionsExt;

    let root = protected_root();
    let source = sample_source();
    store(root.path(), &source);
    let file = root.path().join(source.stem_weights_digest.to_string());
    fs::set_permissions(&file, fs::Permissions::from_mode(0o666)).expect("valid CAS fixture operation");
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .expect("valid CAS fixture operation")
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
    fs::set_permissions(&file, fs::Permissions::from_mode(0o600)).expect("valid CAS fixture operation");
    fs::hard_link(&file, root.path().join("extra-hardlink")).expect("valid CAS fixture operation");
    assert!(matches!(
        StemArtifactCasVerifierV1::open(root.path(), 4096)
            .expect("valid CAS fixture operation")
            .verify_selected(&source),
        Err(StemCasError::UnsafeBlob)
    ));
}

#[test]
fn zero_selected_digest_and_epoch_are_refused_before_read() {
    let root = protected_root();
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096).expect("valid CAS fixture operation");
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
