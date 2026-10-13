use super::*;

fn id(value: &str) -> codex_hepta_types::StableId {
    codex_hepta_types::StableId::new(value).expect("id")
}

fn digest(seed: u8) -> codex_hepta_types::Digest32 {
    codex_hepta_types::Digest32::from_array([seed; 32])
}

#[test]
fn canary_receipt_binds_dispatch_fence_generation_and_rollback() {
    let receipt = CellSplitCanaryReceiptV1::new(
        id("split.1"),
        codex_hepta_types::Generation::new(8).expect("generation"),
        digest(1),
        digest(2),
        digest(3),
        10,
        0,
        true,
    )
    .expect("receipt");
    receipt.verify_digest().expect("digest");
    let mut tampered = receipt;
    tampered.observed_requests = 11;
    assert_eq!(
        tampered.verify_digest(),
        Err(CellSplitLifecycleErrorV1::Digest)
    );
}

#[test]
fn canary_rejects_failed_count_above_observed() {
    assert_eq!(
        CellSplitCanaryReceiptV1::new(
            id("split.2"),
            codex_hepta_types::Generation::new(2).expect("generation"),
            digest(1),
            digest(2),
            digest(3),
            1,
            2,
            false,
        ),
        Err(CellSplitLifecycleErrorV1::InvalidEvidence)
    );
}

#[test]
fn zero_observation_canary_cannot_qualify_retention() {
    assert_eq!(
        CellSplitCanaryReceiptV1::new(
            id("split.zero"),
            codex_hepta_types::Generation::new(8).expect("generation"),
            digest(1),
            digest(2),
            digest(3),
            0,
            0,
            true,
        ),
        Err(CellSplitLifecycleErrorV1::InvalidEvidence)
    );

    // Defense in depth: a pre-existing, digest-consistent legacy record
    // with zero observed requests cannot silently pass retention.
    let mut legacy = CellSplitCanaryReceiptV1::new(
        id("split.legacy"),
        codex_hepta_types::Generation::new(8).expect("generation"),
        digest(1),
        digest(2),
        digest(3),
        1,
        0,
        true,
    )
    .expect("valid starting receipt");
    legacy.observed_requests = 0;
    legacy.receipt_digest = legacy.digest();
    assert!(!legacy.passes());
    assert_eq!(
        legacy.verify_digest(),
        Err(CellSplitLifecycleErrorV1::InvalidEvidence)
    );
}

#[test]
fn digest_consistent_but_invalid_canary_must_not_pass_retention() {
    let original = CellSplitCanaryReceiptV1::new(
        id("split.forged"),
        codex_hepta_types::Generation::new(8).expect("generation"),
        digest(1),
        digest(2),
        digest(3),
        10,
        0,
        true,
    )
    .expect("valid baseline");

    // An adversary can recompute an *unkeyed* SHA-256 receipt digest after
    // deleting a mandatory dispatch, old-route fence or child-route anchor.
    // The resulting digest remains self-consistent but proves no admission.
    for missing in 0..3 {
        let mut forged = original.clone();
        match missing {
            0 => forged.dispatch_receipt_digest = codex_hepta_types::Digest32::ZERO,
            1 => forged.old_route_fence_digest = codex_hepta_types::Digest32::ZERO,
            _ => forged.child_route_digest = codex_hepta_types::Digest32::ZERO,
        }
        forged.receipt_digest = forged.digest();
        assert_eq!(
            forged.verify_digest(),
            Err(CellSplitLifecycleErrorV1::InvalidEvidence),
        );
        assert!(!forged.passes());
    }

    let mut impossible = original;
    impossible.failed_requests = impossible.observed_requests + 1;
    impossible.receipt_digest = impossible.digest();
    assert_eq!(
        impossible.verify_digest(),
        Err(CellSplitLifecycleErrorV1::InvalidEvidence),
    );
    assert!(!impossible.passes());
}
