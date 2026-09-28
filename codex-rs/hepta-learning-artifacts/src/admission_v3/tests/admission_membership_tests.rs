//! Adversarial public-DTO tests for live publication membership.
use super::*;

fn withdrawn_registry(dataset: Digest32) -> DatasetWithdrawalRegistry {
    let mut registry = DatasetWithdrawalRegistry::new_scoped(scope("membership"));
    registry
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawn-notice"),
            dataset_digest: dataset,
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .fixture("withdrawal appends");
    registry
}

#[test]
fn art_05_resealed_current_head_cannot_hide_withdrawn_dataset() {
    let dataset = digest("withdrawn-dataset");
    let registry = withdrawn_registry(dataset);
    // A caller can reconstruct every public field and its digest. Integrity
    // alone must not turn this DTO into proof of authoritative admission.
    let validated_manifest = validate_artifact_manifest_v2(manifest(dataset), 22)
        .fixture("manifest syntax is valid");
    let withdrawal_scope_digest = registry.scope_digest().fixture("scoped registry");
    let withdrawal_head_digest = registry.head_digest();
    let admission_digest = digest_admission(
        validated_manifest.manifest_digest,
        withdrawal_scope_digest,
        withdrawal_head_digest,
        22,
    );
    let forged = WithdrawalBoundArtifactAdmissionV3 {
        validated_manifest,
        withdrawal_scope_digest,
        withdrawal_head_digest,
        admitted_at: 22,
        admission_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        verify_artifact_admission_v3(&forged, registry.head_digest(), 22),
        Ok(())
    );
    assert_eq!(
        validate_artifact_publication_v3(&forged, &registry, 22),
        Err(ArtifactAdmissionError::Manifest(
            ArtifactClosureError::WithdrawnDataset
        ))
    );
    let artifacts = crate::ArtifactRegistry::default();
    assert!(
        crate::ArtifactPublicationTransactionV1::begin(
            id("forged-publication"),
            forged,
            &registry,
            &artifacts,
            artifacts.snapshot().head_digest,
            22,
        )
        .is_err()
    );
}

#[test]
fn art_05_unrelated_withdrawal_allows_new_admission() {
    let registry = withdrawn_registry(digest("other-dataset"));
    let admission = admit_manifest_at_withdrawal_head_v3(
        &registry,
        registry.head_digest(),
        manifest(digest("eligible-dataset")),
        22,
    )
    .fixture("unrelated withdrawal does not exclude this dataset");
    assert_eq!(validate_artifact_publication_v3(&admission, &registry, 22), Ok(()));
}

#[test]
fn art_05_historical_integrity_does_not_renew_publication() {
    let dataset = digest("historical-dataset");
    let original = DatasetWithdrawalRegistry::new_scoped(scope("membership"));
    let admission = admit_manifest_at_withdrawal_head_v3(
        &original,
        original.head_digest(),
        manifest(dataset),
        20,
    )
    .fixture("original admission");
    let current = withdrawn_registry(dataset);
    assert_eq!(
        verify_artifact_admission_v3(&admission, original.head_digest(), admission.admitted_at),
        Ok(())
    );
    assert_eq!(
        validate_artifact_publication_v3(&admission, &current, 22),
        Err(ArtifactAdmissionError::WithdrawalHeadChanged)
    );
}
