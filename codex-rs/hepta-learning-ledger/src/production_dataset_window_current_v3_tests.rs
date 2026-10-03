use super::*;
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
