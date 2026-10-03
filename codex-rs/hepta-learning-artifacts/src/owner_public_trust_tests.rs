use super::super::tests::*;
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn complete_public_trust_retains_both_signer_sets_and_rejects_partial_or_noncanonical_bytes() {
    let key = signer();
    let mut original = trust(&key, withdrawal_scope().digest());
    original.minimum_authority_epoch = 1;
    original.genesis_predecessor_head_digest = Digest32::of_bytes(b"actual genesis predecessor");
    original.head_signers[0].revoked_at = Some(91);
    let bytes = encode_artifact_public_trust_v1(&original).expect("whole original trust");
    assert_eq!(
        decode_artifact_public_trust_v1(&bytes).expect("original fields"),
        original
    );
    for end in 0..bytes.len() {
        assert!(decode_artifact_public_trust_v1(&bytes[..end]).is_err());
    }
    let mut extra = bytes.clone();
    extra.extend_from_slice(b"execution_authority=true\n");
    assert!(decode_artifact_public_trust_v1(&extra).is_err());
    let text = std::str::from_utf8(&bytes).expect("codec text");
    let padded = text.replacen("\n1\n", "\n01\n", 1);
    assert!(decode_artifact_public_trust_v1(padded.as_bytes()).is_err());
}

#[test]
fn public_material_in_an_unprotected_path_cannot_construct_the_current_owner() {
    let directory = TestDir::new();
    let path = directory.0.join("public-trust.bin");
    let original = encode_artifact_public_trust_v1(&trust(&signer(), withdrawal_scope().digest()))
        .expect("public bytes");
    fs::write(&path, &original).expect("unprotected fixture");
    let sources = ArtifactReadOnlyOwnerSourcesV1 {
        root: directory.0.clone(),
        trust_path: path.clone(),
        trust_digest: Digest32::of_bytes(&original),
        withdrawal_path: directory.0.join("absent-withdrawal"),
        withdrawal_receipt: crate::DatasetWithdrawalSnapshotReceiptV1 {
            binding: Digest32::ZERO,
            scope_digest: Digest32::ZERO,
            head_digest: Digest32::ZERO,
            file_digest: Digest32::ZERO,
            records: 0,
            encoded_bytes: 0,
        },
    };
    assert!(matches!(
        ReadOnlyArtifactCurrentOwnerV1::from_protected_sources(&sources, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));
    assert_eq!(fs::read(path).expect("unchanged public source"), original);
    assert!(!sources.withdrawal_path.exists());
    assert!(!directory.0.join("READ-CURRENT").exists());
}
