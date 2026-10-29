//! Scoped study roles around the actual supervised training population.
//! Four separately keyed roles are controlled by this test host; external
//! administrative independence and production enrollment are not claimed.

use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::Value;

pub fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("{error:?}"))
}
pub fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub fn micros() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|error| panic!("{error:?}"))
        .as_micros()
        .try_into()
        .unwrap_or_else(|error| panic!("{error:?}"))
}
pub fn create(path: &Path) -> File {
    OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap_or_else(|error| panic!("{error:?}"))
}

pub struct ControlledRoles {
    keys: [SigningKey; 4],
    pub principals: Vec<ledger::AuthenticatedPrincipalV1>,
    pub verifier: ledger::LearningEvidenceVerifierV1,
    pub trust: ledger::LearningEvidenceTrustV1,
    actions: [StableId; 2],
    yes: StableId,
    from: u64,
    until: u64,
    sequence: u64,
}

impl ControlledRoles {
    pub fn new(objective: Digest32, actions: [StableId; 2], yes: StableId) -> Self {
        let from = micros();
        let until = from + 3_600_000_000;
        let keys = [31, 47, 53, 89].map(|byte| SigningKey::from_bytes(&[byte; 32]));
        let scope = hash("controlled-neural-comparison-scope-not-production");
        let kinds = [
            ledger::LearningEvidenceRoleV1::Generator,
            ledger::LearningEvidenceRoleV1::Evaluator,
            ledger::LearningEvidenceRoleV1::Observer,
            ledger::LearningEvidenceRoleV1::Selector,
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
            objective_digest: objective,
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
        let verifier = ledger::LearningEvidenceVerifierV1::new(trust.clone())
            .unwrap_or_else(|error| panic!("{error:?}"));
        Self {
            keys,
            principals,
            verifier,
            trust,
            from,
            until,
            sequence: 0,
            actions,
            yes,
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
        profile: super::StudyProfile,
        root: &Path,
        training_rows: &[Value],
    ) -> (ledger::DatasetSnapshotReceiptV3, ledger::LedgerSnapshot) {
        assert_eq!(training_rows.len(), profile.training_source_rows());
        std::fs::create_dir(root).unwrap_or_else(|error| panic!("{error:?}"));
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
            .sign(
                &distribution
                    .signing_bytes()
                    .unwrap_or_else(|error| panic!("{error:?}")),
            )
            .to_bytes();
        let activated = ledger::activate_learning_trust(&root_trust, distribution, None, micros())
            .unwrap_or_else(|error| panic!("{error:?}"));
        let binding = profile.training_ledger_binding();
        let durable = ledger::DurableLedger::create(create(&root.join("ledger")), binding, 512)
            .unwrap_or_else(|error| panic!("{error:?}"));
        let witness = ledger::LedgerWitnessStore::create(create(&root.join("witness")), binding)
            .unwrap_or_else(|error| panic!("{error:?}"));
        let directory = File::open(root).unwrap_or_else(|error| panic!("{error:?}"));
        let mut writer =
            ledger::LedgerWriter::from_durable(durable, witness, activated, &directory, &directory)
                .unwrap_or_else(|error| panic!("{error:?}"));
        let mut candidates = self.actions.to_vec();
        candidates.push(id("abstain"));
        // One ground-truth answer per exact supervised row consumed by the
        // selected trainer. These are labels, not claims that a neural
        // forward generated an answer. No counterfactual answer is admitted.
        // Each row's canonical
        // prompt, target, source group and original id are bound before training.
        let actions = self.actions.clone();
        for (task, row) in training_rows.iter().enumerate() {
            let bytes = serde_json::to_vec(row).unwrap_or_else(|error| panic!("{error:?}"));
            let row_digest = Digest32::of_bytes(&bytes);
            let expected_yes = row["expected_output"]
                .as_str()
                .expect("validated training target")
                == "yes";
            for (action_index, action) in actions.iter().enumerate() {
                if (*action == self.yes) != expected_yes {
                    continue;
                }
                let episode = id(&format!("training-{task}-{action_index}"));
                let support =
                    Digest32::of_parts(&[row_digest.as_array(), action.as_str().as_bytes()]);
                let decision = ledger::ProductionDecisionV2 {
                    record_id: id(&format!("{episode}-decision")),
                    episode_id: episode.clone(),
                    run_snapshot_digest: row_digest,
                    objective_digest: self.trust.objective_digest,
                    policy_digest: hash(match profile {
                        super::StudyProfile::OriginalV1 | super::StudyProfile::BinaryAnswerV2 => {
                            "original-supervised-target-is-the-training-label"
                        }
                        super::StudyProfile::BinaryDiverse60V3 => {
                            "diverse60-public-target-is-the-training-label-v3"
                        }
                    }),
                    candidate_ids: candidates.clone(),
                    selected_candidate_id: action.clone(),
                    selected_propensity: ProbabilityQ32::ONE,
                    completeness: ledger::CandidateSetCompletenessReceiptV1 {
                        set_id: id("controlled-two-answer-vocabulary"),
                        state_digest: support,
                        generator_id: self.principals[0].principal_id.clone(),
                        generator_code_digest: hash(match profile {
                            super::StudyProfile::OriginalV1
                            | super::StudyProfile::BinaryAnswerV2 => {
                                "exact-original-supervised-training-row-v1"
                            }
                            super::StudyProfile::BinaryDiverse60V3 => {
                                "exact-diverse60-supervised-training-row-v3"
                            }
                        }),
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
                    &ledger::decision_signing_payload_v2(&decision)
                        .unwrap_or_else(|error| panic!("{error:?}")),
                );
                let head = writer
                    .witness_frontier()
                    .unwrap_or_else(|error| panic!("{error:?}"))
                    .anchor
                    .chain_digest;
                let decision_receipt = writer
                    .append_decision(head, decision, &signed, micros())
                    .unwrap_or_else(|error| panic!("{error:?}"));
                let now = micros();
                let correct = expected_yes == (*action == self.yes);
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
                    .unwrap_or_else(|error| panic!("{error:?}"));
            }
        }
        let plan = ledger::DatasetFreezePlanV2 {
            snapshot_id: id("controlled-neural-actual-training"),
            objective_digest: self.trust.objective_digest,
            inclusion_policy_digest: hash(match profile {
                super::StudyProfile::OriginalV1 | super::StudyProfile::BinaryAnswerV2 => {
                    "one-authenticated-original-target-for-each-of-ten-consumed-training-rows"
                }
                super::StudyProfile::BinaryDiverse60V3 => {
                    "one-authenticated-public-target-for-each-of-sixty-distinct-training-rows-v3"
                }
            }),
        };
        let signed = self.sign(
            /*index*/ 1,
            &ledger::dataset_freeze_signing_payload_v2(
                &writer
                    .snapshot()
                    .unwrap_or_else(|error| panic!("{error:?}")),
                &plan,
            )
            .unwrap_or_else(|error| panic!("{error:?}")),
        );
        let dataset = writer
            .freeze_dataset(plan, &signed, micros())
            .unwrap_or_else(|error| panic!("{error:?}"));
        let snapshot = writer
            .snapshot()
            .unwrap_or_else(|error| panic!("{error:?}"));
        ledger::verify_dataset_snapshot_receipt_against_ledger_v3(&dataset, &snapshot, micros())
            .unwrap_or_else(|error| panic!("{error:?}"));
        (dataset, snapshot)
    }
}
