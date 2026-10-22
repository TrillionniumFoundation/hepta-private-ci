use super::*;

fn committed() -> (
    Fixture,
    LedgerWriter,
    DatasetSnapshotReceiptV3,
    UnlearningLineageRequestV1,
    SignedLearningEvidenceV1,
) {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let decision = decision();
    let signed = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision).unwrap(),
    );
    let first = writer
        .append_decision(Digest32::ZERO, decision, &signed, /*now*/ 50)
        .unwrap();
    let outcome = outcome(
        "outcome-record",
        "outcome",
        /*predecessor*/ None,
        /*value*/ 100,
    );
    let signed = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    let last = writer
        .append_outcome(first.chain_digest, outcome, &signed, /*now*/ 50)
        .unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let signed = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &signed, /*now*/ 50).unwrap();
    let request = UnlearningLineageRequestV1 {
        record_id: id("unlearning-record"),
        lineage_id: id("lineage"),
        source_record_id: id("outcome-record"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("artifact"),
        reason_digest: digest("reason"),
    };
    let signed = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&request),
    );
    writer
        .append_unlearning(
            last.chain_digest,
            request.clone(),
            &dataset,
            &signed,
            /*now*/ 50,
        )
        .unwrap();
    (fixture, writer, dataset, request, signed)
}

#[test]
fn confirmed_unlearning_uses_actual_signed_record_and_independent_witness_after_reopen() {
    let (fixture, writer, dataset, request, evidence) = committed();
    let frontier = writer.witness_frontier().unwrap();
    let records = writer.records().unwrap();
    let expected = (
        &request.record_id,
        &request.artifact_id,
        request.dataset_digest,
        records.last().unwrap().event_digest,
        frontier,
    );
    let fact = writer
        .verify_committed_unlearning(&request, &dataset, &evidence, /*now*/ 50)
        .unwrap();
    assert_eq!(
        (
            fact.record_id(),
            fact.artifact_id(),
            fact.dataset_digest(),
            fact.event_digest(),
            fact.frontier()
        ),
        expected
    );
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        /*max_records*/ 64,
        LedgerRecovery::Acknowledged(frontier.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let reopened =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    let fact = reopened
        .verify_committed_unlearning(&request, &dataset, &evidence, /*now*/ 50)
        .unwrap();
    assert_eq!(
        (
            fact.record_id(),
            fact.artifact_id(),
            fact.dataset_digest(),
            fact.event_digest(),
            fact.frontier()
        ),
        expected
    );
}

#[test]
fn confirmed_unlearning_refuses_signed_but_uncommitted_or_changed_event() {
    let (_fixture, writer, dataset, request, evidence) = committed();
    let before = (
        writer.snapshot().unwrap(),
        writer.witness_frontier().unwrap(),
    );
    for (field, value) in [
        ("record", "missing-record"),
        ("artifact", "different-artifact"),
        ("reason", "different-reason"),
    ] {
        let mut changed = request.clone();
        match field {
            "record" => changed.record_id = id(value),
            "artifact" => changed.artifact_id = id(value),
            "reason" => changed.reason_digest = digest(value),
            _ => unreachable!(),
        }
        let signed = sign(
            writer.verifier(),
            "privacy-owner",
            LearningEvidenceRoleV1::UnlearningAuthority,
            &unlearning_signing_payload_v1(&changed),
        );
        assert!(
            writer
                .verify_committed_unlearning(&changed, &dataset, &signed, /*now*/ 50)
                .is_err()
        );
    }
    let mut bad = evidence.clone();
    bad.signature[0] ^= 1;
    assert!(
        writer
            .verify_committed_unlearning(&request, &dataset, &bad, /*now*/ 50)
            .is_err()
    );
    let mut bad_dataset = dataset;
    bad_dataset.snapshot.snapshot_id = id("different-dataset");
    assert!(
        writer
            .verify_committed_unlearning(&request, &bad_dataset, &evidence, /*now*/ 50)
            .is_err()
    );
    assert_eq!(
        (
            writer.snapshot().unwrap(),
            writer.witness_frontier().unwrap()
        ),
        before
    );
}

#[test]
fn confirmed_unlearning_refuses_expired_or_changed_evidence_and_current_trust() {
    let (_fixture, mut writer, dataset, request, evidence) = committed();
    assert!(
        writer
            .verify_committed_unlearning(&request, &dataset, &evidence, /*now*/ 91)
            .is_err()
    );
    let mut changed = evidence.clone();
    changed.evidence_id = id("new-signed-envelope");
    changed.signature = SigningKey::from_bytes(&[5; 32])
        .sign(&changed.signing_bytes())
        .to_bytes();
    assert!(
        writer
            .verify_committed_unlearning(&request, &dataset, &changed, /*now*/ 50)
            .is_err()
    );
    let root_key = trust_root_key();
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut trust = trust();
    trust
        .signers
        .iter_mut()
        .find(|v| v.principal.principal_id == id("privacy-owner"))
        .unwrap()
        .revoked_at = Some(60);
    let mut next = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("successor"),
            generation: 2,
            effective_at: 60,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 60,
        expires_at: 90,
        signature: [0; 64],
    };
    next.signature = root_key.sign(&next.signing_bytes().unwrap()).to_bytes();
    writer.rotate_trust(&root, next, /*now*/ 60).unwrap();
    assert!(
        writer
            .verify_committed_unlearning(&request, &dataset, &evidence, /*now*/ 60)
            .is_err()
    );
}

#[test]
fn confirmed_unlearning_refuses_actual_durable_but_unwitnessed_tail() {
    let (_fixture, mut writer, dataset, request, evidence) = committed();
    let frontier = writer.witness_frontier().unwrap();
    // Fault cut only: the original private backend writes a real synced frame;
    // the independently retained witness deliberately has not acknowledged it.
    writer
        .backend
        .append(
            frontier.anchor.chain_digest,
            LedgerEvent::Revocation(crate::Revocation {
                record_id: id("unwitnessed"),
                target_record_id: id("decision-record"),
                authority_id: id("privacy-owner"),
                reason_digest: digest("fault-cut"),
            }),
        )
        .unwrap();
    assert!(matches!(
        writer.verify_committed_unlearning(&request, &dataset, &evidence, /*now*/ 50),
        Err(ProductionLedgerError::WitnessLag)
    ));
    assert_eq!(writer.witness_frontier().unwrap(), frontier);
}
