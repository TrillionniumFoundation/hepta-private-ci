//! Every admitted V2 observation must fit the frozen HPTC V1 container profile.
use codex_hepta_types::Digest32;
use codex_hepta_types::PromptDeliveryObservationV1;
use codex_hepta_types::StableId;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryErrorV2;
use codex_hepta_types::prompt_delivery_v2::PromptDeliveryObservationV2;

fn legacy(count: u32) -> PromptDeliveryObservationV1 {
    PromptDeliveryObservationV1 {
        compilation_id: StableId::new("compilation-1").expect("id"),
        provider_request_digest: Digest32::of_bytes(b"request"),
        delivered: true,
        rejected_reason: None,
        observed_token_positions: Some((0..count).collect()),
        truncation_observed: false,
    }
}

#[test]
fn admitted_position_boundaries_are_hashable_without_truncation() {
    for count in [1_u32, 4_095, 4_096, 4_097, 8_192, 8_193] {
        let original = legacy(count);
        let admitted = PromptDeliveryObservationV2::new(
            original.compilation_id.clone(),
            original.provider_request_digest,
            original.delivered,
            /*rejected_reason*/ None,
            original.observed_token_positions.clone(),
            original.truncation_observed,
            /*legacy_v1_digest*/ None,
        );
        if count <= 4_096 {
            let value = admitted.expect("within V2 capacity");
            assert_eq!(
                value.observed_token_positions(),
                original.observed_token_positions.as_deref()
            );
            assert!(
                value.semantic_digest().is_ok(),
                "accepted {count} positions must hash"
            );
        } else {
            assert_eq!(
                admitted,
                Err(PromptDeliveryErrorV2::TokenPositionLimitExceeded)
            );
        }
    }
}

#[test]
fn v1_migration_preserves_old_identity_or_rejects_without_truncation() {
    for count in [1_u32, 4_096, 4_097, 8_192] {
        let original = legacy(count);
        let old_digest = original.semantic_digest().expect("V1 remains supported");
        let migrated = PromptDeliveryObservationV2::from_v1(&original);
        if count <= 4_096 {
            let value = migrated.expect("migration fits V2");
            assert_eq!(value.legacy_v1_digest(), Some(old_digest));
            assert_eq!(
                value.observed_token_positions(),
                original.observed_token_positions.as_deref()
            );
            assert!(value.semantic_digest().is_ok());
        } else {
            assert_eq!(
                migrated,
                Err(PromptDeliveryErrorV2::TokenPositionLimitExceeded)
            );
        }
        assert_eq!(original.semantic_digest(), Ok(old_digest));
        assert_eq!(
            original.observed_token_positions.as_ref().map(Vec::len),
            Some(count as usize)
        );
    }
}
