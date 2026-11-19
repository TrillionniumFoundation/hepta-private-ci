use super::*;

use codex_hepta_cognitive_types::consumer::CognitiveConsumerV1;
use codex_hepta_cognitive_types::consumer::ConsumerConvergenceErrorV1;
use codex_hepta_cognitive_types::consumer::ShadowComparisonReceiptV1;

use crate::CanonicalCognitiveStoreV1Ext;
use crate::CanonicalMemoryWriteV1;
use crate::CanonicalStoreAdapterErrorV1;

fn canonical_write(
    store: &mut AdmittedCognitiveStoreV2,
    record_id: &str,
) -> Result<CanonicalMemoryWriteV1, CanonicalStoreAdapterErrorV1> {
    let value = candidate(
        record_id,
        "canonical-content",
        MemoryAdmissionKind::Inference,
    );
    let write_intent = intent(store, &format!("intent:{record_id}"), &value);
    store.append_admitted_canonical(
        &Verifier,
        value,
        write_intent,
        "writer:canonical",
        /*issued_at_unix_ms*/ 10,
    )
}

#[test]
fn another_real_write_shadow_cannot_attest_this_write() -> Result<(), Box<dyn std::error::Error>> {
    let mut store = store();
    let mut first = canonical_write(&mut store, "record:first")?;
    let second = canonical_write(&mut store, "record:second")?;
    first.validate()?;
    second.validate()?;
    let image = store.export_image()?;
    first.shadow_receipt = second.shadow_receipt;
    first.shadow_receipt.validate()?;
    assert!(first.shadow_receipt.cutover_eligible());
    assert!(matches!(
        first.validate(),
        Err(CanonicalStoreAdapterErrorV1::SemanticMismatch)
    ));
    assert_eq!(store.export_image()?, image);
    Ok(())
}

#[test]
fn self_consistent_shadow_must_bind_the_actual_id_consumer_and_digest_pair()
-> Result<(), Box<dyn std::error::Error>> {
    let mut store = store();
    let original = canonical_write(&mut store, "record:first")?;
    let shadow = &original.shadow_receipt;
    for alternative in [
        ShadowComparisonReceiptV1::new(
            id("intent:other"),
            shadow.consumer,
            shadow.legacy_digest,
            shadow.canonical_digest,
            shadow.observed_at_unix_ms,
        )?,
        ShadowComparisonReceiptV1::new(
            shadow.comparison_id.clone(),
            CognitiveConsumerV1::CognitiveRead,
            shadow.legacy_digest,
            shadow.canonical_digest,
            shadow.observed_at_unix_ms,
        )?,
        ShadowComparisonReceiptV1::new(
            shadow.comparison_id.clone(),
            shadow.consumer,
            Some(digest("unrelated-comparison")),
            Some(digest("unrelated-comparison")),
            shadow.observed_at_unix_ms,
        )?,
    ] {
        alternative.validate()?;
        assert!(alternative.cutover_eligible());
        let mut changed = original.clone();
        changed.shadow_receipt = alternative;
        assert!(matches!(
            changed.validate(),
            Err(CanonicalStoreAdapterErrorV1::SemanticMismatch)
        ));
    }
    original.validate()?;
    Ok(())
}

#[test]
fn comparison_time_remains_metadata_and_original_shadow_error_precedes_binding()
-> Result<(), Box<dyn std::error::Error>> {
    let mut store = store();
    let mut write = canonical_write(&mut store, "record:first")?;
    let shadow = &write.shadow_receipt;
    write.shadow_receipt = ShadowComparisonReceiptV1::new(
        shadow.comparison_id.clone(),
        shadow.consumer,
        shadow.legacy_digest,
        shadow.canonical_digest,
        shadow.observed_at_unix_ms + 1,
    )?;
    // This repair binds the comparison to its operands; it does not invent a
    // new freshness/clock rule or require observation time to equal issue time.
    write.validate()?;
    write.shadow_receipt.consumer = CognitiveConsumerV1::CognitiveRead;
    assert!(matches!(
        write.validate(),
        Err(CanonicalStoreAdapterErrorV1::Consumer(
            ConsumerConvergenceErrorV1::DigestMismatch
        ))
    ));
    Ok(())
}
