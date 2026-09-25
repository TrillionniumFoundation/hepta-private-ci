use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AppendDisposition;
use crate::CreditAllocationV1;
use crate::LearningEvidenceTrustV1;
use crate::LearningTrustDistributionV1;
use crate::LearningTrustRootV1;
use crate::LedgerRecovery;
use crate::OutcomeWatermarkV1;
use crate::SignedLearningTrustDistributionV1;
use crate::TrustedLearningSignerV1;
use crate::activate_learning_trust;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn binding() -> Digest32 {
    digest("production-ledger-binding")
}

fn trusted(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn trust() -> LearningEvidenceTrustV1 {
    LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                "observer",
                "observer-controller",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            trusted(
                "allocator",
                "allocator-controller",
                3,
                LearningEvidenceRoleV1::CreditAllocator,
            ),
            trusted(
                "evaluator",
                "evaluator-controller",
                4,
                LearningEvidenceRoleV1::Evaluator,
            ),
            trusted(
                "privacy-owner",
                "privacy-controller",
                5,
                LearningEvidenceRoleV1::UnlearningAuthority,
            ),
        ],
    }
}

fn principal(name: &str) -> AuthenticatedPrincipalV1 {
    trust()
        .signers
        .into_iter()
        .find(|signer| signer.principal.principal_id == id(name))
        .unwrap()
        .principal
}

fn trust_root_key() -> SigningKey {
    SigningKey::from_bytes(&[99; 32])
}

fn activated_trust() -> ActivatedLearningTrustV1 {
    let root_key = trust_root_key();
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-distribution"),
            generation: 1,
            effective_at: 20,
            trust: trust(),
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, None, 50).unwrap()
}

fn seed(name: &str) -> u8 {
    match name {
        "generator" => 1,
        "observer" => 2,
        "allocator" => 3,
        "evaluator" => 4,
        "privacy-owner" => 5,
        _ => panic!("unknown signer"),
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{name}")),
        principal_id: id(name),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed(name); 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-production-ledger-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        File::create(root.join("ledger")).unwrap();
        File::create(root.join("witness")).unwrap();
        Self { root }
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .unwrap()
    }

    fn directory(&self) -> File {
        File::open(&self.root).unwrap()
    }

    fn writer(&self) -> LedgerWriter {
        let ledger = DurableLedger::create(self.file("ledger"), binding(), 64).unwrap();
        let witness = LedgerWitnessStore::create(self.file("witness"), binding()).unwrap();
        let trust = activated_trust();
        let ledger_directory = self.directory();
        let witness_directory = self.directory();
        LedgerWriter::from_durable(
            ledger,
            witness,
            trust,
            &ledger_directory,
            &witness_directory,
        )
        .unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn decision() -> ProductionDecisionV2 {
    let candidates = vec![id("action"), id("abstain")];
    ProductionDecisionV2 {
        record_id: id("decision-record"),
        episode_id: id("episode"),
        run_snapshot_digest: digest("run-snapshot"),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("candidate-set"),
            state_digest: digest("state"),
            generator_id: id("generator"),
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: digest("decision-support"),
    }
}

fn outcome(
    record: &str,
    outcome: &str,
    predecessor: Option<&str>,
    value: i64,
) -> AuthenticatedOutcomeV1 {
    AuthenticatedOutcomeV1 {
        record_id: id(record),
        outcome_id: id(outcome),
        episode_id: id("episode"),
        observer: principal("observer"),
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(value)),
        unit_profile_digest: digest("reward-units"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: predecessor.map(id),
            finalized_at: Some(46),
        },
    }
}

fn credit_batch() -> CreditAllocationBatchV1 {
    CreditAllocationBatchV1 {
        batch_id: id("credit-batch"),
        episode_id: id("episode"),
        outcome_id: id("outcome-2"),
        allocator: principal("allocator"),
        terminal_outcome: FixedQ32::from_raw(120),
        allocations: vec![
            CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
            CreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: FixedQ32::from_raw(50),
            },
        ],
        conservation_residual: FixedQ32::from_raw(10),
        support_digest: digest("credit-support"),
        finalized: true,
    }
}

#[test]
fn production_writer_closes_authenticated_causal_chain_and_witnesses_each_commit() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let request = decision();
    let decision_payload = decision_signing_payload_v2(&request).unwrap();
    let decision_evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_payload,
    );
    let decision_receipt = writer
        .append_decision(Digest32::ZERO, request, &decision_evidence, 50)
        .unwrap();

    let first = outcome("outcome-record-1", "outcome-1", None, 100);
    let first_evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&first),
    );
    let first_receipt = writer
        .append_outcome(decision_receipt.chain_digest, first, &first_evidence, 50)
        .unwrap();

    let corrected = outcome("outcome-record-2", "outcome-2", Some("outcome-1"), 120);
    let corrected_evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&corrected),
    );
    let corrected_receipt = writer
        .append_outcome(
            first_receipt.chain_digest,
            corrected,
            &corrected_evidence,
            50,
        )
        .unwrap();

    let batch = credit_batch();
    let batch_digest = finalize_credit_batch(batch.clone(), 50)
        .unwrap()
        .batch_digest;
    let credit_evidence = sign(
        writer.verifier(),
        "allocator",
        LearningEvidenceRoleV1::CreditAllocator,
        &credit_batch_signing_payload_v2(&batch, batch_digest),
    );
    let credit_receipt = writer
        .append_credit_batch(corrected_receipt.chain_digest, batch, &credit_evidence, 50)
        .unwrap();

    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let freeze_payload =
        dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap();
    let freeze_evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &freeze_payload,
    );
    let dataset = writer.freeze_dataset(plan, &freeze_evidence, 50).unwrap();
    assert_eq!(dataset.snapshot.source_record_digests.len(), 3);
    assert_eq!(dataset.snapshot.pending_outcomes, 0);
    assert_eq!(dataset.snapshot.censored_outcomes, 0);
    writer
        .revalidate_dataset_snapshot(&dataset, 50)
        .expect("fresh dataset remains current");

    let stale_source = UnlearningLineageRequestV1 {
        record_id: id("unlearning-stale-record"),
        lineage_id: id("unlearning-stale-lineage"),
        source_record_id: id("outcome-record-1"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("artifact-a"),
        reason_digest: digest("withdrawal"),
    };
    let stale_evidence = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&stale_source),
    );
    assert!(matches!(
        writer.append_unlearning(
            credit_receipt.chain_digest,
            stale_source,
            &dataset,
            &stale_evidence,
            50,
        ),
        Err(ProductionLedgerError::Binding(
            "unlearning source not in dataset"
        ))
    ));

    let unlearning = UnlearningLineageRequestV1 {
        record_id: id("unlearning-record"),
        lineage_id: id("unlearning-lineage"),
        source_record_id: id("outcome-record-2"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
        dataset_digest: dataset.snapshot.dataset_digest,
        artifact_id: id("artifact-a"),
        reason_digest: digest("withdrawal"),
    };
    let unlearning_evidence = sign(
        writer.verifier(),
        "privacy-owner",
        LearningEvidenceRoleV1::UnlearningAuthority,
        &unlearning_signing_payload_v1(&unlearning),
    );
    let receipt = writer
        .append_unlearning(
            credit_receipt.chain_digest,
            unlearning,
            &dataset,
            &unlearning_evidence,
            50,
        )
        .unwrap();

    let frontier = writer.witness_frontier().unwrap();
    assert_eq!(frontier.anchor.sequence, 5);
    assert_eq!(frontier.anchor.chain_digest, receipt.append.chain_digest);
    assert_eq!(receipt.dataset_digest, dataset.snapshot.dataset_digest);
    assert!(
        dataset
            .snapshot
            .source_record_digests
            .contains(&receipt.source_event_digest)
    );

    assert!(matches!(
        writer.revalidate_dataset_snapshot(&dataset, 50),
        Err(ProductionLedgerError::Binding(
            "dataset source revoked, corrected or unavailable"
        ))
    ));

    let core = LearningLedger::from_snapshot(writer.snapshot().unwrap()).unwrap();
    let active: Vec<_> = core
        .active_records()
        .iter()
        .map(|record| record.event.record_id().to_string())
        .collect();
    assert_eq!(active, vec!["decision-record", "unlearning-record"]);
}

#[test]
fn dataset_freeze_counts_decisions_without_any_outcome_as_pending() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();

    let first = decision();
    let first_payload = decision_signing_payload_v2(&first).unwrap();
    let first_evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &first_payload,
    );
    let first_receipt = writer
        .append_decision(Digest32::ZERO, first, &first_evidence, 50)
        .unwrap();

    let observed = outcome(
        "outcome-record-pending-test",
        "outcome-pending-test",
        None,
        100,
    );
    let observed_evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    let observed_receipt = writer
        .append_outcome(first_receipt.chain_digest, observed, &observed_evidence, 50)
        .unwrap();

    let mut pending = decision();
    pending.record_id = id("decision-record-without-outcome");
    pending.episode_id = id("episode-without-outcome");
    pending.completeness.set_id = id("candidate-set-without-outcome");
    pending.support_digest = digest("decision-support-without-outcome");
    let pending_payload = decision_signing_payload_v2(&pending).unwrap();
    let pending_evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &pending_payload,
    );
    writer
        .append_decision(
            observed_receipt.chain_digest,
            pending,
            &pending_evidence,
            50,
        )
        .unwrap();

    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("dataset-with-missing-outcome"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("inclusion-policy"),
    };
    let freeze_payload =
        dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap();
    let freeze_evidence = sign(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &freeze_payload,
    );
    let dataset = writer.freeze_dataset(plan, &freeze_evidence, 50).unwrap();

    assert_eq!(dataset.snapshot.pending_outcomes, 1);
    assert_eq!(dataset.snapshot.censored_outcomes, 0);
    assert_eq!(dataset.snapshot.source_record_digests.len(), 3);
}

#[test]
fn production_writer_recovers_against_independent_witness() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let request = decision();
    let payload = decision_signing_payload_v2(&request).unwrap();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    let receipt = writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
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
    let trust = activated_trust();
    let ledger_directory = fixture.directory();
    let witness_directory = fixture.directory();
    let recovered = LedgerWriter::from_durable(
        ledger,
        witness,
        trust,
        &ledger_directory,
        &witness_directory,
    )
    .unwrap();
    assert_eq!(
        recovered.witness_frontier().unwrap().anchor.chain_digest,
        receipt.chain_digest
    );
    assert_eq!(recovered.snapshot().unwrap().records().len(), 1);
}

#[test]
fn lost_ack_after_ledger_sync_reconciles_exact_decision_into_witness() {
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

    let reconciled = writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap();
    assert_eq!(reconciled.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(reconciled.chain_digest, committed.chain_digest);
    let frontier = writer.witness_frontier().unwrap();
    assert_eq!(frontier.anchor.sequence, 1);
    assert_eq!(frontier.anchor.chain_digest, committed.chain_digest);
}

#[test]
fn corrupt_or_missing_witness_history_never_falls_back_to_reinitialization() {
    let corrupt = Fixture::new();
    {
        let mut writer = corrupt.writer();
        let request = decision();
        let payload = decision_signing_payload_v2(&request).unwrap();
        let evidence = sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &payload,
        );
        writer
            .append_decision(Digest32::ZERO, request, &evidence, 50)
            .unwrap();
    }
    let mut bytes = fs::read(corrupt.root.join("witness")).unwrap();
    assert!(bytes.len() > 72);
    bytes[80] ^= 0x40;
    fs::write(corrupt.root.join("witness"), bytes).unwrap();
    assert_eq!(
        LedgerWitnessStore::recover(corrupt.file("witness"), binding()).err(),
        Some(DurableLedgerError::Corrupt)
    );

    let missing = Fixture::new();
    drop(LedgerWitnessStore::create(missing.file("witness"), binding()).unwrap());
    missing.file("witness").set_len(0).unwrap();
    assert_eq!(
        LedgerWitnessStore::recover(missing.file("witness"), binding()).err(),
        Some(DurableLedgerError::MissingHeader)
    );
}

#[test]
fn crash_after_ledger_sync_before_witness_child() {
    let Ok(root) = std::env::var("HEPTA_PRODUCTION_LEDGER_CRASH_FIXTURE") else {
        return;
    };
    let root = PathBuf::from(root);
    let open = |name: &str| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(root.join(name))
            .unwrap()
    };

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
        record_id: request.record_id,
        episode_id: request.episode_id,
        run_snapshot_digest: request.run_snapshot_digest,
        objective_digest: request.objective_digest,
        policy_digest: request.policy_digest,
        generator_id: principal.principal_id.clone(),
        generator_controller_id: verified.controller_id().clone(),
        generator_credential_chain_digest: principal.credential_chain_digest,
        generator_signing_key_digest: principal.signing_key_digest,
        generator_scope_digest: principal.scope_digest,
        generator_authority_epoch: principal.authority_epoch,
        candidate_ids: request.candidate_ids,
        selected_candidate_id: request.selected_candidate_id,
        selected_propensity: request.selected_propensity,
        candidate_completeness_digest: validate_production_completeness(&decision()).unwrap(),
        support_digest: request.support_digest,
        authentication_digest: signed_evidence_digest(&evidence),
    });

    drop(LedgerWitnessStore::create(open("witness"), binding()).unwrap());
    let mut ledger = DurableLedger::create(open("ledger"), binding(), 64).unwrap();
    ledger.append(Digest32::ZERO, event).unwrap();
    std::process::exit(31);
}

#[test]
fn process_death_between_ledger_and_witness_reconciles_without_redispatch() {
    let fixture = Fixture::new();
    let output = Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "production::tests::crash_after_ledger_sync_before_witness_child",
            "--nocapture",
        ])
        .env("HEPTA_PRODUCTION_LEDGER_CRASH_FIXTURE", &fixture.root)
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(31),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );

    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Unacknowledged,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let trust = activated_trust();
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

    let request = decision();
    let payload = decision_signing_payload_v2(&request).unwrap();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    let receipt = writer
        .append_decision(Digest32::ZERO, request, &evidence, 50)
        .unwrap();
    assert_eq!(receipt.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(writer.witness_frontier().unwrap().anchor.sequence, 1);
}

#[test]
fn directory_durability_requires_an_actual_directory_handle() {
    let fixture = Fixture::new();
    let directory = fixture.directory();
    sync_directory_handle(&directory).unwrap();
    assert_eq!(
        sync_directory_handle(&fixture.file("ledger")).err(),
        Some(DurableLedgerError::NotDirectory)
    );
}

#[test]
fn production_writer_rotates_root_signed_trust_and_rejects_revocation_and_rollback() {
    let fixture = Fixture::new();
    let mut writer = fixture.writer();
    let before = writer.witness_frontier().unwrap();
    let first = writer.trust_distribution_digest();
    let root_key = trust_root_key();
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut revoked = trust();
    revoked
        .signers
        .iter_mut()
        .find(|row| row.principal.principal_id == id("generator"))
        .unwrap()
        .revoked_at = Some(40);
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-revoked-generator"),
            generation: 2,
            effective_at: 40,
            trust: revoked,
        },
        root_id: root.root_id.clone(),
        issued_at: 35,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    let second = writer.rotate_trust(&root, signed.clone(), 50).unwrap();
    assert_ne!(first, second);
    let payload = decision_signing_payload_v2(&decision()).unwrap();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &payload,
    );
    assert!(matches!(
        writer.append_decision(Digest32::ZERO, decision(), &evidence, 50),
        Err(ProductionLedgerError::Evidence(
            SignedEvidenceError::Revoked
        ))
    ));
    assert!(matches!(
        writer.rotate_trust(&root, signed, 50),
        Err(crate::LearningTrustDistributionError::NonMonotonicRotation)
    ));
    assert_eq!(writer.trust_distribution_digest(), second);
    assert_eq!(writer.witness_frontier().unwrap(), before);
    assert!(writer.records().unwrap().is_empty());
}

#[test]
fn product_writer_history_growth_keeps_exact_retry_and_witness_after_reopen() {
    let fixture = Fixture::new();
    let ledger = DurableLedger::create(fixture.file("ledger"), binding(), 512).unwrap();
    let witness = LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let mut writer =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    let first = decision();
    let evidence = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&first).unwrap(),
    );
    let original = writer
        .append_decision(Digest32::ZERO, first.clone(), &evidence, 50)
        .unwrap();
    let mut predecessor = original.chain_digest;
    for index in 1..256 {
        let mut next = decision();
        next.record_id = id(&format!("growth-record-{index}"));
        next.episode_id = id(&format!("growth-episode-{index}"));
        let signed = sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&next).unwrap(),
        );
        predecessor = writer
            .append_decision(predecessor, next, &signed, 50)
            .unwrap()
            .chain_digest;
    }
    let before = writer.witness_frontier().unwrap();
    let retry = writer
        .append_decision(Digest32::ZERO, first.clone(), &evidence, 50)
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(writer.witness_frontier().unwrap(), before);
    writer
        .verify_active_decision_binding(&first.record_id, &first.episode_id)
        .unwrap();
    let records = writer.records().unwrap();
    assert_eq!(records.len(), 256);
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        512,
        LedgerRecovery::Acknowledged(before.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let mut recovered =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    assert_eq!(recovered.records().unwrap(), records);
    let retry = recovered
        .append_decision(Digest32::ZERO, first, &evidence, 50)
        .unwrap();
    assert_eq!(retry.chain_digest, original.chain_digest);
    assert_eq!(recovered.witness_frontier().unwrap(), before);
}

#[path = "production_growth_tests.rs"]
mod growth;

#[path = "production_freeze_tests.rs"]
mod freeze_tests;

#[path = "production_objective_index_tests.rs"]
mod objective_index_tests;

#[path = "production_recovery_tests.rs"]
mod recovery_tests;
