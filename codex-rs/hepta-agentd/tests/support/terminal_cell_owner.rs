#![allow(clippy::unwrap_used)]
//! Qualification-only local keys and actual durable owners; no runtime authority.
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
static NEXT: AtomicU64 = AtomicU64::new(0);
pub(super) fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

pub(super) fn digest(value: &str) -> Digest32 {
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

pub(super) fn sign(
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

pub(super) struct Fixture {
    pub(super) root: PathBuf,
}

impl Fixture {
    pub(super) fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-cell-owner-loop-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        File::create(root.join("ledger")).unwrap();
        File::create(root.join("witness")).unwrap();
        Self { root }
    }

    pub(super) fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
            .unwrap()
    }

    pub(super) fn directory(&self) -> File {
        File::open(&self.root).unwrap()
    }

    pub(super) fn writer(&self) -> LedgerWriter {
        self.writer_with_limit(64)
    }

    pub(super) fn writer_with_limit(&self, limit: usize) -> LedgerWriter {
        let ledger = DurableLedger::create(self.file("ledger"), binding(), limit).unwrap();
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

impl Fixture {
    pub(super) fn recover_writer(
        &self,
        limit: usize,
        frontier: LedgerWitnessFrontier,
    ) -> LedgerWriter {
        let ledger = DurableLedger::recover(
            self.file("ledger"),
            binding(),
            limit,
            LedgerRecovery::Acknowledged(frontier.anchor),
        )
        .unwrap();
        let witness = LedgerWitnessStore::recover(self.file("witness"), binding()).unwrap();
        LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust(),
            &self.directory(),
            &self.directory(),
        )
        .unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

pub(super) fn decision() -> ProductionDecisionV2 {
    let candidates = vec![id("read"), id("abstain")];
    ProductionDecisionV2 {
        record_id: id("decision-record"),
        episode_id: id("episode"),
        run_snapshot_digest: digest("run-snapshot"),
        objective_digest: digest("objective"),
        policy_digest: digest("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("read"),
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

pub(super) fn outcome(
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

pub(super) fn rotate_trust(writer: &mut LedgerWriter) {
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
            distribution_id: id("successor-distribution"),
            generation: 2,
            effective_at: 50,
            trust: trust(),
        },
        root_id: root.root_id.clone(),
        issued_at: 50,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    writer.rotate_trust(&root, signed, 50).unwrap();
}
