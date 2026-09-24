//! The borrowed owner path and the untrusted snapshot adapter must retain the
//! same signed bytes, causal cuts and receipts across correction and recovery.
use super::*;

fn append_episode(writer: &mut LedgerWriter) -> Digest32 {
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let head = writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap()
        .chain_digest;
    let observed = outcome("freeze-outcome-1", "freeze-value-1", None, 100);
    let signed = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    writer
        .append_outcome(head, observed, &signed, 50)
        .unwrap()
        .chain_digest
}

fn plan() -> DatasetFreezePlanV2 {
    DatasetFreezePlanV2 {
        snapshot_id: id("borrowed-freeze"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    }
}

fn assert_replay_parity(writer: &LedgerWriter) -> SignedLearningEvidenceV1 {
    let before = writer.snapshot().unwrap();
    let frontier = writer.witness_frontier().unwrap();
    let payload = writer.dataset_freeze_signing_payload(&plan()).unwrap();
    assert_eq!(
        payload,
        dataset_freeze_signing_payload_v2(&before, &plan()).unwrap()
    );
    let evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    let principal = writer
        .verifier()
        .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, 50)
        .unwrap()
        .principal()
        .clone();
    let expected = freeze_dataset_from_ledger(&before, plan(), principal, 50).unwrap();
    let actual = writer.freeze_dataset(plan(), &evidence, 50).unwrap();
    assert_eq!(actual, expected);
    assert_eq!(writer.snapshot().unwrap(), before);
    assert_eq!(writer.witness_frontier().unwrap(), frontier);
    evidence
}

#[test]
fn borrowed_freeze_preserves_correction_cuts_signed_bytes_and_reopen() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_episode(&mut writer);
    let old_evidence = assert_replay_parity(&writer);
    let correction = outcome(
        "freeze-outcome-2",
        "freeze-value-2",
        Some("freeze-value-1"),
        120,
    );
    let signed = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&correction),
    );
    writer
        .append_outcome(head, correction, &signed, 50)
        .unwrap();
    assert!(writer.freeze_dataset(plan(), &old_evidence, 50).is_err());
    let new_evidence = assert_replay_parity(&writer);
    let expected = writer.freeze_dataset(plan(), &new_evidence, 50).unwrap();
    assert_eq!(expected.snapshot.source_record_digests.len(), 2);
    let frontier = writer.witness_frontier().unwrap();
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(frontier.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let recovered =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    assert_replay_parity(&recovered);
    assert_eq!(
        recovered.freeze_dataset(plan(), &new_evidence, 50).unwrap(),
        expected
    );
}

#[test]
fn borrowed_freeze_rejects_wrong_role_wrong_plan_and_forged_snapshot() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    append_episode(&mut writer);
    let payload = writer.dataset_freeze_signing_payload(&plan()).unwrap();
    let wrong_role = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    assert!(writer.freeze_dataset(plan(), &wrong_role, 50).is_err());
    let signed = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    let mut substituted = plan();
    substituted.inclusion_policy_digest = digest("substituted-policy");
    assert!(writer.freeze_dataset(substituted, &signed, 50).is_err());
    let mut forged = writer.snapshot().unwrap();
    forged.head_digest = digest("forged-head");
    assert!(dataset_freeze_signing_payload_v2(&forged, &plan()).is_err());
    assert_replay_parity(&writer);
}

#[test]
fn borrowed_freeze_never_reintroduces_unlearned_source() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let head = append_episode(&mut writer);
    let evidence = assert_replay_parity(&writer);
    let dataset = writer.freeze_dataset(plan(), &evidence, 50).unwrap();
    let withdrawal = UnlearningLineageRequestV1 {
        record_id: id("freeze-withdrawal"),
        lineage_id: id("freeze-lineage"),
        source_record_id: id("freeze-outcome-1"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("artifact-a"),
        reason_digest: digest("withdrawal"),
    };
    let signed = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&withdrawal),
    );
    writer
        .append_unlearning(head, withdrawal, &dataset, &signed, 50)
        .unwrap();
    assert!(writer.revalidate_dataset_snapshot(&dataset, 50).is_err());
    assert!(writer.freeze_dataset(plan(), &evidence, 50).is_err());
    // With the only outcome removed, neither adapter may fabricate a watermark.
    assert!(matches!(
        writer.dataset_freeze_signing_payload(&plan()),
        Err(ProductionLedgerError::OutcomeWatermarkRequired)
    ));
    assert!(matches!(
        dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan()),
        Err(ProductionLedgerError::OutcomeWatermarkRequired)
    ));
}
