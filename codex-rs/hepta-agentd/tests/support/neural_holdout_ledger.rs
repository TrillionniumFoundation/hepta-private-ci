//! Controlled test signers around the original durable LedgerWriter.
//! Separate test keys exercise signature/role validation; they do not establish
//! independent administration, real model-training provenance, or efficacy.

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub fn micros() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_micros()
        .try_into()
        .unwrap()
}
pub fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000219").unwrap()
}
pub fn create(path: &Path) -> File {
    OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap()
}
pub fn actions() -> [StableId; 2] {
    [id("neural-no"), id("neural-yes")]
}

pub struct ControlledRoles {
    keys: [SigningKey; 3],
    pub principals: Vec<ledger::AuthenticatedPrincipalV1>,
    pub verifier: ledger::LearningEvidenceVerifierV1,
    trust: ledger::LearningEvidenceTrustV1,
    from: u64,
    until: u64,
    sequence: u64,
}

impl ControlledRoles {
    pub fn new() -> Self {
        let from = micros();
        let until = from + 3_600_000_000;
        let keys = [31, 47, 53].map(|byte| SigningKey::from_bytes(&[byte; 32]));
        let scope = hash("controlled-neural-comparison-scope-not-production");
        let kinds = [
            ledger::LearningEvidenceRoleV1::Generator,
            ledger::LearningEvidenceRoleV1::Evaluator,
            ledger::LearningEvidenceRoleV1::Observer,
        ];
        let principals: Vec<_> = keys
            .iter()
            .enumerate()
            .map(|(index, key)| ledger::AuthenticatedPrincipalV1 {
                principal_id: id(&format!("controlled-neural-role-{index}")),
                credential_chain_digest: hash(&format!("controlled-test-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 1,
                authenticated_at: from,
                expires_at: until,
            })
            .collect();
        let trust = ledger::LearningEvidenceTrustV1 {
            scope_digest: scope,
            objective_digest: hash("controlled-binary-integer-comparison-v1"),
            authority_epoch: 1,
            signers: keys
                .iter()
                .enumerate()
                .map(|(index, key)| ledger::TrustedLearningSignerV1 {
                    principal: principals[index].clone(),
                    controller_id: id(&format!("controlled-test-role-{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![kinds[index]],
                    revoked_at: None,
                })
                .collect(),
        };
        let verifier = ledger::LearningEvidenceVerifierV1::new(trust.clone()).unwrap();
        Self {
            keys,
            principals,
            verifier,
            trust,
            from,
            until,
            sequence: 0,
        }
    }

    pub fn sign(&mut self, index: usize, payload: &[u8]) -> ledger::SignedLearningEvidenceV1 {
        self.sequence += 1;
        let mut signed = ledger::SignedLearningEvidenceV1 {
            evidence_id: id(&format!("controlled-evidence-{}", self.sequence)),
            principal_id: self.principals[index].principal_id.clone(),
            role: self.trust.signers[index].roles[0],
            trust_digest: self.verifier.trust_digest(),
            scope_digest: self.trust.scope_digest,
            objective_digest: self.trust.objective_digest,
            authority_epoch: 1,
            issued_at: micros(),
            expires_at: self.until,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        signed.signature = self.keys[index].sign(&signed.signing_bytes()).to_bytes();
        signed
    }

    pub fn comparison_evidence(
        &mut self,
        bundle: &eval::IndependentEvaluationBundleV1,
        roles: &[eval::MetricRoleContractV2],
    ) -> eval::SignedEvaluationEvidenceV1 {
        let payload = eval::evaluation_signing_payload_v2(bundle, roles).unwrap();
        eval::SignedEvaluationEvidenceV1 {
            generator_plan: self.sign(/*index*/ 0, bundle.frozen_plan.plan_digest.as_array()),
            evaluator_bundle: self.sign(/*index*/ 1, &payload),
        }
    }

    pub fn context(&self) -> eval::ProductQualificationContextV1 {
        eval::ProductQualificationContextV1 {
            generator: self.principals[0].clone(),
            evaluator: self.principals[1].clone(),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        }
    }

    pub fn dataset(
        &mut self,
        root: &Path,
    ) -> (ledger::DatasetSnapshotReceiptV3, ledger::LedgerSnapshot) {
        std::fs::create_dir(root).unwrap();
        let root_key = SigningKey::from_bytes(&[61; 32]);
        let root_trust = ledger::LearningTrustRootV1 {
            root_id: id("controlled-neural-test-root"),
            scope_digest: self.trust.scope_digest,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: self.from,
            expires_at: self.until,
            revoked_at: None,
        };
        let now = micros();
        let mut distribution = ledger::SignedLearningTrustDistributionV1 {
            distribution: ledger::LearningTrustDistributionV1 {
                distribution_id: id("controlled-neural-test-distribution"),
                generation: 1,
                effective_at: now,
                trust: self.trust.clone(),
            },
            root_id: root_trust.root_id.clone(),
            issued_at: now,
            expires_at: self.until,
            signature: [0; 64],
        };
        distribution.signature = root_key
            .sign(&distribution.signing_bytes().unwrap())
            .to_bytes();
        let activated =
            ledger::activate_learning_trust(&root_trust, distribution, None, micros()).unwrap();
        let binding = hash("controlled-neural-estimator-ledger");
        let durable =
            ledger::DurableLedger::create(create(&root.join("ledger")), binding, 512).unwrap();
        let witness =
            ledger::LedgerWitnessStore::create(create(&root.join("witness")), binding).unwrap();
        let directory = File::open(root).unwrap();
        let mut writer =
            ledger::LedgerWriter::from_durable(durable, witness, activated, &directory, &directory)
                .unwrap();
        let mut candidates = actions().to_vec();
        candidates.push(id("abstain"));
        // Earlier calibration observations for the original nuisance estimator.
        // These do not train, modify or describe training of the neural model.
        for (task, (a, b)) in [(1, 3), (4, 2), (2, 8), (9, 4)].into_iter().enumerate() {
            for (action_index, action) in actions().iter().enumerate() {
                let episode = id(&format!("calibration-{task}-{action_index}"));
                let support = hash(&format!("controlled-calibration:{a}>{b}:{action}"));
                let decision = ledger::ProductionDecisionV2 {
                    record_id: id(&format!("{episode}-decision")),
                    episode_id: episode.clone(),
                    run_snapshot_digest: hash(&format!("{a}>{b}")),
                    objective_digest: self.trust.objective_digest,
                    policy_digest: hash("controlled-complete-two-action-census"),
                    candidate_ids: candidates.clone(),
                    selected_candidate_id: action.clone(),
                    selected_propensity: ProbabilityQ32::ONE,
                    completeness: ledger::CandidateSetCompletenessReceiptV1 {
                        set_id: id("controlled-two-answer-vocabulary"),
                        state_digest: support,
                        generator_id: self.principals[0].principal_id.clone(),
                        generator_code_digest: hash("controlled-comparison-test-v1"),
                        grammar_digest: hash("yes-or-no"),
                        hard_filter_digest: hash("complete-vocabulary"),
                        truncation_digest: hash("none"),
                        candidates_digest: ledger::candidate_ids_digest_v2(&candidates),
                        candidate_count: 3,
                        omitted_count_bound: 0,
                        canonical_order_digest: ledger::candidate_order_digest_v2(&candidates),
                        complete_for_generator: true,
                    },
                    support_digest: support,
                };
                let signed = self.sign(
                    /*index*/ 0,
                    &ledger::decision_signing_payload_v2(&decision).unwrap(),
                );
                let head = writer.witness_frontier().unwrap().anchor.chain_digest;
                let decision_receipt = writer
                    .append_decision(head, decision, &signed, micros())
                    .unwrap();
                let now = micros();
                let correct = (a > b) == (action_index == 1);
                let outcome = ledger::AuthenticatedOutcomeV1 {
                    record_id: id(&format!("{episode}-outcome")),
                    outcome_id: id(&format!("{episode}-result")),
                    episode_id: episode,
                    observer: self.principals[2].clone(),
                    observed_at: Some(now),
                    value: Some(if correct {
                        FixedQ32::ONE
                    } else {
                        FixedQ32::ZERO
                    }),
                    unit_profile_digest: hash("binary-correctness-0-or-1"),
                    support_digest: support,
                    watermark: ledger::OutcomeWatermarkV1 {
                        latest_observable_at: now,
                        expected_delay_profile_digest: hash("synchronous-score"),
                        terminality: ledger::OutcomeTerminalityV1::Terminal,
                        censoring_reason: None,
                        correction_predecessor: None,
                        finalized_at: Some(now),
                    },
                };
                let signed = self.sign(
                    /*index*/ 2,
                    &ledger::outcome_signing_payload_v2(&outcome),
                );
                writer
                    .append_outcome(decision_receipt.chain_digest, outcome, &signed, micros())
                    .unwrap();
            }
        }
        let plan = ledger::DatasetFreezePlanV2 {
            snapshot_id: id("controlled-neural-estimator-training"),
            objective_digest: self.trust.objective_digest,
            inclusion_policy_digest: hash("all-authenticated-terminal-calibration-outcomes"),
        };
        let signed = self.sign(
            /*index*/ 1,
            &ledger::dataset_freeze_signing_payload_v2(&writer.snapshot().unwrap(), &plan).unwrap(),
        );
        let dataset = writer.freeze_dataset(plan, &signed, micros()).unwrap();
        let snapshot = writer.snapshot().unwrap();
        ledger::verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &snapshot, micros())
            .unwrap();
        (dataset, snapshot)
    }
}
