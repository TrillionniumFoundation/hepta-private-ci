use super::EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION;
use super::EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS;
use super::EvidenceFrontierBackendError;
use super::EvidenceFrontierBackendIdentityV1;
use super::EvidenceFrontierHistoryRangeV1;

#[test]
fn backend_identity_requires_registered_ids_and_positive_generation() {
    let valid = EvidenceFrontierBackendIdentityV1 {
        schema_version: EVIDENCE_FRONTIER_BACKEND_IDENTITY_SCHEMA_VERSION,
        backend_id: "backend:kernel-evidence".to_string(),
        authority_id: "authority:kernel-evidence".to_string(),
        authority_generation: 3,
        storage_class: EVIDENCE_FRONTIER_BACKEND_STORAGE_CLASS.to_string(),
    };
    valid.validate().expect("valid backend identity");

    let mut invalid = valid.clone();
    invalid.authority_generation = 0;
    assert!(matches!(
        invalid.validate(),
        Err(EvidenceFrontierBackendError::Invalid(_))
    ));
}

#[test]
fn history_range_is_positive_ordered_and_bounded() {
    assert_eq!(
        EvidenceFrontierHistoryRangeV1::new(7, 9).expect("valid range"),
        EvidenceFrontierHistoryRangeV1 {
            first_generation: 7,
            last_generation: 9,
        }
    );
    assert!(EvidenceFrontierHistoryRangeV1::new(0, 1).is_err());
    assert!(EvidenceFrontierHistoryRangeV1::new(9, 7).is_err());
    assert!(EvidenceFrontierHistoryRangeV1::new(1, 4097).is_err());
}
