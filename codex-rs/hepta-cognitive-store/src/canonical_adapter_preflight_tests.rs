use super::*;

use std::cell::Cell;

use codex_hepta_cognitive_types::write_receipt::MemoryWriteReceiptErrorV1;

use crate::CanonicalCognitiveStoreV1Ext;
use crate::CanonicalStoreAdapterErrorV1;

#[derive(Default)]
struct CountingVerifier {
    calls: Cell<usize>,
}

impl StoreAuthorityVerifierV2 for CountingVerifier {
    fn verify(
        &self,
        operation_id: &StableId,
        payload_digest: Digest32,
        authorization_digest: Digest32,
    ) -> Result<(), CognitiveStoreV2Error> {
        self.calls.set(self.calls.get() + 1);
        Verifier.verify(operation_id, payload_digest, authorization_digest)
    }
}

#[test]
fn invalid_canonical_metadata_cannot_change_existing_ledger_or_intent_journal()
-> Result<(), Box<dyn std::error::Error>> {
    for (writer_id, issued_at_unix_ms) in [("", 10), ("writer:canonical", 0), ("", 0)] {
        let mut store = store();
        let existing = candidate(
            "memory:existing",
            "prior-content",
            MemoryAdmissionKind::Observation,
        );
        let existing_intent = intent(&store, "intent:existing", &existing);
        store.append_admitted(&Verifier, existing, existing_intent)?;
        let before = store.export_image()?;
        let value = candidate("memory:new", "new-content", MemoryAdmissionKind::Inference);
        let write_intent = intent(&store, "intent:new", &value);
        let verifier = CountingVerifier::default();

        let result = store.append_admitted_canonical(
            &verifier,
            value.clone(),
            write_intent.clone(),
            writer_id,
            issued_at_unix_ms,
        );
        if writer_id.is_empty() {
            assert!(matches!(
                result,
                Err(CanonicalStoreAdapterErrorV1::Receipt(
                    MemoryWriteReceiptErrorV1::Identifier(_)
                ))
            ));
        } else {
            assert!(matches!(
                result,
                Err(CanonicalStoreAdapterErrorV1::Receipt(
                    MemoryWriteReceiptErrorV1::ZeroIssuedAt
                ))
            ));
        }
        assert_eq!(verifier.calls.get(), 0);
        // The image contains the snapshot, sequence, complete revision history,
        // and intent journal. This is an in-memory check, not a disk transaction.
        assert_eq!(store.export_image()?, before);

        let accepted = store.append_admitted_canonical(
            &verifier,
            value.clone(),
            write_intent.clone(),
            "writer:canonical",
            /*issued_at_unix_ms*/ 10,
        )?;
        accepted.validate()?;
        assert_eq!(verifier.calls.get(), 1);
        let committed = store.export_image()?;
        let retried = store.append_admitted_canonical(
            &verifier,
            value,
            write_intent,
            "writer:canonical",
            /*issued_at_unix_ms*/ 10,
        )?;
        assert_eq!(retried, accepted);
        assert_eq!(store.export_image()?, committed);
        // Exact intent retries keep the existing writer's idempotent behavior.
        assert_eq!(verifier.calls.get(), 1);
    }
    Ok(())
}

#[test]
fn canonical_valid_metadata_preserves_legacy_commit_and_retry_results()
-> Result<(), Box<dyn std::error::Error>> {
    let mut legacy = store();
    let mut canonical = store();
    let first = candidate(
        "memory:first",
        "content:first",
        MemoryAdmissionKind::Observation,
    );
    let first_intent = intent(&canonical, "intent:first", &first);
    let expected = legacy.append_admitted(&Verifier, first.clone(), first_intent.clone())?;
    let actual = canonical.append_admitted_canonical(
        &Verifier,
        first.clone(),
        first_intent.clone(),
        "writer:canonical",
        /*issued_at_unix_ms*/ 10,
    )?;
    actual.validate()?;
    assert_eq!(actual.compatibility_receipt, expected);
    assert_eq!(canonical.export_image()?, legacy.export_image()?);

    let second = candidate(
        "memory:second",
        "content:second",
        MemoryAdmissionKind::Inference,
    );
    let second_intent = intent(&canonical, "intent:second", &second);
    legacy.append_admitted(&Verifier, second.clone(), second_intent.clone())?;
    canonical.append_admitted_canonical(
        &Verifier,
        second,
        second_intent,
        "writer:canonical",
        /*issued_at_unix_ms*/ 11,
    )?;
    let after_unrelated = canonical.export_image()?;
    let retried = canonical.append_admitted_canonical(
        &Verifier,
        first.clone(),
        first_intent.clone(),
        "writer:canonical",
        /*issued_at_unix_ms*/ 10,
    )?;
    assert_eq!(retried, actual);
    assert_eq!(canonical.export_image()?, after_unrelated);
    assert_eq!(canonical.export_image()?, legacy.export_image()?);
    assert_eq!(
        legacy.append_admitted(&Verifier, first, first_intent)?,
        expected
    );
    Ok(())
}

#[test]
fn canonical_valid_metadata_preserves_store_rejection_order_and_state()
-> Result<(), Box<dyn std::error::Error>> {
    for fault in ["candidate", "intent_binding", "authority"] {
        let mut legacy = store();
        let mut canonical = store();
        let before = canonical.export_image()?;
        let mut value = candidate(
            "memory:new",
            "content:new",
            MemoryAdmissionKind::Observation,
        );
        let mut write_intent = intent(&canonical, "intent:new", &value);
        match fault {
            "candidate" => value.policy_digest = Digest32::ZERO,
            "intent_binding" => write_intent.candidate_digest = digest("other-candidate"),
            "authority" => write_intent.authorization_digest = digest("wrong-authorization"),
            _ => unreachable!(),
        }
        let expected = legacy
            .append_admitted(&Verifier, value.clone(), write_intent.clone())
            .expect_err("legacy writer must reject this real input");
        let actual = canonical.append_admitted_canonical(
            &Verifier,
            value,
            write_intent,
            "writer:canonical",
            /*issued_at_unix_ms*/ 10,
        );
        let Err(CanonicalStoreAdapterErrorV1::Store(actual)) = actual else {
            panic!("valid canonical metadata must preserve the store error: {fault}");
        };
        assert_eq!(actual, expected);
        assert_eq!(canonical.export_image()?, before);
        assert_eq!(legacy.export_image()?, before);
    }
    Ok(())
}
