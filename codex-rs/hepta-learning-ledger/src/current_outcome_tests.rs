use super::*;
use std::sync::Arc;

use pretty_assertions::assert_eq;

struct TestClock(AtomicU64);

impl CurrentOutcomeHostClockV1 for TestClock {
    fn now_unix_seconds(&self) -> Result<u64, ProductionLedgerError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

fn current_writer(fixture: &Fixture) -> (LedgerWriter, Arc<TestClock>) {
    let mut writer = fixture.writer();
    let clock = Arc::new(TestClock(AtomicU64::new(50)));
    writer.configure_current_outcome_clock(clock.clone());
    (writer, clock)
}

fn append_decision(writer: &mut LedgerWriter) -> AppendReceipt {
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap()
}

fn append_observed(writer: &mut LedgerWriter, request: AuthenticatedOutcomeV1) -> AppendReceipt {
    let evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&request),
    );
    writer
        .append_outcome(
            writer.witness_frontier().unwrap().anchor.chain_digest,
            request,
            &evidence,
            50,
        )
        .unwrap()
}

fn resolve<'owner>(
    writer: &'owner LedgerWriter,
    record: &str,
) -> Result<CurrentAuthenticatedOutcomeV1<'owner>, ProductionLedgerError> {
    writer.resolve_current_outcome(&id(record), &id("episode"), digest("outcome-support"))
}

fn withdraw(writer: &mut LedgerWriter, record: &str) {
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("current-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &evidence, 50).unwrap();
    let request = UnlearningLineageRequestV1 {
        record_id: id("withdrawal"),
        lineage_id: id("withdrawal-lineage"),
        source_record_id: id(record),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("artifact"),
        reason_digest: digest("withdrawn"),
    };
    let evidence = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&request),
    );
    writer
        .append_unlearning(
            writer.witness_frontier().unwrap().anchor.chain_digest,
            request,
            &dataset,
            &evidence,
            50,
        )
        .unwrap();
}

fn rotate(writer: &mut LedgerWriter, trust: LearningEvidenceTrustV1) {
    let key = trust_root_key();
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("next-distribution"),
            generation: 2,
            effective_at: 50,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 50,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    writer.rotate_trust(&root, signed, 50).unwrap();
}

#[test]
fn current_outcome_comes_from_durable_owner_and_survives_exact_reopen() {
    let fixture = Fixture::new();
    let (mut writer, clock) = current_writer(&fixture);
    append_decision(&mut writer);
    append_observed(&mut writer, outcome("observed", "outcome", None, 1));
    let token = resolve(&writer, "observed").unwrap();
    let before = (
        token.outcome().clone(),
        token.decision().clone(),
        token.outcome_event_digest(),
        token.decision_event_digest(),
        token.witness_frontier(),
        token.ledger_binding(),
    );
    // The non-clone owner borrow can cross threads. A SQLite future borrowing it
    // can be Send; host code must also retain a Send owner lock across await.
    std::thread::scope(|scope| scope.spawn(move || token.ensure_current()).join().unwrap())
        .unwrap();
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
    let mut reopened =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    reopened.configure_current_outcome_clock(clock);
    let token = resolve(&reopened, "observed").unwrap();
    assert_eq!(
        before,
        (
            token.outcome().clone(),
            token.decision().clone(),
            token.outcome_event_digest(),
            token.decision_event_digest(),
            token.witness_frontier(),
            token.ledger_binding(),
        )
    );
    assert!(
        reopened
            .resolve_current_outcome(
                &id("observed"),
                &id("wrong-episode"),
                digest("outcome-support")
            )
            .is_err()
    );
    assert!(
        reopened
            .resolve_current_outcome(&id("observed"), &id("episode"), digest("different-support"))
            .is_err()
    );
    assert!(resolve(&reopened, "decision-record").is_err());
}

#[test]
fn current_outcome_rejects_corrected_and_unlearned_sources() {
    for withdrawn in ["corrected", "decision-record"] {
        let fixture = Fixture::new();
        let (mut writer, _) = current_writer(&fixture);
        append_decision(&mut writer);
        append_observed(&mut writer, outcome("observed", "outcome", None, 1));
        resolve(&writer, "observed")
            .unwrap()
            .ensure_current()
            .unwrap();
        append_observed(
            &mut writer,
            outcome("corrected", "outcome-2", Some("outcome"), 2),
        );
        assert!(resolve(&writer, "observed").is_err());
        resolve(&writer, "corrected")
            .unwrap()
            .ensure_current()
            .unwrap();
        withdraw(&mut writer, withdrawn);
        assert!(resolve(&writer, "corrected").is_err());
    }
}

#[test]
fn current_outcome_rechecks_installed_actor_roles_credentials_and_controllers() {
    for change in 0..6 {
        let fixture = Fixture::new();
        let (mut writer, _) = current_writer(&fixture);
        append_decision(&mut writer);
        append_observed(&mut writer, outcome("observed", "outcome", None, 1));
        resolve(&writer, "observed")
            .unwrap()
            .ensure_current()
            .unwrap();
        let mut next = trust();
        let observer = &mut next.signers[1];
        match change {
            0 => observer.revoked_at = Some(50),
            1 => observer.controller_id = id("changed-controller"),
            2 => observer.principal.credential_chain_digest = digest("changed-credential"),
            3 => observer.roles = vec![LearningEvidenceRoleV1::Generator],
            4 => {
                observer.verifying_key =
                    SigningKey::from_bytes(&[8; 32]).verifying_key().to_bytes();
                observer.principal.signing_key_digest = Digest32::of_bytes(&observer.verifying_key);
            }
            5 => {
                next.signers.remove(1);
            }
            _ => unreachable!(),
        }
        rotate(&mut writer, next);
        assert!(resolve(&writer, "observed").is_err(), "change {change}");
    }
}

#[test]
fn owner_clock_rechecks_expiry_and_rejects_time_regression() {
    let fixture = Fixture::new();
    let (mut writer, clock) = current_writer(&fixture);
    append_decision(&mut writer);
    append_observed(&mut writer, outcome("observed", "outcome", None, 1));
    let token = resolve(&writer, "observed").unwrap();
    assert_eq!(token.valid_until_unix_seconds(), 90);
    clock.0.store(90, Ordering::SeqCst);
    token.ensure_current().unwrap();
    clock.0.store(91, Ordering::SeqCst);
    assert!(token.ensure_current().is_err());
    clock.0.store(50, Ordering::SeqCst);
    assert!(matches!(
        token.ensure_current(),
        Err(ProductionLedgerError::Binding("owner clock regressed"))
    ));
}

#[test]
fn unacknowledged_tail_cannot_supply_current_evidence_before_exact_retry() {
    let fixture = Fixture::new();
    let (mut writer, clock) = current_writer(&fixture);
    let decision = append_decision(&mut writer);
    let witnessed_length = fixture.file("witness").metadata().unwrap().len();
    let request = outcome("observed", "outcome", None, 1);
    let evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&request),
    );
    writer
        .append_outcome(decision.chain_digest, request.clone(), &evidence, 50)
        .unwrap();
    drop(writer);
    let witness_file = fixture.file("witness");
    witness_file.set_len(witnessed_length).unwrap();
    witness_file.sync_all().unwrap();
    drop(witness_file);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Unacknowledged,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let mut recovered =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    recovered.configure_current_outcome_clock(clock);
    assert!(matches!(
        resolve(&recovered, "observed"),
        Err(ProductionLedgerError::WitnessLag)
    ));
    let receipt = recovered
        .append_outcome(decision.chain_digest, request, &evidence, 50)
        .unwrap();
    assert_eq!(receipt.disposition, AppendDisposition::IdempotentReplay);
    resolve(&recovered, "observed")
        .unwrap()
        .ensure_current()
        .unwrap();
}
