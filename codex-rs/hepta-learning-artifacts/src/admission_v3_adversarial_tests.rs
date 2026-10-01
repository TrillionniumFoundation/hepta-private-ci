use super::tests::digest;
use super::tests::id;
use super::tests::manifest;
use super::tests::scope;
use super::*;
use crate::DatasetWithdrawalNoticeV1;
use crate::test_support::FixtureValue;

#[test]
fn recomputed_public_receipt_cannot_admit_a_withdrawn_dataset() {
    let dataset = digest("dataset");
    let mut registry = DatasetWithdrawalRegistry::new_scoped(scope("a"));
    registry
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("notice"),
            dataset_digest: dataset,
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            authority_epoch: 1,
            issued_at: 15,
        })
        .fixture("withdrawal fixture");
    let validated_manifest = validate_artifact_manifest_v2(manifest(dataset), 20)
        .fixture("manifest shape is valid even though its dataset was withdrawn");
    let scope_digest = registry.scope_digest().fixture("scoped registry");
    let admission = WithdrawalBoundArtifactAdmissionV3 {
        admission_digest: digest_admission(
            validated_manifest.manifest_digest,
            scope_digest,
            registry.head_digest(),
            20,
        ),
        validated_manifest,
        withdrawal_scope_digest: scope_digest,
        withdrawal_head_digest: registry.head_digest(),
        admitted_at: 20,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert!(validate_artifact_publication_v3(&admission, &registry, 20).is_err());
}

#[test]
fn admission_timestamp_cannot_predate_manifest_creation() {
    let registry = DatasetWithdrawalRegistry::new_scoped(scope("a"));
    let mut admission = admit_manifest_at_withdrawal_head_v3(
        &registry,
        registry.head_digest(),
        manifest(digest("dataset")),
        20,
    )
    .fixture("valid admission fixture");
    admission.admitted_at = 9;
    admission.admission_digest = digest_admission(
        admission.validated_manifest.manifest_digest,
        admission.withdrawal_scope_digest,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    );
    assert!(verify_artifact_admission_v3(&admission, registry.head_digest(), 20).is_err());
}
