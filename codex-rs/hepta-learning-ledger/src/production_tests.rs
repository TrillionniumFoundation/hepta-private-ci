use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationV1;
use crate::LearningEvidenceTrustV1;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;
use crate::TrustedLearningSignerV1;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("valid id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn signer(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key,
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
            signer(
                "generator",
                "controller-generator",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            signer(
                "observer",
                "controller-observer",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            signer(
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
    evidence_id: &str,
    name: &str,
    role: LearningEvidenceRoleV1,
    seed: u8,
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
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join("ledger"))
            .expect("create ledger");
        Self { root }
    }
    fn file(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("ledger"))
            .expect("open ledger")
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn production_writer_closes_signed_decision_outcome_credit_and_dataset_path() {
    let fixture = Fixture::new();
    let ledger =
        crate::DurableLedger::create(fixture.file(), digest("binding"), 32).expect("ledger");
    let verifier = LearningEvidenceVerifierV1::new(trust()).expect("trust");
    let generator_signed = sign(
        &verifier,
        "evidence-generator",
        "generator",
        LearningEvidenceRoleV1::Generator,
        1,
        b"decision",
    );
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &generator_signed,
            b"decision",
            50,
        )
        .expect("generator");
    let mut writer = ProductionLedgerWriter::new(ledger, verifier.clone());

    let decision = EpisodeDecision {
        record_id: id("decision-record"),
        episode_id: id("episode-1"),
        objective_digest: digest("objective"),
        policy_id: id("generator"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"decision"),
    };
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: id("candidate-set"),
        state_digest: digest("state"),
        generator_id: id("generator"),
        generator_code_digest: digest("code"),
        grammar_digest: digest("grammar"),
        hard_filter_digest: digest("hard-filter"),
        truncation_digest: digest("truncation"),
        candidates_digest: digest("candidates"),
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: digest("order"),
        complete_for_generator: true,
    };
    let zero = LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    };
    let decision_receipt = writer
        .append_decision(
            zero,
            decision,
            &completeness,
            &generator_signed,
            b"decision",
            50,
        )
        .expect("decision");

    let observer_signed = sign(
        &verifier,
        "evidence-observer",
        "observer",
        LearningEvidenceRoleV1::Observer,
        2,
        b"outcome",
    );
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer: trust().signers[1].principal.clone(),
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("unit"),
        support_digest: Digest32::of_bytes(b"outcome"),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 40,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(41),
        },
    };
    let outcome_receipt = writer
        .append_authenticated_outcome(
            LedgerAnchor {
                sequence: decision_receipt.sequence.get(),
                chain_digest: decision_receipt.chain_digest,
            },
            &generator,
            outcome,
            &observer_signed,
            b"outcome",
            50,
        )
        .expect("outcome");

    let credit_signed = sign(
        &verifier,
        "evidence-credit",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        b"credit",
    );
    let batch = CreditAllocationBatchV1 {
        batch_id: id("credit-batch"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        allocator: trust().signers[2].principal.clone(),
        terminal_outcome: FixedQ32::from_raw(100),
        allocations: vec![
            CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(60),
            },
            CreditAllocationV1 {
                target_id: id("artifact-b"),
                credit: FixedQ32::from_raw(30),
            },
        ],
        conservation_residual: FixedQ32::from_raw(10),
        support_digest: Digest32::of_bytes(b"credit"),
        finalized: true,
    };
    let credit_receipt = writer
        .append_credit_batch(
            LedgerAnchor {
                sequence: outcome_receipt.sequence.get(),
                chain_digest: outcome_receipt.chain_digest,
            },
            batch,
            &credit_signed,
            b"credit",
            50,
        )
        .expect("credit");

    let dataset_signed = sign(
        &verifier,
        "evidence-dataset",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        b"dataset",
    );
    let dataset = writer
        .freeze_dataset_from_ledger(
            LedgerAnchor {
                sequence: credit_receipt.sequence.get(),
                chain_digest: credit_receipt.chain_digest,
            },
            id("dataset-1"),
            digest("objective"),
            50,
            digest("inclusion-policy"),
            &dataset_signed,
            b"dataset",
            50,
        )
        .expect("dataset");
    assert_eq!(dataset.snapshot.source_record_digests.len(), 3);
    assert_eq!(dataset.snapshot.eligible_frontier, 3);
    assert_eq!(dataset.snapshot.ledger_head_digest, credit_receipt.chain_digest);
}
