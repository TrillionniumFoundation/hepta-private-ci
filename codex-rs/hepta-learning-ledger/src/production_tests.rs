use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::AuthenticatedPrincipalV1;
use crate::CandidateSetCompleteness;
use crate::CreditAllocationV1;
use crate::LearningEvidenceTrustProviderV1;
use crate::LearningEvidenceTrustSnapshotV1;
use crate::LearningEvidenceTrustV1;
use crate::OutcomeTerminalityV1;
use crate::OutcomeWatermarkV1;
use crate::SignedEvidenceError;
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

#[derive(Clone)]
struct MutableTrustProvider {
    current: Arc<Mutex<LearningEvidenceTrustSnapshotV1>>,
}

impl MutableTrustProvider {
    fn new(revision: u64, trust: LearningEvidenceTrustV1) -> Self {
        Self {
            current: Arc::new(Mutex::new(LearningEvidenceTrustSnapshotV1 {
                revision,
                valid_from: 1,
                valid_until: 100,
                trust,
            })),
        }
    }

    fn set_revision(&self, revision: u64) {
        self.current.lock().expect("trust lock").revision = revision;
    }

    fn replace(&self, revision: u64, trust: LearningEvidenceTrustV1) {
        *self.current.lock().expect("trust lock") = LearningEvidenceTrustSnapshotV1 {
            revision,
            valid_from: 1,
            valid_until: 100,
            trust,
        };
    }
}

impl LearningEvidenceTrustProviderV1 for MutableTrustProvider {
    fn current_trust(
        &self,
        _now: u64,
    ) -> Result<LearningEvidenceTrustSnapshotV1, SignedEvidenceError> {
        Ok(self.current.lock().expect("trust lock").clone())
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
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join("witness"))
            .expect("create witness");
        Self { root }
    }
    fn file(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("ledger"))
            .expect("open ledger")
    }

    fn witness_file(&self) -> std::fs::File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("witness"))
            .expect("open witness")
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
    let trust_state = trust();
    let verifier = LearningEvidenceVerifierV1::new(trust_state.clone()).expect("trust");
    let trust_provider = MutableTrustProvider::new(1, trust_state);
    let mut writer = ProductionLedgerWriter::new(ledger, trust_provider);

    let mut decision = EpisodeDecision {
        record_id: id("decision-record"),
        episode_id: id("episode-1"),
        objective_digest: digest("objective"),
        policy_id: id("generator"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::ZERO,
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
    let decision_payload =
        decision_admission_payload(&decision, &completeness).expect("decision payload");
    decision.support_digest = Digest32::of_bytes(&decision_payload);
    let generator_signed = sign(
        &verifier,
        "evidence-generator",
        "generator",
        LearningEvidenceRoleV1::Generator,
        1,
        &decision_payload,
    );
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &generator_signed,
            &decision_payload,
            50,
        )
        .expect("generator");
    let zero = LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    };
    let mut drifted_decision = decision.clone();
    drifted_decision.selected_candidate_id = id("abstain");
    assert_eq!(
        writer.append_decision(
            zero,
            drifted_decision,
            &completeness,
            &generator_signed,
            &decision_payload,
            50,
        ),
        Err(ProductionLedgerError::AdmissionPayloadMismatch)
    );
    let decision_receipt = writer
        .append_decision(
            zero,
            decision,
            &completeness,
            &generator_signed,
            &decision_payload,
            50,
        )
        .expect("decision");

    let mut outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer: trust().signers[1].principal.clone(),
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: digest("unit"),
        support_digest: Digest32::ZERO,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 40,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(41),
        },
    };
    let outcome_payload = authenticated_outcome_admission_payload(&outcome);
    outcome.support_digest = Digest32::of_bytes(&outcome_payload);
    let observer_signed = sign(
        &verifier,
        "evidence-observer",
        "observer",
        LearningEvidenceRoleV1::Observer,
        2,
        &outcome_payload,
    );
    let outcome_receipt = writer
        .append_authenticated_outcome(
            LedgerAnchor {
                sequence: decision_receipt.sequence.get(),
                chain_digest: decision_receipt.chain_digest,
            },
            &generator,
            outcome,
            &observer_signed,
            &outcome_payload,
            50,
        )
        .expect("outcome");

    let mut batch = CreditAllocationBatchV1 {
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
        support_digest: Digest32::ZERO,
        finalized: true,
    };
    let credit_payload = credit_batch_admission_payload(&batch);
    batch.support_digest = Digest32::of_bytes(&credit_payload);
    let credit_signed = sign(
        &verifier,
        "evidence-credit",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        &credit_payload,
    );
    let credit_receipt = writer
        .append_credit_batch(
            LedgerAnchor {
                sequence: outcome_receipt.sequence.get(),
                chain_digest: outcome_receipt.chain_digest,
            },
            batch,
            &credit_signed,
            &credit_payload,
            50,
        )
        .expect("credit");

    let mut witness =
        DurableAnchorWitness::create(fixture.witness_file(), digest("witness-binding"))
            .expect("witness");
    let retained = writer
        .retain_acknowledgement(&mut witness, &credit_receipt)
        .expect("retain acknowledgement");
    assert_eq!(retained.sequence, credit_receipt.sequence.get());
    assert_eq!(retained.chain_digest, credit_receipt.chain_digest);

    let dataset_anchor = LedgerAnchor {
        sequence: credit_receipt.sequence.get(),
        chain_digest: credit_receipt.chain_digest,
    };
    let dataset_request = writer
        .prepare_dataset_freeze_request(
            dataset_anchor,
            id("dataset-1"),
            trust().signers[2].principal.clone(),
            digest("objective"),
            50,
            digest("inclusion-policy"),
        )
        .expect("prepare dataset");
    let dataset_payload = dataset_freeze_admission_payload(&dataset_request);
    let dataset_signed = sign(
        &verifier,
        "evidence-dataset",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        &dataset_payload,
    );
    let dataset = writer
        .freeze_dataset_from_ledger(
            dataset_anchor,
            id("dataset-1"),
            digest("objective"),
            50,
            digest("inclusion-policy"),
            &dataset_signed,
            &dataset_payload,
            50,
        )
        .expect("dataset");
    assert_eq!(dataset.snapshot.source_record_digests.len(), 3);
    assert_eq!(dataset.snapshot.eligible_frontier, 3);
    assert_eq!(
        dataset.snapshot.ledger_head_digest,
        credit_receipt.chain_digest
    );

    let revocation = Revocation {
        record_id: id("revoke-decision"),
        target_record_id: id("decision-record"),
        authority_id: id("evaluator"),
        reason_digest: digest("privacy-erasure-request"),
    };
    let revocation_payload = revocation_admission_payload(&revocation);
    let revocation_signed = sign(
        &verifier,
        "evidence-revocation",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        &revocation_payload,
    );
    let revocation_receipt = writer
        .append_revocation(
            dataset_anchor,
            revocation,
            &revocation_signed,
            &revocation_payload,
            50,
        )
        .expect("revocation");

    let dataset_lineage = UnlearningLineageEventV1 {
        record_id: id("unlearning-dataset"),
        source_record_id: id("decision-record"),
        derived_id: id("dataset-1"),
        derived_kind: UnlearningDerivedKindV1::Dataset,
        predecessor: None,
        upstream_derived_id: None,
        upstream_derived_digest: None,
        authority_id: id("evaluator"),
        reason_digest: digest("privacy-erasure-request"),
        source_digest: decision_receipt.event_digest,
        derived_digest: dataset.snapshot.dataset_digest,
    };
    let dataset_unlearning_payload = unlearning_admission_payload(&dataset_lineage);
    let dataset_unlearning_signed = sign(
        &verifier,
        "evidence-unlearning-dataset",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        &dataset_unlearning_payload,
    );
    let dataset_lineage_receipt = writer
        .append_unlearning_lineage(
            LedgerAnchor {
                sequence: revocation_receipt.sequence.get(),
                chain_digest: revocation_receipt.chain_digest,
            },
            dataset_lineage,
            &dataset_unlearning_signed,
            &dataset_unlearning_payload,
            50,
        )
        .expect("dataset unlearning");

    let artifact_lineage = UnlearningLineageEventV1 {
        record_id: id("unlearning-artifact"),
        source_record_id: id("decision-record"),
        derived_id: id("artifact-1"),
        derived_kind: UnlearningDerivedKindV1::Artifact,
        predecessor: None,
        upstream_derived_id: Some(id("dataset-1")),
        upstream_derived_digest: Some(dataset.snapshot.dataset_digest),
        authority_id: id("evaluator"),
        reason_digest: digest("privacy-erasure-request"),
        source_digest: decision_receipt.event_digest,
        derived_digest: digest("artifact-1"),
    };
    let artifact_payload = unlearning_admission_payload(&artifact_lineage);
    let artifact_signed = sign(
        &verifier,
        "evidence-unlearning-artifact",
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        3,
        &artifact_payload,
    );
    let artifact_anchor = writer.current_anchor().expect("dataset lineage anchor");
    let artifact_receipt = writer
        .append_unlearning_lineage(
            artifact_anchor,
            artifact_lineage,
            &artifact_signed,
            &artifact_payload,
            50,
        )
        .expect("artifact unlearning");
    assert_eq!(
        artifact_receipt.upstream_derived_id,
        Some(id("dataset-1"))
    );
    assert_eq!(
        dataset_lineage_receipt.derived_id,
        id("dataset-1")
    );
}

#[test]
fn production_writer_reloads_current_trust_and_rejects_rollback() {
    let fixture = Fixture::new();
    let ledger =
        crate::DurableLedger::create(fixture.file(), digest("binding-trust"), 8).expect("ledger");
    let initial_trust = trust();
    let provider = MutableTrustProvider::new(1, initial_trust);
    let control = provider.clone();
    let mut writer = ProductionLedgerWriter::new(ledger, provider);

    let first = writer.current_trust_digest(50).expect("revision one");

    let mut revoked_trust = trust();
    revoked_trust.signers[0].revoked_at = Some(40);
    let revoked_verifier =
        LearningEvidenceVerifierV1::new(revoked_trust.clone()).expect("revoked trust snapshot");
    control.replace(2, revoked_trust);
    let second = writer.current_trust_digest(50).expect("revision two");
    assert_ne!(first, second);

    let mut decision = EpisodeDecision {
        record_id: id("revoked-decision-record"),
        episode_id: id("revoked-episode"),
        objective_digest: digest("objective"),
        policy_id: id("generator"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: ProbabilityQ32::from_raw(1 << 31).expect("probability"),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::ZERO,
    };
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: id("revoked-set"),
        state_digest: digest("revoked-state"),
        generator_id: id("generator"),
        generator_code_digest: digest("revoked-code"),
        grammar_digest: digest("revoked-grammar"),
        hard_filter_digest: digest("revoked-filter"),
        truncation_digest: digest("revoked-truncation"),
        candidates_digest: digest("revoked-candidates"),
        candidate_count: 2,
        omitted_count_bound: 0,
        canonical_order_digest: digest("revoked-order"),
        complete_for_generator: true,
    };
    let payload = decision_admission_payload(&decision, &completeness).expect("payload");
    decision.support_digest = Digest32::of_bytes(&payload);
    let signed = sign(
        &revoked_verifier,
        "revoked-evidence",
        "generator",
        LearningEvidenceRoleV1::Generator,
        1,
        &payload,
    );
    assert_eq!(
        writer.append_decision(
            LedgerAnchor {
                sequence: 0,
                chain_digest: Digest32::ZERO,
            },
            decision,
            &completeness,
            &signed,
            &payload,
            50,
        ),
        Err(ProductionLedgerError::Signed(SignedEvidenceError::Revoked))
    );

    control.set_revision(1);
    assert_eq!(
        writer.current_trust_digest(50),
        Err(ProductionLedgerError::TrustRollback)
    );
}
