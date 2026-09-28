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

#[test]
fn history_range_accepts_the_inclusive_limit_and_preserves_endpoints() {
    for first in [1_u64, 2, 4096, u64::MAX - 4095] {
        let last = first + 4095;
        let range = EvidenceFrontierHistoryRangeV1::new(first, last)
            .expect("exactly 4096 generations fit the policy");
        assert_eq!(
            (range.first_generation(), range.last_generation()),
            (first, last)
        );
    }
    let singleton = EvidenceFrontierHistoryRangeV1::new(u64::MAX, u64::MAX)
        .expect("last generation is a valid singleton");
    assert_eq!(
        (singleton.first_generation(), singleton.last_generation()),
        (u64::MAX, u64::MAX)
    );
}

#[test]
fn history_range_rejects_overflow_zero_and_every_oversized_boundary() {
    for (first, last) in [
        (0, 0),
        (0, u64::MAX),
        (1, u64::MAX),
        (u64::MAX, 1),
        (u64::MAX - 4096, u64::MAX),
    ] {
        assert!(matches!(
            EvidenceFrontierHistoryRangeV1::new(first, last),
            Err(EvidenceFrontierBackendError::Invalid(_))
        ));
    }
    for first in 1_u64..=512 {
        for width in [0_u64, 1, 4094, 4095, 4096, 8192] {
            let range = EvidenceFrontierHistoryRangeV1::new(first, first + width);
            assert_eq!(range.is_ok(), width < 4096);
        }
    }
}
