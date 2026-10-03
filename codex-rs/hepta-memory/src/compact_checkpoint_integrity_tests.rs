use super::*;

use pretty_assertions::assert_eq;

use crate::CompactCommitDecision;
use crate::CompactRejectReason;

#[test]
fn changed_summary_provenance_conflicts_after_journal_reopen() {
    let original = checkpoint();
    let original_digest = checkpoint_digest(&original).expect("digest");
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    journal
        .append_intent("op:provenance", &original, &snapshot())
        .expect("intent");
    journal
        .commit_checkpoint("op:provenance", &original_digest)
        .expect("commit");
    let retained = journal.snapshot();
    for changed in [
        {
            let mut value = original.clone();
            value.summary.model_receipt_sha256 = Sha256Digest::for_bytes(b"different-model");
            value
        },
        {
            let mut value = original.clone();
            value.summary.policy_digest = Sha256Digest::for_bytes(b"different-policy");
            value
        },
    ] {
        let changed_digest = checkpoint_digest(&changed).expect("valid changed checkpoint");
        assert_ne!(changed_digest, original_digest);
        let mut reopened = CompactPersistenceJournal::reopen(retained.clone()).expect("reopen");
        assert!(matches!(
            reopened.append_intent("op:provenance", &changed, &snapshot()),
            Err(CompactPersistenceError::CasConflict(_))
        ));
        assert_eq!(reopened.snapshot(), retained);
    }
}

fn assert_checkpoint_rejected(value: CompactCheckpoint) {
    assert_eq!(
        value.validate_against(&snapshot()),
        CompactCommitDecision::Rejected {
            reason: CompactRejectReason::InvalidPayload
        }
    );
    assert!(value.rehydration_plan(value.checkpoint_revision).is_err());
    assert!(checkpoint_digest(&value).is_err());
    let mut journal = CompactPersistenceJournal::new(fence()).expect("journal");
    let retained = journal.snapshot();
    assert!(matches!(
        journal.append_intent("op:invalid", &value, &snapshot()),
        Err(CompactPersistenceError::Invalid(_))
    ));
    assert_eq!(journal.snapshot(), retained);
}

#[test]
fn stale_loss_report_digest_is_rejected_at_every_checkpoint_entry() {
    let original = checkpoint();
    for changed in [
        {
            let mut value = original.clone();
            value.loss_report.omitted_event_ids.clear();
            value.loss_report.omitted_span_count = 0;
            value
        },
        {
            let mut value = original.clone();
            value.loss_report.semantic_loss_score_ppm = 1_000_001;
            value
        },
        {
            let mut value = original.clone();
            value.loss_report.report_sha256 = Sha256Digest::for_bytes(b"forged-loss");
            value
        },
    ] {
        let encoded = serde_json::to_vec(&changed).expect("serialize mutated payload");
        let decoded = serde_json::from_slice(&encoded).expect("decode untrusted fields");
        assert_checkpoint_rejected(decoded);
    }
}

#[test]
fn deserialized_loss_lists_must_retain_canonical_unique_order() {
    let mut original = checkpoint();
    original.loss_report =
        CompactLossReport::new(vec!["event:2".into(), "event:1".into()], 2, Vec::new(), 100)
            .expect("loss");
    for changed in [
        {
            let mut value = original.clone();
            value.loss_report.omitted_event_ids.reverse();
            value
        },
        {
            let mut value = original.clone();
            value.loss_report.omitted_event_ids.push("event:2".into());
            value
        },
        {
            let mut value = original.clone();
            value.loss_report.omitted_event_ids[0] = "event:\0hidden".into();
            value
        },
    ] {
        assert_checkpoint_rejected(changed);
    }
}

#[test]
fn constructor_rechecks_a_mutated_loss_report() {
    let original = checkpoint();
    let mut loss = original.loss_report.clone();
    loss.omitted_span_count += 1;
    assert!(
        CompactCheckpoint::new(
            original.checkpoint_id,
            original.lease,
            original.protected_refs,
            original.summary,
            loss,
            original.checkpoint_revision
        )
        .is_err()
    );
}

#[test]
fn imported_summary_and_parent_digests_must_have_canonical_sha256_shape() {
    let malformed: Sha256Digest =
        serde_json::from_str("\"not-a-sha256\"").expect("unvalidated digest wrapper");
    let original = checkpoint();
    for changed in [
        {
            let mut value = original.clone();
            value.summary.summary_sha256 = malformed.clone();
            value
        },
        {
            let mut value = original.clone();
            value.summary.model_receipt_sha256 = malformed.clone();
            value
        },
        {
            let mut value = original.clone();
            value.summary.policy_digest = malformed.clone();
            value
        },
        {
            let mut value = original.clone();
            let mut parent = snapshot();
            parent.expected_state_sha256 = malformed;
            value.lease = CompactLease::from_snapshot(parent);
            value
        },
    ] {
        assert_checkpoint_rejected(changed);
    }
}

#[test]
fn self_consistent_lease_hash_does_not_admit_invalid_parent_or_fence() {
    let original = snapshot();
    for parent in [
        {
            let mut value = original.clone();
            value.context_id.clear();
            value
        },
        {
            let mut value = original.clone();
            value.parent_event_start = value.parent_event_end + 1;
            value
        },
        {
            let mut value = original.clone();
            value.fence.authority_epoch = 0;
            value
        },
        {
            let mut value = original.clone();
            value.fence.owner_epoch = 0;
            value
        },
        {
            let mut value = original.clone();
            value.fence.generation = 0;
            value
        },
        {
            let mut value = original.clone();
            value.fence.fencing_token = "bad\0token".into();
            value
        },
    ] {
        let mut value = checkpoint();
        value.lease = CompactLease::from_snapshot(parent);
        assert_checkpoint_rejected(value);
    }
}

#[test]
fn checkpoint_use_rechecks_identity_and_protected_reference_payloads() {
    let original = checkpoint();
    for changed in [
        {
            let mut value = original.clone();
            value.checkpoint_id.clear();
            value
        },
        {
            let mut value = original.clone();
            value.protected_refs.push(value.protected_refs[0].clone());
            value
        },
        {
            let mut value = original.clone();
            value.protected_refs[0].ref_id.clear();
            value
        },
        {
            let mut value = original.clone();
            value.protected_refs[0].kind = "bad\0kind".into();
            value
        },
    ] {
        assert_checkpoint_rejected(changed);
    }
}

#[test]
fn legacy_checkpoint_envelope_does_not_gain_the_stronger_commitment() {
    let mut original = checkpoint();
    original.schema_version = 1;
    assert_checkpoint_rejected(original);
}

#[test]
fn valid_checkpoint_roundtrip_keeps_canonical_loss_and_lease_identity() {
    let original = checkpoint();
    let wire = serde_json::to_vec(&original).expect("wire");
    let decoded: CompactCheckpoint = serde_json::from_slice(&wire).expect("decoded");
    assert_eq!(decoded, original);
    assert_eq!(checkpoint_digest(&decoded), checkpoint_digest(&original));
    assert_eq!(decoded.lease, CompactLease::from_snapshot(snapshot()));
    assert!(
        decoded
            .rehydration_plan(decoded.checkpoint_revision)
            .is_ok()
    );
}

// Frozen output from the original df95fd5d implementation; never regenerated
// from the strengthened checkpoint constructor. Journal v2 remains readable.
const LEGACY_JOURNAL_V2: &str = r#"{
  "schema_version": 2,
  "namespace": "local_development_only",
  "fence": {
    "authority_epoch": 3,
    "owner_epoch": 8,
    "generation": 19,
    "fencing_token": "fence:19"
  },
  "entries": [
    {
      "schema_version": 2,
      "namespace": "local_development_only",
      "sequence": 1,
      "operation_id": "op:1",
      "authority_epoch": 3,
      "owner_epoch": 8,
      "generation": 19,
      "fencing_token": "fence:19",
      "kind": {
        "kind": "intent",
        "checkpoint_id": "ctxcp:local-development",
        "checkpoint_revision": 0,
        "checkpoint_sha256": "f7016c0b61e5ec673f9d553164e23254c91501e21e1ecd761e2e8d18e060e440",
        "parent_sha256": "773d9e31906e491c2f93086a4993258841dd7b667d686c044cedd3370b786d80"
      },
      "previous_sha256": "263ac6ac3d56b25abd820979b8bb1d7a8fc1ce19b2f17668d61b9582e2c0c0b0",
      "event_sha256": "7ffbbbb1873f8c7be8a2065eb76089e5fc98b0b1d53193717e23cdce3146a644"
    },
    {
      "schema_version": 2,
      "namespace": "local_development_only",
      "sequence": 2,
      "operation_id": "op:1",
      "authority_epoch": 3,
      "owner_epoch": 8,
      "generation": 19,
      "fencing_token": "fence:19",
      "kind": {
        "kind": "checkpoint_committed",
        "checkpoint_sha256": "f7016c0b61e5ec673f9d553164e23254c91501e21e1ecd761e2e8d18e060e440"
      },
      "previous_sha256": "7ffbbbb1873f8c7be8a2065eb76089e5fc98b0b1d53193717e23cdce3146a644",
      "event_sha256": "4984588e31d22c3d3f6e8e83c015a89b07a2a63dcf4eafa9ce6c309a1a07d8c8"
    },
    {
      "schema_version": 2,
      "namespace": "local_development_only",
      "sequence": 3,
      "operation_id": "op:1",
      "authority_epoch": 3,
      "owner_epoch": 8,
      "generation": 19,
      "fencing_token": "fence:19",
      "kind": {
        "kind": "rehydrated",
        "checkpoint_sha256": "f7016c0b61e5ec673f9d553164e23254c91501e21e1ecd761e2e8d18e060e440",
        "expected_revision": 0
      },
      "previous_sha256": "4984588e31d22c3d3f6e8e83c015a89b07a2a63dcf4eafa9ce6c309a1a07d8c8",
      "event_sha256": "005fea2e771514d2451adfd26231eed4e0ad3088dbaf6c5c322b0177a1fa92f8"
    }
  ],
  "head_sha256": "005fea2e771514d2451adfd26231eed4e0ad3088dbaf6c5c322b0177a1fa92f8"
}"#;
const LEGACY_CHECKPOINT_V1: &str = r#"{
  "schema_version": 1,
  "namespace": "local_development_only",
  "checkpoint_id": "ctxcp:local-development",
  "lease": {
    "schema_version": 1,
    "namespace": "local_development_only",
    "lease_id": "ctxlease:v1:036abfe432bbbac825dc7e41f44cca556c381deb77b29d6aa29c9ddae3e2a074",
    "snapshot": {
      "context_id": "ctx:local-development",
      "parent_event_start": 20,
      "parent_event_end": 30,
      "expected_parent_revision": 7,
      "expected_state_sha256": "7c1a8226fe4a8e36b206a6f3e365b4e53ae0057d420a60265d87a4c4ea4488e4",
      "fence": {
        "authority_epoch": 3,
        "owner_epoch": 8,
        "generation": 19,
        "fencing_token": "fence:19"
      }
    },
    "lease_sha256": "036abfe432bbbac825dc7e41f44cca556c381deb77b29d6aa29c9ddae3e2a074"
  },
  "protected_refs": [
    {
      "ref_id": "approval:1",
      "kind": "approval",
      "required": true
    }
  ],
  "summary": {
    "summary_sha256": "761b7ad8ad439b2855fcbb611331c646ef0870b0631247bba3f3025cb6df5a53",
    "model_receipt_sha256": "9372c470eeadd5ecd9c3c74c2b3cb633f8e2f2fad799250a0f70d652b6b825e4",
    "policy_digest": "823412d1eacb67956220e532959f0104603057c88704863ca38e7cd188fda812",
    "fact_admission": false
  },
  "loss_report": {
    "omitted_event_ids": [
      "event:29"
    ],
    "omitted_span_count": 1,
    "protected_refs_lost": [],
    "semantic_loss_score_ppm": 0,
    "report_sha256": "859a322064dd9bbe6925a89494292ba1421ac52a89d97c584af8b774bd6ec1af"
  },
  "checkpoint_revision": 0
}"#;

#[test]
fn historical_journal_stays_readable_without_upgrading_weak_checkpoint_identity() {
    let retained: crate::CompactPersistenceSnapshot =
        serde_json::from_str(LEGACY_JOURNAL_V2).expect("legacy journal");
    let legacy_checkpoint: CompactCheckpoint =
        serde_json::from_str(LEGACY_CHECKPOINT_V1).expect("legacy checkpoint");
    let mut reopened =
        CompactPersistenceJournal::reopen(retained.clone()).expect("audit old history");
    assert_eq!(reopened.snapshot(), retained);
    assert_eq!(
        reopened.state("op:1"),
        Some(CompactPersistenceState::Committed)
    );
    assert_checkpoint_rejected(legacy_checkpoint);
    let fresh = checkpoint();
    assert!(matches!(
        reopened.append_intent("op:1", &fresh, &snapshot()),
        Err(CompactPersistenceError::CasConflict(_))
    ));
    assert_eq!(reopened.snapshot(), retained);
    assert!(matches!(
        reopened.append_intent("op:v2", &fresh, &snapshot()),
        Ok(CompactPersistenceAppend::Appended { .. })
    ));
}

#[tokio::test]
async fn sqlite_store_reopens_old_journal_without_admitting_weak_checkpoint_payloads() {
    let retained: crate::CompactPersistenceSnapshot =
        serde_json::from_str(LEGACY_JOURNAL_V2).expect("legacy journal");
    let legacy: CompactCheckpoint =
        serde_json::from_str(LEGACY_CHECKPOINT_V1).expect("legacy checkpoint");
    let temp = tempfile::TempDir::new().expect("temporary store");
    let owner = crate::cognitive_test_support::agent_id(/*suffix*/ 99);
    let layout = crate::cognitive_test_support::layout(&temp, &owner);
    let store = crate::CognitiveStore::open(&layout).await.expect("store");
    let executor = store
        .open_local_compact_executor("journal:legacy-v2", retained.fence.clone())
        .await
        .expect("executor");
    let mut transaction = store.pool.begin().await.expect("transaction");
    for event in &retained.entries {
        executor
            .insert_event(&mut transaction, event)
            .await
            .expect("retain original historical event");
    }
    transaction.commit().await.expect("commit fixture history");
    drop(executor);
    store.pool.close().await;
    drop(store);

    let store = crate::CognitiveStore::open(&layout)
        .await
        .expect("old compact history must not quarantine the whole store");
    let executor = store
        .open_local_compact_executor("journal:legacy-v2", retained.fence.clone())
        .await
        .expect("historical executor");
    assert_eq!(executor.snapshot().await.expect("snapshot"), retained);
    assert!(matches!(
        executor
            .read_rehydration("op:1", &legacy, /*expected_revision*/ 0)
            .await,
        Err(crate::LocalCompactExecutorError::Invalid(_))
    ));
    assert!(matches!(
        executor
            .read_rehydration("op:1", &checkpoint(), /*expected_revision*/ 0)
            .await,
        Err(crate::LocalCompactExecutorError::Corrupt(_))
    ));
    assert_eq!(
        executor.snapshot().await.expect("unchanged history"),
        retained
    );
    drop(executor);
    store.pool.close().await;
}
