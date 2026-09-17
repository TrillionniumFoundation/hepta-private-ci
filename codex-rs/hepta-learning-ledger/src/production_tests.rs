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
use pretty_assertions::assert_eq;

use crate::AuthenticatedPrincipalV1;
use crate::CreditAllocationV1;
use crate::FileLearningWitnessStore;
use crate::LearningEvidenceTrustV1;
use crate::OutcomeWatermarkV1;
use crate::TrustedLearningSignerV1;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn key(seed: u8) -> [u8; 32] {
    SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes()
}

fn trusted(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let verifying_key = key(seed);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("credential-{name}")),
            signing_key_digest: Digest32::of_bytes(&verifying_key),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key,
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
                "controller-generator",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                "observer",
                "controller-observer",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            trusted(
                "evaluator",
                "controller-evaluator",
                3,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    evidence_id: &str,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
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
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

fn placeholder(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
    evidence_id: &str,
) -> SignedLearningEvidenceV1 {
    sign(verifier, name, role, seed, evidence_id, b"placeholder")
}

fn completeness() -> CandidateSetCompletenessReceiptV1 {
    CandidateSetCompletenessReceiptV1 {
        set_id: id("candidate-set"),
        state_digest: digest("state"),
        generator_id: id("generator"),
        generator_code_digest: digest("generator-code"),
        grammar_digest: digest("grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: digest("candidate-set-bytes"),
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: digest("candidate-order"),
        complete_for_generator: true,
    }
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
        fs::create_dir(&root).expect("create fixture");
        for name in ["ledger", "witness"] {
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(root.join(name))
                .expect("create file");
        }
        Self { root }
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .expect("open fixture file")
    }

    fn service(
        &self,
    ) -> ProductionLearningLedger<crate::DurableLedger, FileLearningWitnessStore> {
        let verifier = LearningEvidenceVerifierV1::new(trust()).expect("trust");
        let ledger = crate::DurableLedger::create(
            self.file("ledger"),
            digest("ledger-binding"),
            64,
        )
        .expect("ledger");
        let witness = FileLearningWitnessStore::create(
            self.file("witness"),
            digest("witness-binding"),
        )
        .expect("witness");
        ProductionLearningLedger::new(verifier, ledger, witness).expect("production service")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn signed_decision_request(
    service: &ProductionLearningLedger<crate::DurableLedger, FileLearningWitnessStore>,
) -> ProductionDecisionRequestV1 {
    let mut request = ProductionDecisionRequestV1 {
        record_id: id("decision-record"),
        episode_id: id("episode"),
        objective_digest: digest("objective"),
        policy_id: id("candidate-policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: completeness(),
        generator_evidence: placeholder(
            service.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            1,
            "decision-evidence",
        ),
        expected_predecessor: Digest32::ZERO,
    };
    let completeness_digest =
        validate_candidate_set_completeness(&request.completeness).expect("completeness");
    let payload =
        production_decision_signing_payload_v1(&request, completeness_digest).expect("payload");
    request.generator_evidence = sign(
        service.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        1,
        "decision-evidence",
        &payload,
    );
    request
}

fn signed_outcome_request(
    service: &ProductionLearningLedger<crate::DurableLedger, FileLearningWitnessStore>,
    outcome: AuthenticatedOutcomeV1,
    predecessor: Digest32,
    evidence_id: &str,
) -> ProductionOutcomeRequestV1 {
    let payload = production_outcome_signing_payload_v1(&outcome, predecessor)
        .expect("outcome payload");
    ProductionOutcomeRequestV1 {
        outcome,
        observer_evidence: sign(
            service.verifier(),
            "observer",
            LearningEvidenceRoleV1::Observer,
            2,
            evidence_id,
            &payload,
        ),
        expected_predecessor: predecessor,
    }
}

#[test]
fn production_path_authenticates_writes_conserves_credit_and_freezes_from_ledger() {
    let fixture = Fixture::new();
    let mut service = fixture.service();

    let decision_request = signed_decision_request(&service);
    let decision = service
        .append_decision(decision_request, 50)
        .expect("decision");
    assert_eq!(decision.commit.witness.anchor.sequence, 1);

    let observer = trust().signers[1].principal.clone();
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("reward-unit"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let outcome_request = signed_outcome_request(
        &service,
        outcome,
        decision.commit.ledger.chain_digest,
        "outcome-evidence",
    );
    let outcome_commit = service
        .append_outcome(&decision.generator, outcome_request, 50)
        .expect("outcome");
    assert_eq!(outcome_commit.witness.anchor.sequence, 2);

    let allocator = trust().signers[2].principal.clone();
    let mut credit_request = ProductionCreditBatchRequestV1 {
        record_id: id("credit-record"),
        batch: CreditAllocationBatchV1 {
            batch_id: id("credit-batch"),
            episode_id: id("episode"),
            outcome_id: id("outcome"),
            allocator,
            terminal_outcome: FixedQ32::from_raw(100),
            allocations: vec![
                CreditAllocationV1 {
                    target_id: id("artifact-b"),
                    credit: FixedQ32::from_raw(30),
                },
                CreditAllocationV1 {
                    target_id: id("artifact-a"),
                    credit: FixedQ32::from_raw(60),
                },
            ],
            conservation_residual: FixedQ32::from_raw(10),
            support_digest: digest("credit-support"),
            finalized: true,
        },
        allocator_evidence: placeholder(
            service.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            3,
            "credit-evidence",
        ),
        expected_predecessor: outcome_commit.ledger.chain_digest,
    };
    let credit_payload =
        production_credit_batch_signing_payload_v1(&credit_request).expect("credit payload");
    credit_request.allocator_evidence = sign(
        service.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        "credit-evidence",
        &credit_payload,
    );
    let credit = service
        .append_credit_batch(&decision.generator, credit_request, 50)
        .expect("credit");
    assert_eq!(credit.witness.anchor.sequence, 3);

    let mut freeze_request = ProductionDatasetFreezeRequestV1 {
        snapshot_id: id("dataset"),
        objective_digest: digest("objective"),
        eligible_frontier: 3,
        outcome_watermark: 50,
        ledger_head_digest: credit.ledger.chain_digest,
        evaluator_evidence: placeholder(
            service.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            3,
            "freeze-evidence",
        ),
    };
    let freeze_payload =
        production_dataset_freeze_signing_payload_v1(&freeze_request).expect("freeze payload");
    freeze_request.evaluator_evidence = sign(
        service.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        "freeze-evidence",
        &freeze_payload,
    );
    let dataset = service.freeze_dataset(freeze_request, 50).expect("dataset");
    assert_eq!(dataset.snapshot.source_record_digests.len(), 3);
    assert_eq!(dataset.snapshot.pending_outcomes, 0);
    assert_eq!(dataset.snapshot.censored_outcomes, 0);
}

#[test]
fn corrections_supersede_pending_outcome_in_ledger_derived_dataset() {
    let fixture = Fixture::new();
    let mut service = fixture.service();
    let decision_request = signed_decision_request(&service);
    let decision = service
        .append_decision(decision_request, 50)
        .expect("decision");

    let observer = trust().signers[1].principal.clone();
    let pending = AuthenticatedOutcomeV1 {
        record_id: id("pending-record"),
        outcome_id: id("pending-outcome"),
        episode_id: id("episode"),
        observer: observer.clone(),
        observed_at: None,
        value: None,
        unit_profile_digest: digest("reward-unit"),
        support_digest: digest("pending-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 40,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Pending,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: None,
        },
    };
    let pending_request = signed_outcome_request(
        &service,
        pending,
        decision.commit.ledger.chain_digest,
        "pending-evidence",
    );
    let pending_commit = service
        .append_outcome(&decision.generator, pending_request, 50)
        .expect("pending");

    let terminal = AuthenticatedOutcomeV1 {
        record_id: id("terminal-record"),
        outcome_id: id("terminal-outcome"),
        episode_id: id("episode"),
        observer,
        observed_at: Some(42),
        value: Some(FixedQ32::from_raw(7)),
        unit_profile_digest: digest("reward-unit"),
        support_digest: digest("terminal-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: Some(id("pending-outcome")),
            finalized_at: Some(46),
        },
    };
    let terminal_request = signed_outcome_request(
        &service,
        terminal,
        pending_commit.ledger.chain_digest,
        "terminal-evidence",
    );
    let terminal_commit = service
        .append_outcome(&decision.generator, terminal_request, 50)
        .expect("terminal");

    let mut freeze_request = ProductionDatasetFreezeRequestV1 {
        snapshot_id: id("dataset-corrected"),
        objective_digest: digest("objective"),
        eligible_frontier: 3,
        outcome_watermark: 50,
        ledger_head_digest: terminal_commit.ledger.chain_digest,
        evaluator_evidence: placeholder(
            service.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            3,
            "freeze-corrected-evidence",
        ),
    };
    let payload =
        production_dataset_freeze_signing_payload_v1(&freeze_request).expect("freeze payload");
    freeze_request.evaluator_evidence = sign(
        service.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        "freeze-corrected-evidence",
        &payload,
    );
    let dataset = service.freeze_dataset(freeze_request, 50).expect("dataset");
    assert_eq!(dataset.snapshot.source_record_digests.len(), 2);
    assert_eq!(dataset.snapshot.pending_outcomes, 0);
    assert_eq!(dataset.snapshot.censored_outcomes, 0);
    assert!(!dataset.correction_cut_digest.is_zero());
}

#[test]
fn invalid_credit_conservation_never_advances_witness() {
    let fixture = Fixture::new();
    let mut service = fixture.service();
    let decision_request = signed_decision_request(&service);
    let decision = service
        .append_decision(decision_request, 50)
        .expect("decision");

    let observer = trust().signers[1].principal.clone();
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: id("episode"),
        observer,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("reward-unit"),
        support_digest: digest("outcome-support"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay-profile"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let outcome_request = signed_outcome_request(
        &service,
        outcome,
        decision.commit.ledger.chain_digest,
        "outcome-evidence",
    );
    let outcome_commit = service
        .append_outcome(&decision.generator, outcome_request, 50)
        .expect("outcome");

    let allocator = trust().signers[2].principal.clone();
    let mut request = ProductionCreditBatchRequestV1 {
        record_id: id("bad-credit-record"),
        batch: CreditAllocationBatchV1 {
            batch_id: id("bad-credit-batch"),
            episode_id: id("episode"),
            outcome_id: id("outcome"),
            allocator,
            terminal_outcome: FixedQ32::from_raw(100),
            allocations: vec![CreditAllocationV1 {
                target_id: id("artifact"),
                credit: FixedQ32::from_raw(80),
            }],
            conservation_residual: FixedQ32::from_raw(10),
            support_digest: digest("credit-support"),
            finalized: true,
        },
        allocator_evidence: placeholder(
            service.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            3,
            "bad-credit-evidence",
        ),
        expected_predecessor: outcome_commit.ledger.chain_digest,
    };
    let payload = production_credit_batch_signing_payload_v1(&request).expect("credit payload");
    request.allocator_evidence = sign(
        service.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        "bad-credit-evidence",
        &payload,
    );
    assert!(matches!(
        service.append_credit_batch(&decision.generator, request, 50),
        Err(ProductionLedgerError::Causal(CausalV2Error::CreditConservation))
    ));
    assert_eq!(service.witness_anchor().sequence, 2);
    assert_eq!(service.snapshot().expect("snapshot").records().len(), 2);
}
