use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

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

    fn writer(&self) -> LedgerWriter {
        let ledger = DurableLedger::create(self.file("ledger"), binding(), 64).unwrap();
        let witness = LedgerWitnessStore::create(self.file("witness"), binding()).unwrap();
        let verifier = LearningEvidenceVerifierV1::new(trust()).unwrap();
        LedgerWriter::from_durable(ledger, witness, verifier).unwrap()
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

fn outcome(record: &str, outcome: &str, predecessor: Option<&str>, value: i64) -> AuthenticatedOutcomeV1 {
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
        .append_outcome(
            decision_receipt.chain_digest,
            first,
            &first_evidence,
            50,
        )
        .unwrap();

    let corrected = outcome(
        "outcome-record-2",
        "outcome-2",
        Some("outcome-1"),
        120,
    );
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
        .append_credit_batch(
            corrected_receipt.chain_digest,
            batch,
            &credit_evidence,
            50,
        )
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

    let unlearning = UnlearningLineageRequestV1 {
        record_id: id("unlearning-record"),
        lineage_id: id("unlearning-lineage"),
        source_record_id: id("outcome-record-2"),
        dataset_snapshot_id: dataset.snapshot.snapshot_id.clone(),
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
            &unlearning_evidence,
            50,
        )
        .unwrap();

    let frontier = writer.witness_frontier().unwrap();
    assert_eq!(frontier.anchor.sequence, 5);
    assert_eq!(frontier.anchor.chain_digest, receipt.append.chain_digest);

    let core = LearningLedger::from_snapshot(writer.snapshot().unwrap()).unwrap();
    let active: Vec<_> = core
        .active_records()
        .iter()
        .map(|record| record.event.record_id().to_string())
        .collect();
    assert_eq!(active, vec!["decision-record", "unlearning-record"]);
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
    let verifier = LearningEvidenceVerifierV1::new(trust()).unwrap();
    let recovered = LedgerWriter::from_durable(ledger, witness, verifier).unwrap();
    assert_eq!(
        recovered.witness_frontier().unwrap().anchor.chain_digest,
        receipt.chain_digest
    );
    assert_eq!(recovered.snapshot().unwrap().records().len(), 1);
}
