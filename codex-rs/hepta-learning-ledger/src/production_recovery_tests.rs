use super::*;
use crate::LearningAppendIdentityV1;

fn reopen(fixture: &Fixture) -> LedgerWriter {
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Unacknowledged,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    LedgerWriter::from_durable(
        ledger,
        witness,
        activated_trust(),
        &fixture.directory(),
        &fixture.directory(),
    )
    .unwrap()
}

#[test]
fn append_ack_loss_child() {
    let Some(root) = std::env::var_os("HEPTA_APPEND_RECOVERY_CHILD") else {
        return;
    };
    let fixture = Fixture {
        root: PathBuf::from(root),
    };
    let mut writer = fixture.writer();
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let identity =
        writer.authenticated_append_identity(&request.record_id, Digest32::ZERO, &evidence);
    // This is the existing caller's durable intent, not a second event journal.
    fs::write(
        fixture.root.join("append-identity"),
        identity.encode().unwrap(),
    )
    .unwrap();
    File::open(fixture.root.join("append-identity"))
        .unwrap()
        .sync_all()
        .unwrap();
    fixture.directory().sync_all().unwrap();
    writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap();
    // Exit without returning the append receipt or running destructors. Parent
    // has neither request bytes nor any prepared model state.
    std::process::exit(0);
}

#[test]
fn signed_append_recovers_after_process_exit_without_original_request() {
    let fixture = Fixture::new();
    let status = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "production::tests::recovery_tests::append_ack_loss_child",
            "--nocapture",
        ])
        .env("HEPTA_APPEND_RECOVERY_CHILD", &fixture.root)
        .status()
        .unwrap();
    assert!(status.success());
    let identity =
        LearningAppendIdentityV1::decode(&fs::read(fixture.root.join("append-identity")).unwrap())
            .unwrap();
    let mut writer = reopen(&fixture);
    let before = writer.snapshot().unwrap();
    let recovered = writer
        .recover_authenticated_append(&identity)
        .unwrap()
        .unwrap();
    assert_eq!(recovered.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(recovered.chain_digest, before.head_digest);
    assert_eq!(writer.snapshot().unwrap(), before);
    drop(writer);
    let mut writer = reopen(&fixture);
    assert_eq!(
        writer.recover_authenticated_append(&identity).unwrap(),
        Some(recovered)
    );
    assert_eq!(writer.snapshot().unwrap(), before);
}

#[test]
fn identity_changes_never_adopt_another_commit_or_advance_witness() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let identity =
        writer.authenticated_append_identity(&request.record_id, Digest32::ZERO, &evidence);
    assert_eq!(
        writer.recover_authenticated_append(&identity).unwrap(),
        None
    );
    writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap();
    let before = writer.snapshot().unwrap();
    let frontier = writer.witness_frontier().unwrap();
    for field in [
        "ledger_binding",
        "expected_predecessor",
        "authentication_digest",
    ] {
        let mut wire: serde_json::Value =
            serde_json::from_slice(&identity.encode().unwrap()).unwrap();
        wire[field] = digest(field).to_string().into();
        let altered =
            LearningAppendIdentityV1::decode(&serde_json::to_vec(&wire).unwrap()).unwrap();
        assert!(
            writer.recover_authenticated_append(&altered).is_err(),
            "{field}"
        );
        assert_eq!(writer.snapshot().unwrap(), before);
        assert_eq!(writer.witness_frontier().unwrap(), frontier);
    }
    let mut wire: serde_json::Value = serde_json::from_slice(&identity.encode().unwrap()).unwrap();
    wire["record_id"] = "missing-record".into();
    let absent = LearningAppendIdentityV1::decode(&serde_json::to_vec(&wire).unwrap()).unwrap();
    assert_eq!(writer.recover_authenticated_append(&absent).unwrap(), None);
    assert_eq!(writer.snapshot().unwrap(), before);
}

#[test]
fn expired_signature_does_not_prevent_history_lookup_or_authorize_new_append() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let request = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let identity =
        writer.authenticated_append_identity(&request.record_id, Digest32::ZERO, &evidence);
    writer
        .append_decision(Digest32::ZERO, request.clone(), &evidence, 50)
        .unwrap();
    assert!(
        writer
            .append_decision(Digest32::ZERO, request, &evidence, 500)
            .is_err()
    );
    assert!(
        writer
            .recover_authenticated_append(&identity)
            .unwrap()
            .is_some()
    );
    assert_eq!(writer.snapshot().unwrap().records().len(), 1);
}

#[test]
fn lookup_identity_rejects_unknown_fields_versions_and_oversized_bytes() {
    let fixture = Fixture::new();
    let writer = fixture.writer();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&decision()).unwrap(),
    );
    let identity =
        writer.authenticated_append_identity(&decision().record_id, Digest32::ZERO, &evidence);
    let bytes = identity.encode().unwrap();
    assert_eq!(LearningAppendIdentityV1::decode(&bytes).unwrap(), identity);
    let mut wire: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    wire["schema"] = "unknown-v2".into();
    assert!(LearningAppendIdentityV1::decode(&serde_json::to_vec(&wire).unwrap()).is_err());
    let mut wire: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    wire["allow_replay"] = true.into();
    assert!(LearningAppendIdentityV1::decode(&serde_json::to_vec(&wire).unwrap()).is_err());
    assert!(LearningAppendIdentityV1::decode(&vec![b' '; 1025]).is_err());
}

#[test]
fn late_witness_recovers_by_persisted_identity_without_signed_replay() {
    let fixture = Fixture::new();
    let trust = activated_trust();
    let request = decision();
    let payload = decision_signing_payload_v2(&request).unwrap();
    let evidence = sign(
        trust.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    let verified = trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Generator, &evidence, &payload, 50)
        .unwrap();
    let principal = verified.principal().clone();
    let event = LedgerEvent::AuthenticatedDecisionV2(AuthenticatedDecisionRecordV2 {
        record_id: request.record_id.clone(),
        episode_id: request.episode_id.clone(),
        run_snapshot_digest: request.run_snapshot_digest,
        objective_digest: request.objective_digest,
        policy_digest: request.policy_digest,
        generator_id: principal.principal_id.clone(),
        generator_controller_id: verified.controller_id().clone(),
        generator_credential_chain_digest: principal.credential_chain_digest,
        generator_signing_key_digest: principal.signing_key_digest,
        generator_scope_digest: principal.scope_digest,
        generator_authority_epoch: principal.authority_epoch,
        candidate_ids: request.candidate_ids.clone(),
        selected_candidate_id: request.selected_candidate_id.clone(),
        selected_propensity: request.selected_propensity,
        candidate_completeness_digest: validate_production_completeness(&request).unwrap(),
        support_digest: request.support_digest,
        authentication_digest: signed_evidence_digest(&evidence),
    });

    let mut raw = DurableLedger::create(fixture.file("ledger"), binding(), 64).unwrap();
    let committed = raw.append(Digest32::ZERO, event).unwrap();
    drop(raw);
    drop(LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap());

    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Unacknowledged,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let ledger_directory = fixture.directory();
    let witness_directory = fixture.directory();
    let mut writer = LedgerWriter::from_durable(
        ledger,
        witness,
        trust,
        &ledger_directory,
        &witness_directory,
    )
    .unwrap();
    assert_eq!(writer.witness_frontier().unwrap().anchor.sequence, 0);

    let identity =
        writer.authenticated_append_identity(&request.record_id, Digest32::ZERO, &evidence);
    let identity = LearningAppendIdentityV1::decode(&identity.encode().unwrap()).unwrap();
    let original = writer.snapshot().unwrap();
    let mut wrong: serde_json::Value = serde_json::from_slice(&identity.encode().unwrap()).unwrap();
    wrong["expected_predecessor"] = digest("different predecessor").to_string().into();
    let wrong = LearningAppendIdentityV1::decode(&serde_json::to_vec(&wrong).unwrap()).unwrap();
    assert!(writer.recover_authenticated_append(&wrong).is_err());
    assert_eq!(writer.witness_frontier().unwrap().anchor.sequence, 0);
    let reconciled = writer
        .recover_authenticated_append(&identity)
        .unwrap()
        .unwrap();
    assert_eq!(writer.snapshot().unwrap(), original);
    assert_eq!(reconciled.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(reconciled.chain_digest, committed.chain_digest);
    let frontier = writer.witness_frontier().unwrap();
    assert_eq!(frontier.anchor.sequence, 1);
    assert_eq!(frontier.anchor.chain_digest, committed.chain_digest);
}

#[test]
fn outcome_recovery_after_withdrawal_keeps_training_data_ineligible() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
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
    let observed = outcome("recovery-outcome", "recovery-outcome-value", None, 100);
    let signed = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    let identity = writer.authenticated_append_identity(&observed.record_id, head, &signed);
    let receipt = writer.append_outcome(head, observed, &signed, 50).unwrap();
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("recovery-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion"),
    };
    let evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &writer.dataset_freeze_signing_payload(&plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &evidence, 50).unwrap();
    let withdrawal = UnlearningLineageRequestV1 {
        record_id: id("recovery-withdrawal"),
        lineage_id: id("recovery-lineage"),
        source_record_id: id("recovery-outcome"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("recovery-artifact"),
        reason_digest: digest("withdrawal"),
    };
    let signed = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&withdrawal),
    );
    writer
        .append_unlearning(receipt.chain_digest, withdrawal, &dataset, &signed, 50)
        .unwrap();
    let before = writer.snapshot().unwrap();
    let frontier = writer.witness_frontier().unwrap();
    let identity = LearningAppendIdentityV1::decode(&identity.encode().unwrap()).unwrap();
    drop(writer);
    let mut writer = reopen(&fixture);
    let recovered = writer
        .recover_authenticated_append(&identity)
        .unwrap()
        .unwrap();
    assert_eq!(recovered.chain_digest, receipt.chain_digest);
    assert_eq!(recovered.event_digest, receipt.event_digest);
    assert!(writer.revalidate_dataset_snapshot(&dataset, 50).is_err());
    assert_eq!(writer.snapshot().unwrap(), before);
    assert_eq!(writer.witness_frontier().unwrap(), frontier);
}
