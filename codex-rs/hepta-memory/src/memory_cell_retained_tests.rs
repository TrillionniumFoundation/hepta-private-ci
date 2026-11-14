use pretty_assertions::assert_eq;

use super::*;
use crate::production_writer::memory_cell_test_support::fixture;

fn encoded(claim: &MemoryCellSourceClaimV1) -> serde_json::Value {
    serde_json::json!({"event": claim.event, "production": claim.production})
}

#[tokio::test]
async fn retained_receipt_round_trips_but_self_consistent_forgery_has_no_owner_authority() {
    let f = fixture().await;
    let bytes = serde_json::to_vec(&encoded(&f.claim)).unwrap();
    let recovered = decode_retained_memory_cell_source_claim_v1(&bytes).unwrap();
    assert_eq!(recovered, f.claim);
    f.writer
        .authorize_memory_cell(&f.access, &f.query, &recovered)
        .await
        .unwrap();
    let mut forged = recovered;
    forged.production.authority_grant_digest =
        Sha256Digest::for_bytes(b"not an admitted source authority");
    let stale_bytes = serde_json::to_vec(&encoded(&forged)).unwrap();
    assert!(decode_retained_memory_cell_source_claim_v1(&stale_bytes).is_err());
    forged.production.receipt_sha256 = forged.production.compute_receipt_sha256();
    let self_consistent = decode_retained_memory_cell_source_claim_v1(
        &serde_json::to_vec(&encoded(&forged)).unwrap(),
    )
    .unwrap();
    assert!(
        f.writer
            .authorize_memory_cell(&f.access, &f.query, &self_consistent)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn retained_claim_rejects_nested_extensions_and_invalid_opaque_generation() {
    let f = fixture().await;
    for pointer in [
        "/production/write/projection",
        "/production/write/memory/id",
        "/production/write/source",
        "/production/write/memory/scope",
        "/production/write/memory/lifecycle",
    ] {
        let mut value = encoded(&f.claim);
        value
            .pointer_mut(pointer)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("unknown".into(), serde_json::json!(true));
        assert!(
            decode_retained_memory_cell_source_claim_v1(&serde_json::to_vec(&value).unwrap())
                .is_err(),
            "{pointer}"
        );
    }
    for generation in [
        serde_json::json!(0),
        serde_json::json!(u64::MAX),
        serde_json::json!(-1),
        serde_json::json!("1"),
    ] {
        let mut value = encoded(&f.claim);
        value["production"]["write"]["projection"]["generation"] = generation;
        assert!(
            decode_retained_memory_cell_source_claim_v1(&serde_json::to_vec(&value).unwrap())
                .is_err()
        );
    }
    assert!(decode_retained_memory_cell_source_claim_v1(&vec![b' '; 1_048_577]).is_err());
}
