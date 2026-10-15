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


#[test]
fn byte_verified_cas_and_shared_q24_views_preserve_legacy_v1_without_granting_execution() {
    use codex_hepta_infer_core::SharedStemQ24BufferV1;
    use codex_hepta_infer_core::StemAccessContextV1;
    use codex_hepta_infer_core::StemFeatureBindingError;
    use codex_hepta_infer_core::StemHeadBindingV1;
    use codex_hepta_infer_core::bind_stem_feature_request_v1;
    use codex_hepta_infer_core::stem_encoder_pipeline_digest_v1;

    let root = protected_root();
    let source = sample_source();
    store(root.path(), &source);
    // Byte-integrity is checked by the actual CAS owner, not by a digest claim.
    let verifier = StemArtifactCasVerifierV1::open(root.path(), 4096)
        .expect("protected CAS root");
    let proof = verifier.verify_selected(&source).expect("exact CAS bytes");
    assert!(proof.matches_source(&source));
    assert!(!proof.authority().grants_any());

    let values = vec![1_i64 << 22, -(1_i64 << 21)];
    let shared = SharedStemQ24BufferV1::from_unverified_source(source.clone(), values.clone())
        .expect("exact immutable Q24 buffer");
    let access = StemAccessContextV1 {
        scope_id: source.scope_id.clone(),
        principal_id: source.principal_id.clone(),
        stem_generation: source.stem_generation,
        authority_epoch: source.authority_epoch,
        now_ms: 900,
        revocation_observed: false,
    };
    let head = StemHeadBindingV1 {
        request_id: StableId::new("request.cell-a").expect("request identity"),
        head_model_id: StableId::new("head.cell-a").expect("head identity"),
        head_digest: Digest32::of_bytes(b"head-a"),
        head_weights_digest: Digest32::of_bytes(b"head-a-weights"),
        required_stem_model_id: source.stem_model_id.clone(),
        required_stem_generation: source.stem_generation,
        required_encoder_digest: stem_encoder_pipeline_digest_v1(&source),
        required_tokenizer_digest: source.tokenizer_digest,
        required_preprocessor_digest: source.preprocessor_digest,
        required_projection_digest: source.projection_digest,
        required_feature_width: source.feature_width,
        expected_output_width: 5,
    };
    let mut other_head = head.clone();
    other_head.request_id = StableId::new("request.cell-b").expect("second request");
    other_head.head_model_id = StableId::new("head.cell-b").expect("second head");

    let first = shared.borrow_for_head(&access, &head).expect("first allowed view");
    let second = shared.borrow_for_head(&access, &other_head).expect("second allowed view");
    assert!(std::ptr::eq(
        first.feature_vector_q24().as_ptr(),
        second.feature_vector_q24().as_ptr()
    ));
    assert_eq!(first.feature_vector_q24(), values.as_slice());
    assert!(!first.authority().grants_any());
    assert!(!second.authority().grants_any());

    let owned = shared
        .materialize_owned_for_head(&access, &head)
        .expect("freshly checked owned V1 request");
    let baseline = bind_stem_feature_request_v1(&source, &access, head.clone(), &values)
        .expect("legacy exact owned V1 request");
    assert_eq!(owned, baseline);

    // Cached bytes and a historical CAS proof never override a current denial.
    let mut stale = access;
    stale.authority_epoch += 1;
    assert_eq!(
        shared.borrow_for_head(&stale, &head),
        Err(StemFeatureBindingError::AuthorityEpochMismatch)
    );
    stale.authority_epoch = source.authority_epoch;
    stale.revocation_observed = true;
    assert_eq!(
        shared.materialize_owned_for_head(&stale, &head),
        Err(StemFeatureBindingError::Revoked)
    );

    // The CAS proof binds read bytes; a later file change must not be treated
    // as a valid fresh load merely because an old digest was retained.
    fs::write(root.path().join(source.stem_weights_digest.to_string()), b"mutated-weight")
        .expect("mutate fixture blob");
    assert!(matches!(
        verifier.verify_selected(&source),
        Err(StemCasError::DigestMismatch)
    ));
}
