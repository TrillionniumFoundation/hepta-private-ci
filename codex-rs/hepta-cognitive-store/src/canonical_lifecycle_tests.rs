use codex_hepta_cognitive_types::hnmf::ContractDigestV1;

use super::*;

#[test]
fn canonical_tombstone_reason_must_match_the_exact_durable_utf8_reason() {
    let reason = "用户要求删除记忆";
    let durable = MemoryLifecycleState::Tombstoned {
        reason: reason.to_string(),
    };
    let canonical = MemoryLifecycleV1::Tombstoned {
        reason_sha256: ContractDigestV1::from_digest(Digest32::of_bytes(reason.as_bytes()))
            .expect("nonzero reason digest"),
    };
    assert_eq!(validate_lifecycle_binding(&durable, &canonical), Ok(()));

    let changed_reason = MemoryLifecycleState::Tombstoned {
        reason: format!("{reason} "),
    };
    assert_eq!(
        validate_lifecycle_binding(&changed_reason, &canonical),
        Err(CognitiveStoreV2Error::CanonicalDurableStateMismatch),
    );
    assert_eq!(
        validate_lifecycle_binding(&durable, &MemoryLifecycleV1::Active),
        Err(CognitiveStoreV2Error::CanonicalDurableStateMismatch),
    );
}
