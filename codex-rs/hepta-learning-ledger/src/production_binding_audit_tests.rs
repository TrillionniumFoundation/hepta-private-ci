use super::*;
use pretty_assertions::assert_eq;

fn populated_writer(fixture: &Fixture) -> LedgerWriter {
    let mut writer = fixture.writer();
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let receipt = writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap();
    let observed = outcome("outcome-record-2", "outcome-2", None, 120);
    let evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    writer
        .append_outcome(receipt.chain_digest, observed, &evidence, 50)
        .unwrap();
    writer
}

fn rotate_objective(writer: &mut LedgerWriter) {
    let root_key = trust_root_key();
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut successor = trust();
    successor.objective_digest = digest("other-objective");
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("successor"),
            generation: 2,
            effective_at: 50,
            trust: successor,
        },
        root_id: root.root_id.clone(),
        issued_at: 50,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    writer.rotate_trust(&root, signed, 50).unwrap();
}

fn sign_current(
    writer: &LedgerWriter,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = sign(writer.verifier(), name, role, payload);
    evidence.objective_digest = writer.verifier().objective_digest();
    evidence.signature = SigningKey::from_bytes(&[seed(name); 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

#[test]
fn credit_admission_rejects_another_objective_after_trust_rotation() {
    let fixture = Fixture::new();
    let mut writer = populated_writer(&fixture);
    rotate_objective(&mut writer);
    let batch = credit_batch();
    let batch_digest = finalize_credit_batch(batch.clone(), 50)
        .unwrap()
        .batch_digest;
    let evidence = sign_current(
        &writer,
        "allocator",
        LearningEvidenceRoleV1::CreditAllocator,
        &credit_batch_signing_payload_v2(&batch, batch_digest),
    );
    let before = writer.snapshot().unwrap();
    let result = writer.append_credit_batch(before.head_digest, batch, &evidence, 50);
    assert!(
        result.is_err(),
        "new objective must not allocate old objective credit"
    );
    assert_eq!(writer.snapshot().unwrap(), before);
}

#[test]
fn dataset_freeze_rejects_another_objective_after_trust_rotation() {
    let fixture = Fixture::new();
    let mut writer = populated_writer(&fixture);
    rotate_objective(&mut writer);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let payload = dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap();
    let evidence = sign_current(
        &writer,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    assert!(
        writer.freeze_dataset(plan, &evidence, 50).is_err(),
        "new objective must not freeze old objective data"
    );
}

#[test]
fn dataset_final_use_rejects_expired_root_distribution() {
    let fixture = Fixture::new();
    let writer = populated_writer(&fixture);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let payload = dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap();
    let evidence = sign_current(
        &writer,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    let receipt = writer.freeze_dataset(plan, &evidence, 50).unwrap();
    assert!(
        writer.revalidate_dataset_snapshot(&receipt, 90).is_err(),
        "live producer alone cannot outlive root distribution"
    );
}

fn writer_with_unwitnessed_outcome(fixture: &Fixture) -> LedgerWriter {
    let source = Fixture::new();
    let writer = populated_writer(&source);
    let records = writer.records().unwrap();
    let mut ledger = DurableLedger::create(fixture.file("ledger"), binding(), 64).unwrap();
    let first = ledger
        .append(Digest32::ZERO, records[0].event.clone())
        .unwrap();
    let mut witness = LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap();
    witness
        .advance(
            LedgerWitnessFrontier::empty(),
            LedgerWitnessFrontier {
                anchor: LedgerAnchor {
                    sequence: 1,
                    chain_digest: first.chain_digest,
                },
                segment: None,
                sealed: false,
            },
        )
        .unwrap();
    // Simulate death after canonical ledger sync, before witness advancement.
    ledger
        .append(first.chain_digest, records[1].event.clone())
        .unwrap();
    drop(ledger);
    drop(witness);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: 1,
            chain_digest: first.chain_digest,
        }),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory).unwrap()
}

#[test]
fn dataset_freeze_waits_for_independent_witness_reconciliation() {
    let fixture = Fixture::new();
    let mut writer = writer_with_unwitnessed_outcome(&fixture);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let payload = dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap();
    let evidence = sign_current(
        &writer,
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &payload,
    );
    assert!(
        writer.freeze_dataset(plan.clone(), &evidence, 50).is_err(),
        "unwitnessed terminal fact must not become a frozen dataset"
    );
    let observed = outcome("outcome-record-2", "outcome-2", None, 120);
    let signed = sign_current(
        &writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    let before = writer.records().unwrap();
    let replay = writer
        .append_outcome(before[0].chain_digest, observed, &signed, 50)
        .unwrap();
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(writer.records().unwrap(), before);
    writer.freeze_dataset(plan, &evidence, 50).unwrap();
}

#[test]
fn dataset_final_use_waits_for_independent_witness_reconciliation() {
    let fixture = Fixture::new();
    let writer = writer_with_unwitnessed_outcome(&fixture);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let receipt = freeze_dataset_from_ledger(
        &writer.snapshot().unwrap(),
        plan,
        principal("evaluator"),
        50,
    )
    .unwrap();
    assert!(
        writer.revalidate_dataset_snapshot(&receipt, 50).is_err(),
        "self-consistent receipt cannot promote an unwitnessed terminal fact"
    );
    assert!(writer.read_dataset_records(&receipt, 50).is_err());
}

#[test]
fn dataset_final_use_binds_actual_prefix_and_keeps_historical_witnessed_data() {
    let fixture = Fixture::new();
    let writer = populated_writer(&fixture);
    let snapshot = writer.snapshot().unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let receipt = freeze_dataset_from_ledger(&snapshot, plan, principal("evaluator"), 50).unwrap();
    for (frontier, head) in [
        (2, digest("invented-head")),
        (1, snapshot.records()[0].chain_digest),
        (3, snapshot.head_digest),
    ] {
        let invalid = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: receipt.snapshot.snapshot_id.clone(),
                producer: receipt.producer.clone(),
                ledger_head_digest: head,
                objective_digest: receipt.snapshot.objective_digest,
                eligible_frontier: frontier,
                outcome_watermark: receipt.snapshot.outcome_watermark,
                correction_cut_digest: receipt.correction_cut_digest,
                revocation_cut_digest: receipt.revocation_cut_digest,
                inclusion_policy_digest: receipt.inclusion_policy_digest,
                source_record_digests: receipt.snapshot.source_record_digests.clone(),
                pending_outcomes: receipt.snapshot.pending_outcomes,
                censored_outcomes: receipt.snapshot.censored_outcomes,
            },
            50,
        )
        .unwrap();
        assert!(writer.revalidate_dataset_snapshot(&invalid, 50).is_err());
    }
    let witnessed = writer.witness_frontier().unwrap();
    drop(writer);
    let mut ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(witnessed.anchor),
    )
    .unwrap();
    let mut later = snapshot.records()[0].event.clone();
    if let LedgerEvent::AuthenticatedDecisionV2(value) = &mut later {
        value.record_id = id("later-record");
        value.episode_id = id("later-episode");
    }
    ledger.append(snapshot.head_digest, later).unwrap();
    drop(ledger);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(witnessed.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let writer =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    writer.revalidate_dataset_snapshot(&receipt, 50).unwrap();
    assert_eq!(writer.read_dataset_records(&receipt, 50).unwrap().len(), 2);
}

#[test]
fn dataset_final_use_rejects_objective_rotation_without_rewriting_receipt() {
    let fixture = Fixture::new();
    let mut writer = populated_writer(&fixture);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let receipt = freeze_dataset_from_ledger(
        &writer.snapshot().unwrap(),
        plan,
        principal("evaluator"),
        50,
    )
    .unwrap();
    writer.revalidate_dataset_snapshot(&receipt, 50).unwrap();
    rotate_objective(&mut writer);
    assert!(writer.revalidate_dataset_snapshot(&receipt, 50).is_err());
    verify_dataset_snapshot_receipt_v3(&receipt, 50).unwrap();
}
