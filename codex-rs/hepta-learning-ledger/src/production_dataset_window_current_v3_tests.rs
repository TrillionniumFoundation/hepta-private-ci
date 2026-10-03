use super::*;
use crate::authenticate_ledger_snapshot_prefix_v3;
use crate::verify_dataset_window_snapshot_against_current_ledger_v3;

#[test]
fn unrelated_chat_tail_preserves_exact_original_prefix_payload_and_receipt_without_writes() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    add_outcome(&mut writer, "a", "1", None, 100);
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    let frozen = writer.snapshot().unwrap();
    let payload = dataset_window_freeze_signing_payload_v3(&frozen, &p).unwrap();
    add_decision(&mut writer, "normal-chat");
    add_outcome(&mut writer, "normal-chat", "1", None, 100);
    add_credit(&mut writer, "normal-chat", "1", 100);
    let current = writer.snapshot().unwrap();
    let before = (
        fs::read(fixture.root.join("ledger")).unwrap(),
        fs::read(fixture.root.join("witness")).unwrap(),
        writer.witness_frontier().unwrap(),
    );
    assert_ne!(current.head_digest, frozen.head_digest);
    assert!(verify_dataset_window_snapshot_against_ledger_v3(&receipt, &p, &current, 50).is_err());
    writer
        .revalidate_dataset_snapshot(&receipt.receipt, 50)
        .unwrap();
    let returned =
        verify_dataset_window_snapshot_against_current_ledger_v3(&receipt, &p, &current, 50)
            .unwrap();
    assert_eq!(returned, frozen);
    assert_eq!(
        dataset_window_freeze_signing_payload_v3(&returned, &p).unwrap(),
        payload
    );
    assert_eq!(
        freeze(&writer, p).receipt.snapshot.source_record_digests,
        receipt.receipt.snapshot.source_record_digests
    );
    assert_eq!(
        before,
        (
            fs::read(fixture.root.join("ledger")).unwrap(),
            fs::read(fixture.root.join("witness")).unwrap(),
            writer.witness_frontier().unwrap(),
        )
    );
}

#[test]
fn selected_late_outcome_credit_and_correction_each_invalidate_frozen_window() {
    for change in 0..3 {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let a = add_decision(&mut writer, "a");
        let b = add_decision(&mut writer, "b");
        add_outcome(&mut writer, "b", "1", None, 100);
        if change != 0 {
            add_outcome(&mut writer, "a", "1", None, 100);
        }
        let p = plan(a.sequence.get(), b.sequence.get());
        let receipt = freeze(&writer, p.clone());
        match change {
            0 => {
                add_outcome(&mut writer, "a", "1", None, 100);
            }
            1 => {
                add_credit(&mut writer, "a", "1", 100);
            }
            2 => {
                add_outcome(&mut writer, "a", "2", Some("outcome-a-1"), 120);
            }
            _ => unreachable!(),
        }
        assert!(
            verify_dataset_window_snapshot_against_current_ledger_v3(
                &receipt,
                &p,
                &writer.snapshot().unwrap(),
                50,
            )
            .is_err(),
            "selected tail change {change}"
        );
    }
}

#[test]
fn selected_revocation_and_unrelated_unlearning_invalidate_complete_historical_cut() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    let b = add_decision(&mut writer, "b");
    add_outcome(&mut writer, "a", "1", None, 100);
    add_outcome(&mut writer, "b", "1", None, 100);
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    let original = writer.snapshot().unwrap();
    let mut core = LearningLedger::from_snapshot(original.clone()).unwrap();
    core.append(LedgerEvent::Revocation(crate::Revocation {
        record_id: id("selected-revocation"),
        target_record_id: id("decision-a"),
        authority_id: id("privacy-owner"),
        reason_digest: digest("withdraw-selected"),
    }))
    .unwrap();
    assert!(
        verify_dataset_window_snapshot_against_current_ledger_v3(
            &receipt,
            &p,
            &core.snapshot(),
            50,
        )
        .is_err()
    );
    let outside = freeze(&writer, plan(b.sequence.get(), b.sequence.get()));
    let request = UnlearningLineageRequestV1 {
        record_id: id("unrelated-unlearning"),
        lineage_id: id("unrelated-lineage"),
        source_record_id: id("outcome-record-b-1"),
        dataset_snapshot_id: outside.receipt.snapshot.snapshot_id.clone(),
        dataset_digest: outside.receipt.snapshot.dataset_digest,
        artifact_id: id("artifact-a"),
        reason_digest: digest("withdraw-unrelated"),
    };
    let evidence = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&request),
    );
    writer
        .append_unlearning(
            original.head_digest,
            request,
            &outside.receipt,
            &evidence,
            50,
        )
        .unwrap();
    writer
        .revalidate_dataset_snapshot(&receipt.receipt, 50)
        .unwrap();
    assert!(
        verify_dataset_window_snapshot_against_current_ledger_v3(
            &receipt,
            &p,
            &writer.snapshot().unwrap(),
            50,
        )
        .is_err()
    );
}

#[test]
fn foreign_prefix_corrupt_tail_and_expired_producer_never_revalidate() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    add_outcome(&mut writer, "a", "1", None, 100);
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    let foreign_fixture = Fixture::new();
    let mut foreign = foreign_fixture.writer();
    add_decision(&mut foreign, "foreign");
    add_outcome(&mut foreign, "foreign", "1", None, 100);
    assert!(
        verify_dataset_window_snapshot_against_current_ledger_v3(
            &receipt,
            &p,
            &foreign.snapshot().unwrap(),
            50,
        )
        .is_err()
    );
    add_decision(&mut writer, "normal-chat");
    let mut corrupt = writer.snapshot().unwrap();
    corrupt.records.last_mut().unwrap().chain_digest = digest("foreign-tail");
    assert!(
        verify_dataset_window_snapshot_against_current_ledger_v3(&receipt, &p, &corrupt, 50,)
            .is_err()
    );
    assert!(
        verify_dataset_window_snapshot_against_current_ledger_v3(
            &receipt,
            &p,
            &writer.snapshot().unwrap(),
            receipt.receipt.producer.expires_at + 1,
        )
        .is_err()
    );
}

#[test]
fn original_observed_h2_is_exact_prefix_of_h3_while_h1_window_remains_frozen() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    add_outcome(&mut writer, "a", "1", None, 100);
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    let h1 = writer.snapshot().unwrap();
    add_decision(&mut writer, "normal-chat");
    add_outcome(&mut writer, "normal-chat", "1", None, 100);
    let h2 = writer.snapshot().unwrap();
    add_credit(&mut writer, "normal-chat", "1", 100);
    let h3 = writer.snapshot().unwrap();
    let before = (
        fs::read(fixture.root.join("ledger")).unwrap(),
        fs::read(fixture.root.join("witness")).unwrap(),
        writer.witness_frontier().unwrap(),
    );
    assert_ne!(h1.head_digest, h2.head_digest);
    assert_ne!(h2.head_digest, h3.head_digest);
    assert_eq!(
        authenticate_ledger_snapshot_prefix_v3(&h3, h2.head_digest, h2.records().len() as u64)
            .unwrap(),
        h2
    );
    assert_eq!(
        verify_dataset_window_snapshot_against_current_ledger_v3(&receipt, &p, &h3, 50).unwrap(),
        h1
    );
    assert_eq!(
        before,
        (
            fs::read(fixture.root.join("ledger")).unwrap(),
            fs::read(fixture.root.join("witness")).unwrap(),
            writer.witness_frontier().unwrap(),
        )
    );
}

#[test]
fn prefix_rejects_foreign_head_wrong_count_and_corruption_anywhere_in_current_history() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    add_decision(&mut writer, "a");
    add_outcome(&mut writer, "a", "1", None, 100);
    let observed = writer.snapshot().unwrap();
    add_decision(&mut writer, "tail");
    let current = writer.snapshot().unwrap();
    let count = observed.records().len() as u64;
    assert!(authenticate_ledger_snapshot_prefix_v3(&current, digest("foreign"), count).is_err());
    assert!(
        authenticate_ledger_snapshot_prefix_v3(&current, observed.head_digest, count + 1).is_err()
    );
    assert!(
        authenticate_ledger_snapshot_prefix_v3(&current, observed.head_digest, u64::MAX).is_err()
    );
    for index in [0, current.records().len() - 1] {
        let mut corrupt = current.clone();
        corrupt.records[index].chain_digest = digest("corrupt");
        assert!(
            authenticate_ledger_snapshot_prefix_v3(&corrupt, observed.head_digest, count).is_err()
        );
    }
    let mut corrupt = current;
    corrupt.head_digest = digest("corrupt-outer-head");
    assert!(authenticate_ledger_snapshot_prefix_v3(&corrupt, observed.head_digest, count).is_err());
}

#[test]
fn empty_prefix_requires_exact_original_zero_head_and_valid_complete_current_source() {
    let empty = LearningLedger::new().snapshot();
    assert_eq!(
        authenticate_ledger_snapshot_prefix_v3(&empty, Digest32::ZERO, 0).unwrap(),
        empty
    );
    assert!(authenticate_ledger_snapshot_prefix_v3(&empty, digest("foreign-empty"), 0).is_err());
    assert!(authenticate_ledger_snapshot_prefix_v3(&empty, Digest32::ZERO, 1).is_err());
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    add_decision(&mut writer, "a");
    let current = writer.snapshot().unwrap();
    assert_eq!(
        authenticate_ledger_snapshot_prefix_v3(&current, Digest32::ZERO, 0).unwrap(),
        empty
    );
    assert!(authenticate_ledger_snapshot_prefix_v3(&current, Digest32::ZERO, 1).is_err());
    let mut invalid_empty = empty;
    invalid_empty.head_digest = digest("corrupt-empty");
    assert!(authenticate_ledger_snapshot_prefix_v3(&invalid_empty, Digest32::ZERO, 0).is_err());
}
