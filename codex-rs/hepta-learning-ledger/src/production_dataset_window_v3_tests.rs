use super::*;
use crate::DatasetWindowFreezePlanV3;
use crate::DatasetWindowSnapshotWireV3;
use crate::dataset_window_freeze_signing_payload_v3;
use crate::freeze_dataset_window_from_ledger_v3;
use crate::verify_dataset_window_snapshot_against_ledger_v3;

fn add_decision(writer: &mut LedgerWriter, name: &str) -> AppendReceipt {
    let mut request = decision();
    request.record_id = id(&format!("decision-{name}"));
    request.episode_id = id(&format!("episode-{name}"));
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    writer
        .append_decision(
            writer.snapshot().unwrap().head_digest,
            request,
            &evidence,
            50,
        )
        .unwrap()
}
fn add_outcome(
    writer: &mut LedgerWriter,
    name: &str,
    suffix: &str,
    predecessor: Option<&str>,
    value: i64,
) -> AppendReceipt {
    let mut request = outcome(
        &format!("outcome-record-{name}-{suffix}"),
        &format!("outcome-{name}-{suffix}"),
        predecessor,
        value,
    );
    request.episode_id = id(&format!("episode-{name}"));
    let evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&request),
    );
    writer
        .append_outcome(
            writer.snapshot().unwrap().head_digest,
            request,
            &evidence,
            50,
        )
        .unwrap()
}
fn add_credit(writer: &mut LedgerWriter, name: &str, suffix: &str, value: i64) -> AppendReceipt {
    let mut request = credit_batch();
    request.batch_id = id(&format!("credit-{name}-{suffix}"));
    request.episode_id = id(&format!("episode-{name}"));
    request.outcome_id = id(&format!("outcome-{name}-{suffix}"));
    request.terminal_outcome = FixedQ32::from_raw(value);
    request.allocations = vec![CreditAllocationV1 {
        target_id: id("artifact-a"),
        credit: FixedQ32::from_raw(value),
    }];
    request.conservation_residual = FixedQ32::ZERO;
    let batch = finalize_credit_batch(request.clone(), 50).unwrap();
    let evidence = sign(
        writer.verifier(),
        "allocator",
        LearningEvidenceRoleV1::CreditAllocator,
        &credit_batch_signing_payload_v2(&request, batch.batch_digest),
    );
    writer
        .append_credit_batch(
            writer.snapshot().unwrap().head_digest,
            request,
            &evidence,
            50,
        )
        .unwrap()
}
fn plan(start: u64, end: u64) -> DatasetWindowFreezePlanV3 {
    DatasetWindowFreezePlanV3 {
        snapshot_id: id("window-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("original-root-inclusion-policy"),
        decision_sequence_start: start,
        decision_sequence_end: end,
        maximum_episodes: 64,
        maximum_source_records: 256,
        maximum_encoded_bytes: 65_536,
    }
}
fn freeze(
    writer: &LedgerWriter,
    plan: DatasetWindowFreezePlanV3,
) -> crate::DatasetWindowSnapshotReceiptV3 {
    let payload =
        dataset_window_freeze_signing_payload_v3(&writer.snapshot().unwrap(), &plan).unwrap();
    let evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    writer
        .freeze_dataset_window_v3(plan, &evidence, 50)
        .unwrap()
}

#[test]
fn window_keeps_late_corrected_outcome_credit_and_whole_cuts_without_writes() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    let b = add_decision(&mut writer, "b");
    let retired = add_outcome(&mut writer, "a", "1", None, 100);
    let retired_credit = add_credit(&mut writer, "a", "1", 100);
    add_outcome(&mut writer, "b", "1", None, 100);
    let corrected = add_outcome(&mut writer, "a", "2", Some("outcome-a-1"), 120);
    let credit = add_credit(&mut writer, "a", "2", 120);
    let before = (
        fs::read(fixture.root.join("ledger")).unwrap(),
        fs::read(fixture.root.join("witness")).unwrap(),
    );
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    assert_eq!(receipt.receipt.snapshot.source_record_digests.len(), 3);
    for digest in [a.event_digest, corrected.event_digest, credit.event_digest] {
        assert!(
            receipt
                .receipt
                .snapshot
                .source_record_digests
                .contains(&digest)
        );
    }
    for digest in [
        retired.event_digest,
        retired_credit.event_digest,
        b.event_digest,
    ] {
        assert!(
            !receipt
                .receipt
                .snapshot
                .source_record_digests
                .contains(&digest)
        );
    }
    assert!(corrected.sequence.get() > p.decision_sequence_end);
    assert!(credit.sequence.get() > p.decision_sequence_end);
    assert_eq!(
        receipt.receipt.snapshot.eligible_frontier,
        credit.sequence.get()
    );
    assert_eq!(receipt.receipt.snapshot.pending_outcomes, 0);
    writer
        .revalidate_dataset_window_v3(&receipt, &p, 50)
        .unwrap();
    let b_receipt = freeze(&writer, plan(b.sequence.get(), b.sequence.get()));
    assert_eq!(b_receipt.receipt.snapshot.source_record_digests.len(), 2);
    assert_ne!(
        receipt.receipt.correction_cut_digest,
        b_receipt.receipt.correction_cut_digest
    );
    assert_eq!(
        receipt.receipt.revocation_cut_digest,
        b_receipt.receipt.revocation_cut_digest
    );
    assert_eq!(
        receipt.receipt.snapshot.ledger_head_digest,
        b_receipt.receipt.snapshot.ledger_head_digest
    );
    assert!(
        verify_dataset_window_snapshot_against_ledger_v3(
            &receipt,
            &plan(2, 2),
            &writer.snapshot().unwrap(),
            50
        )
        .is_err()
    );
    let encoded = serde_json::to_vec(&DatasetWindowSnapshotWireV3::from_native(&receipt)).unwrap();
    let wire: DatasetWindowSnapshotWireV3 = serde_json::from_slice(&encoded).unwrap();
    assert_eq!(wire.native().unwrap(), receipt);
    assert_eq!(
        before,
        (
            fs::read(fixture.root.join("ledger")).unwrap(),
            fs::read(fixture.root.join("witness")).unwrap()
        )
    );
}

#[test]
fn window_signatures_bind_all_policy_fields_and_do_not_accept_old_v2_purpose() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    add_outcome(&mut writer, "a", "1", None, 100);
    let p = plan(a.sequence.get(), a.sequence.get());
    let receipt = freeze(&writer, p.clone());
    let snapshot = writer.snapshot().unwrap();
    let payload = dataset_window_freeze_signing_payload_v3(&snapshot, &p).unwrap();
    let evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    let old = DatasetFreezePlanV2 {
        snapshot_id: p.snapshot_id.clone(),
        objective_digest: p.objective_digest,
        inclusion_policy_digest: p.inclusion_policy_digest,
    };
    let old_payload = dataset_freeze_signing_payload_v2(&snapshot, &old).unwrap();
    assert_ne!(payload, old_payload);
    let old_evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &old_payload,
    );
    assert!(
        writer
            .freeze_dataset_window_v3(p.clone(), &old_evidence, 50)
            .is_err()
    );
    assert!(writer.freeze_dataset(old, &evidence, 50).is_err());
    for field in 0..8 {
        let mut changed = p.clone();
        match field {
            0 => changed.snapshot_id = id("other-snapshot"),
            1 => changed.objective_digest = digest("other-objective"),
            2 => changed.inclusion_policy_digest = digest("other-policy"),
            3 => changed.decision_sequence_start += 1,
            4 => changed.decision_sequence_end += 1,
            5 => changed.maximum_episodes += 1,
            6 => changed.maximum_source_records += 1,
            7 => changed.maximum_encoded_bytes -= 1,
            _ => unreachable!(),
        }
        assert!(
            writer
                .freeze_dataset_window_v3(changed.clone(), &evidence, 50)
                .is_err(),
            "field{field}"
        );
        assert!(
            verify_dataset_window_snapshot_against_ledger_v3(&receipt, &changed, &snapshot, 50)
                .is_err(),
            "field{field}"
        );
    }
    let wrong_role = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    assert!(
        writer
            .freeze_dataset_window_v3(p.clone(), &wrong_role, 50)
            .is_err()
    );
    assert!(
        writer
            .freeze_dataset_window_v3(p, &evidence, evidence.expires_at + 1)
            .is_err()
    );
}

#[test]
fn window_over_capacity_and_outside_source_reject_whole_without_skipping_pending_episode() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    add_decision(&mut writer, "a");
    let b = add_decision(&mut writer, "b");
    add_outcome(&mut writer, "a", "1", None, 100);
    let snapshot = writer.snapshot().unwrap();
    let p = plan(1, b.sequence.get());
    let receipt = freeze(&writer, p.clone());
    assert_eq!(receipt.receipt.snapshot.pending_outcomes, 1);
    assert_eq!(receipt.receipt.snapshot.source_record_digests.len(), 3);
    assert_eq!(
        receipt.receipt,
        freeze_dataset_from_ledger(
            &snapshot,
            DatasetFreezePlanV2 {
                snapshot_id: p.snapshot_id.clone(),
                objective_digest: p.objective_digest,
                inclusion_policy_digest: p.inclusion_policy_digest,
            },
            principal("evaluator"),
            50
        )
        .unwrap(),
        "full-window original V2 receipt bytes are unchanged"
    );
    let before = writer.witness_frontier().unwrap();
    for cap in 0..5 {
        let mut bad = p.clone();
        match cap {
            0 => bad.maximum_source_records = 2,
            1 => bad.maximum_episodes = 1,
            2 => bad.maximum_encoded_bytes = 1,
            3 => bad.decision_sequence_start = 0,
            4 => bad.decision_sequence_end = snapshot.records().last().unwrap().sequence.get() + 1,
            _ => unreachable!(),
        }
        assert!(
            freeze_dataset_window_from_ledger_v3(&snapshot, bad, principal("evaluator"), 50)
                .is_err()
        );
    }
    assert_eq!(writer.witness_frontier().unwrap(), before);
    assert_eq!(writer.snapshot().unwrap(), snapshot);
}

#[test]
fn window_obeys_current_revocation_and_unlearning_outside_decision_interval() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let a = add_decision(&mut writer, "a");
    let b = add_decision(&mut writer, "b");
    add_outcome(&mut writer, "a", "1", None, 100);
    add_outcome(&mut writer, "b", "1", None, 100);
    let p = plan(a.sequence.get(), b.sequence.get());
    let original = freeze(&writer, p.clone());
    let request = UnlearningLineageRequestV1 {
        record_id: id("window-unlearning"),
        lineage_id: id("window-lineage"),
        source_record_id: id("outcome-record-a-1"),
        dataset_snapshot_id: original.receipt.snapshot.snapshot_id.clone(),
        dataset_digest: original.receipt.snapshot.dataset_digest,
        artifact_id: id("artifact-a"),
        reason_digest: digest("window-withdrawal"),
    };
    let evidence = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&request),
    );
    writer
        .append_unlearning(
            writer.snapshot().unwrap().head_digest,
            request,
            &original.receipt,
            &evidence,
            50,
        )
        .unwrap();
    assert!(
        writer
            .revalidate_dataset_window_v3(&original, &p, 50)
            .is_err()
    );
    let after = freeze(&writer, p.clone());
    assert_eq!(after.receipt.snapshot.pending_outcomes, 1);
    assert_ne!(
        after.receipt.revocation_cut_digest,
        original.receipt.revocation_cut_digest
    );
    let mut core = LearningLedger::from_snapshot(writer.snapshot().unwrap()).unwrap();
    core.append(crate::LedgerEvent::Revocation(crate::Revocation {
        record_id: id("window-revocation"),
        target_record_id: id("decision-a"),
        authority_id: id("privacy-owner"),
        reason_digest: digest("withdraw-episode"),
    }))
    .unwrap();
    let current = core.snapshot();
    let revoked =
        freeze_dataset_window_from_ledger_v3(&current, p.clone(), principal("evaluator"), 50)
            .unwrap();
    assert_eq!(revoked.receipt.snapshot.pending_outcomes, 0);
    assert_eq!(revoked.receipt.snapshot.source_record_digests.len(), 2);
    assert!(
        freeze_dataset_window_from_ledger_v3(&current, plan(1, 1), principal("evaluator"), 50)
            .is_err()
    );
    assert!(verify_dataset_window_snapshot_against_ledger_v3(&after, &p, &current, 50).is_err());
}

#[test]
fn explicit_window_remains_bounded_when_original_complete_history_exceeds_packet_budget() {
    let fixture = Fixture::new();
    let ledger = DurableLedger::create(fixture.file("ledger"), binding(), 2048).unwrap();
    let witness = LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap();
    let mut writer = LedgerWriter::from_durable(
        ledger,
        witness,
        activated_trust(),
        &fixture.directory(),
        &fixture.directory(),
    )
    .unwrap();
    let mut last = 0;
    for episode in 0..520 {
        let name = format!("long-{episode}");
        last = add_decision(&mut writer, &name).sequence.get();
        add_outcome(&mut writer, &name, "1", None, 100);
    }
    let snapshot = writer.snapshot().unwrap();
    let whole = freeze_dataset_from_ledger(
        &snapshot,
        DatasetFreezePlanV2 {
            snapshot_id: id("all-history"),
            objective_digest: digest("objective"),
            inclusion_policy_digest: digest("original-root-inclusion-policy"),
        },
        principal("evaluator"),
        50,
    )
    .unwrap();
    let whole_bytes = serde_json::to_vec(&crate::ReviewDatasetWireV1::from_native(&whole)).unwrap();
    assert!(
        whole_bytes.len() > 65_536,
        "retained original all-history counterexample: {} bytes",
        whole_bytes.len()
    );
    let mut p = plan(last - 8, last);
    p.maximum_episodes = 5;
    p.maximum_source_records = 10;
    p.maximum_encoded_bytes = 8192;
    let receipt = freeze(&writer, p.clone());
    assert_eq!(receipt.receipt.snapshot.source_record_digests.len(), 10);
    assert_eq!(
        receipt.receipt.snapshot.ledger_head_digest,
        snapshot.head_digest
    );
    assert_eq!(receipt.receipt.snapshot.eligible_frontier, 1040);
    assert!(
        serde_json::to_vec(&DatasetWindowSnapshotWireV3::from_native(&receipt))
            .unwrap()
            .len()
            < 8192
    );
    writer
        .revalidate_dataset_window_v3(&receipt, &p, 50)
        .unwrap();
    assert_eq!(
        writer.snapshot().unwrap(),
        snapshot,
        "whole original history retained"
    );
}
