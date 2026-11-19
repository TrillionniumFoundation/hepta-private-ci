use super::*;

use crate::wire::CognitiveWireError;
use crate::wire::decode_wire_v1;
use crate::wire::encode_wire_v1;
use crate::write_receipt::MemoryWriteReceiptErrorV1;

fn constructor_receipts() -> Result<Vec<MemoryWriteReceiptV1>, Box<dyn std::error::Error>> {
    let input = intent();
    let mut receipts = Vec::new();
    for (disposition, committed_snapshot) in [
        (
            LegacyMemoryWriteDisposition::Inserted,
            snapshot(/*memory_frontier*/ 11),
        ),
        (
            LegacyMemoryWriteDisposition::Unchanged,
            snapshot(/*memory_frontier*/ 10),
        ),
    ] {
        let legacy = LegacyMemoryWriteReceiptV1 {
            intent_id: input.intent_id.clone(),
            record_id: id("record:binding"),
            record_digest: digest("record:binding"),
            committed_frontier: committed_snapshot.vector.memory_ledger_frontier,
            snapshot_key: committed_snapshot,
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipts.push(MemoryWriteReceiptV1::from_legacy_committed(
            &input,
            "writer:binding",
            /*issued_at_unix_ms*/ 1_000,
            &legacy,
        )?);
    }
    receipts.push(MemoryWriteReceiptV1::rejected(
        &input,
        "writer:binding",
        /*issued_at_unix_ms*/ 1_000,
        MemoryWriteRejectionCodeV1::AuthorizationRejected,
        /*observed_snapshot_digest*/ None,
        /*retryable*/ false,
    )?);
    Ok(receipts)
}

fn mutate_payload_and_recompute_outer_digest(
    original: &MemoryWriteReceiptV1,
    edits: &[(&str, serde_json::Value)],
) -> Result<(MemoryWriteReceiptV1, Vec<u8>), Box<dyn std::error::Error>> {
    // Parse actual canonical producer bytes so key order remains canonical
    // whether serde_json uses sorted maps or preserves insertion order.
    let mut envelope: serde_json::Value = serde_json::from_slice(&encode_wire_v1(original)?)?;
    for (key, value) in edits {
        let field = envelope["payload"]
            .get_mut(*key)
            .ok_or("expected producer payload field")?;
        *field = value.clone();
    }
    let unsealed: MemoryWriteReceiptV1 = serde_json::from_value(envelope["payload"].clone())?;
    envelope["payload"]["receiptDigest"] =
        serde_json::Value::String(unsealed.compute_receipt_digest().to_string());
    let forged: MemoryWriteReceiptV1 = serde_json::from_value(envelope["payload"].clone())?;
    assert_eq!(
        forged.receipt_digest().digest(),
        forged.compute_receipt_digest()
    );
    Ok((forged, serde_json::to_vec(&envelope)?))
}

#[test]
fn real_insert_unchanged_and_rejected_constructors_keep_canonical_roundtrips()
-> Result<(), Box<dyn std::error::Error>> {
    for receipt in constructor_receipts()? {
        receipt.validate()?;
        let wire = encode_wire_v1(&receipt)?;
        assert_eq!(decode_wire_v1::<MemoryWriteReceiptV1>(&wire)?, receipt);
        assert_eq!(
            decode_registered_wire_v1::<MemoryWriteReceiptV1>(&wire)?,
            receipt
        );
        assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    }
    Ok(())
}

#[test]
fn rehashed_outer_receipt_cannot_hide_inconsistent_intent_fields()
-> Result<(), Box<dyn std::error::Error>> {
    let alternative_digest =
        serde_json::Value::String(digest("different-intent-field").to_string());
    for receipt in constructor_receipts()? {
        for (field, replacement) in [
            (
                "intentId",
                serde_json::Value::String("intent:other".to_string()),
            ),
            ("candidateDigest", alternative_digest.clone()),
            ("expectedSnapshotDigest", alternative_digest.clone()),
            ("writerFenceDigest", alternative_digest.clone()),
            ("authorizationDigest", alternative_digest.clone()),
            ("intentDigest", alternative_digest.clone()),
        ] {
            // Unchanged commits independently bind the snapshot to their
            // outcome, so mutating that field reaches the older frontier
            // check first. Keep that error ordering as a separate assertion.
            let (forged, wire) =
                mutate_payload_and_recompute_outer_digest(&receipt, &[(field, replacement)])?;
            if field == "expectedSnapshotDigest"
                && matches!(
                    receipt.outcome(),
                    MemoryWriteOutcomeV1::Committed {
                        disposition:
                            crate::write_receipt::MemoryWriteCommitDispositionV1::Unchanged,
                        ..
                    }
                )
            {
                assert_eq!(
                    forged.validate(),
                    Err(MemoryWriteReceiptErrorV1::FrontierBindingMismatch)
                );
            } else {
                assert_eq!(
                    forged.validate(),
                    Err(MemoryWriteReceiptErrorV1::DigestMismatch)
                );
            }
            assert!(matches!(
                decode_wire_v1::<MemoryWriteReceiptV1>(&wire),
                Err(CognitiveWireError::Contract(_))
            ));
            assert!(decode_registered_wire_v1::<MemoryWriteReceiptV1>(&wire).is_err());
        }
    }
    Ok(())
}

#[test]
fn original_zero_time_error_still_precedes_new_intent_binding_check()
-> Result<(), Box<dyn std::error::Error>> {
    for receipt in constructor_receipts()? {
        let (forged, _) = mutate_payload_and_recompute_outer_digest(
            &receipt,
            &[
                ("issuedAtUnixMs", serde_json::json!(0)),
                (
                    "candidateDigest",
                    serde_json::Value::String(digest("different-candidate").to_string()),
                ),
            ],
        )?;
        assert_eq!(
            forged.validate(),
            Err(MemoryWriteReceiptErrorV1::ZeroIssuedAt)
        );
    }
    Ok(())
}
