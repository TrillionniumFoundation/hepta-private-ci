//! Synthetic signed observations and ledger-core fixtures for source admission.
//! These do not establish real future-calendar efficacy or production storage.
use super::*;
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[path = "self_evolution_qualification_test_support.rs"]
mod qualification_support;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Signers {
    keys: [SigningKey; 4],
    principals: Vec<AuthenticatedPrincipalV1>,
    verifier: LearningEvidenceVerifierV1,
}

impl Signers {
    fn new() -> Self {
        let keys = [11, 22, 33, 44].map(|byte| SigningKey::from_bytes(&[byte; 32]));
        let principals = keys
            .iter()
            .enumerate()
            .map(|(index, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("longitudinal-signer-{index}")),
                credential_chain_digest: digest(&format!("credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("longitudinal-scope"),
                authority_epoch: 7,
                authenticated_at: 1,
                expires_at: 100,
            })
            .collect::<Vec<_>>();
        let roles = [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Selector,
        ];
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("longitudinal-scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: principals
                .iter()
                .zip(&keys)
                .zip(roles)
                .map(|((principal, key), role)| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: principal.principal_id.clone(),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![role],
                    revoked_at: None,
                })
                .collect(),
        })
        .unwrap();
        Self {
            keys,
            principals,
            verifier,
        }
    }

    fn sign(
        &self,
        signer: usize,
        role: LearningEvidenceRoleV1,
        issued_at: u64,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("longitudinal-attestation-{signer}")),
            principal_id: self.principals[signer].principal_id.clone(),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: digest("longitudinal-scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at,
            expires_at: 99,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[signer].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
}

struct Fixture {
    signers: Signers,
    dataset_request: DatasetFreezeRequestV1,
    dataset: DatasetSnapshotReceiptV3,
    ledger: LedgerSnapshot,
    policy: SelfEvolutionSelectionPolicyV1,
    request: SelfEvolutionSelectionRequestV1,
    qualification: ProductQualificationReceiptV1,
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: SignedEvaluationEvidenceV1,
    timing: LongitudinalTimeEvidenceV1,
}

impl Fixture {
    fn new(publication_namespace: Digest32) -> Self {
        let signers = Signers::new();
        let mut ledger = LearningLedger::new();
        ledger
            .append(LedgerEvent::Decision(EpisodeDecision {
                record_id: id("source-decision"),
                episode_id: id("source-episode"),
                objective_digest: digest("objective"),
                policy_id: id("source-policy"),
                candidate_ids: vec![id("observed-action"), id("abstain")],
                selected_candidate_id: id("observed-action"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompleteness::Complete,
                support_digest: digest("synthetic-source-support"),
            }))
            .unwrap();
        let ledger = ledger.snapshot();
        let dataset_request = DatasetFreezeRequestV1 {
            snapshot_id: id("dataset"),
            producer: signers.principals[0].clone(),
            ledger_head_digest: ledger.head_digest,
            objective_digest: digest("objective"),
            eligible_frontier: 1,
            outcome_watermark: 50,
            correction_cut_digest: digest("corrections"),
            revocation_cut_digest: digest("revocations"),
            inclusion_policy_digest: digest("inclusion"),
            source_record_digests: ledger
                .records()
                .iter()
                .map(|row| row.event_digest)
                .collect(),
            pending_outcomes: 0,
            censored_outcomes: 0,
        };
        let dataset = freeze_dataset_receipt_v3(dataset_request.clone(), /*now*/ 70).unwrap();
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("quality"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let (runner, temporal) = qualification_support::evaluate(
            CrossFoldPlanV1 {
                plan_id: id("longitudinal-plan"),
                claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                objective_digest: digest("objective"),
                dataset_digest: dataset.snapshot.dataset_digest,
                estimand_digest: digest("longitudinal-estimand"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("quality"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: (0..2)
                    .map(|index| CrossFoldPartitionV1 {
                        fold_id: id(&format!("fold-{index}")),
                        training_principals: vec![id(&format!("training-person-{index}"))],
                        training_episodes: vec![id(&format!("training-episode-{index}"))],
                        training_windows: vec![id(&format!("training-window-{index}"))],
                        holdout_principals: vec![id(&format!("holdout-person-{index}"))],
                        holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                        holdout_windows: vec![id(&format!("future-{index}"))],
                        model_digest: digest("fold-model"),
                        predictions_digest: digest("fold-predictions"),
                    })
                    .collect(),
                final_holdout_window_id: id("future-1"),
                final_holdout_digest: digest("final-holdout"),
            },
            roles.clone(),
            vec![id("dataset"), id("snapshot-0"), id("snapshot-1")],
            vec![id("future-0"), id("future-1")],
        );
        let context = ProductQualificationContextV1 {
            generator: signers.principals[0].clone(),
            evaluator: signers.principals[1].clone(),
            retention_receipt_digests: vec![digest("synthetic-retention")],
            unlearning_receipt_digest: digest("synthetic-unlearning"),
        };
        let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
        let mut timing = LongitudinalTimeEvidenceV1 {
            frozen_unix_micros: 10,
            windows: [(11, 19), (20, 50)]
                .into_iter()
                .enumerate()
                .map(|(index, (starts, ends))| ObservedFutureWindowV1 {
                    window_id: id(&format!("future-{index}")),
                    snapshot_id: id(&format!("snapshot-{index}")),
                    starts_unix_micros: starts,
                    ends_unix_micros: ends,
                    observation_count: if index == 1 { 1024 } else { 1 },
                    observed_source_cut: digest(&format!("source-cut-{index}")),
                })
                .collect(),
            observer: signers.sign(
                /*signer*/ 2,
                LearningEvidenceRoleV1::Observer,
                /*issued_at*/ 60,
                b"placeholder",
            ),
        };
        timing.observer = signers.sign(
            /*signer*/ 2,
            LearningEvidenceRoleV1::Observer,
            /*issued_at*/ 60,
            &future_window_signing_payload_v1(&bundle, &timing, /*minimum_window_micros*/ 5)
                .unwrap(),
        );
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: signers.sign(
                /*signer*/ 0,
                LearningEvidenceRoleV1::Generator,
                /*issued_at*/ 10,
                bundle.frozen_plan.plan_digest.as_array(),
            ),
            evaluator_bundle: signers.sign(
                /*signer*/ 1,
                LearningEvidenceRoleV1::Evaluator,
                /*issued_at*/ 60,
                &longitudinal_evaluation_signing_payload_v3(
                    &bundle, &roles, &timing, /*minimum_window_micros*/ 5,
                )
                .unwrap(),
            ),
        };
        let qualification = runner
            .qualify_and_persist(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::SystemLongitudinal {
                    timing: &timing,
                    minimum_window_micros: 5,
                },
                &signers.verifier,
                /*now*/ 70,
                &mut qualification_support::Sink(publication_namespace),
            )
            .unwrap();
        assert_eq!(
            qualification.decision.decision.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        Self {
            signers,
            dataset_request,
            dataset,
            ledger,
            qualification,
            bundle,
            roles,
            evidence,
            timing,
            policy: SelfEvolutionSelectionPolicyV1 {
                no_change_baseline_id: id("baseline"),
                no_change_baseline_digest: digest("baseline-bytes"),
                minimum_dataset_records: 1,
                minimum_future_window_micros: 5,
            },
            request: SelfEvolutionSelectionRequestV1 {
                selection_id: id("selection"),
                predecessor_id: id("baseline"),
                predecessor_generation: Generation::new(7).unwrap(),
                predecessor_artifact_digest: digest("baseline-bytes"),
                candidate_id: id("candidate"),
                candidate_generation: Generation::new(8).unwrap(),
                candidate_artifact_digest: digest("candidate-bytes"),
            },
        }
    }

    fn prepare(&self) -> Result<PreparedSelfEvolutionSelectionV1, SelfEvolutionSelectionError> {
        prepare_self_evolution_selection_v1(
            &self.policy,
            self.request.clone(),
            &self.qualification,
            self.bundle.clone(),
            self.roles.clone(),
            &self.evidence,
            &self.timing,
            &self.dataset,
            &self.ledger,
            &self.signers.verifier,
            /*now*/ 70,
        )
    }

    fn resign_evaluation(&mut self) {
        self.evidence.evaluator_bundle = self.signers.sign(
            /*signer*/ 1,
            LearningEvidenceRoleV1::Evaluator,
            /*issued_at*/ 60,
            &longitudinal_evaluation_signing_payload_v3(
                &self.bundle,
                &self.roles,
                &self.timing,
                self.policy.minimum_future_window_micros,
            )
            .unwrap(),
        );
    }

    fn resign_observations(&mut self) {
        self.timing.observer = self.signers.sign(
            /*signer*/ 2,
            LearningEvidenceRoleV1::Observer,
            /*issued_at*/ 60,
            &future_window_signing_payload_v1(
                &self.bundle,
                &self.timing,
                self.policy.minimum_future_window_micros,
            )
            .unwrap(),
        );
        self.resign_evaluation();
    }
}

#[test]
fn sealed_longitudinal_qualification_reaches_public_preparation_and_independent_selector() {
    let fixture = Fixture::new(digest("publication"));
    let prepared = fixture.prepare().unwrap();
    assert_eq!(
        prepared.receipt().qualification_evidence_digest,
        fixture.qualification.evidence_digest
    );
    assert_eq!(
        prepared.receipt().qualification_publication_digest,
        fixture.qualification.publication_digest
    );
    let selector = fixture.signers.sign(
        /*signer*/ 3,
        LearningEvidenceRoleV1::Selector,
        /*issued_at*/ 70,
        &selection_signing_payload_v2(prepared.receipt()).unwrap(),
    );
    let selected = admit_self_evolution_selection_v1(
        prepared,
        &selector,
        &fixture.signers.verifier,
        /*now*/ 70,
    )
    .unwrap();
    assert_eq!(
        selected.receipt().qualification_evidence_digest,
        fixture.qualification.evidence_digest
    );
    let regression = digest("observed-regression");
    let rollback = fixture.signers.sign(
        /*signer*/ 1,
        LearningEvidenceRoleV1::Evaluator,
        /*issued_at*/ 70,
        &rollback_signing_payload_v1(&selected, regression).unwrap(),
    );
    let rollback = admit_self_evolution_rollback_v1(
        &selected,
        regression,
        &rollback,
        &fixture.signers.verifier,
        /*now*/ 70,
    )
    .unwrap();
    assert_eq!(rollback.rollback_generation(), Generation::new(9).unwrap());
}

#[test]
fn valid_v3_resignatures_cannot_replace_published_metrics_or_time_policy() {
    let mut fixture = Fixture::new(digest("publication"));
    fixture.bundle.metrics[0].candidate.upper =
        FixedQ32::from_raw(fixture.bundle.metrics[0].candidate.upper.raw() + 1);
    fixture.resign_evaluation();
    let raw = crate::decide_with_signed_longitudinal_evidence_v3(
        fixture.bundle.clone(),
        fixture.roles.clone(),
        &fixture.evidence,
        &fixture.timing,
        fixture.policy.minimum_future_window_micros,
        &fixture.signers.verifier,
        /*now_unix_micros*/ 70,
    )
    .unwrap();
    assert_eq!(
        raw.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    assert!(matches!(
        fixture.prepare(),
        Err(SelfEvolutionSelectionError::QualificationRejected)
    ));

    let mut fixture = Fixture::new(digest("publication"));
    fixture.policy.minimum_future_window_micros = 6;
    fixture.resign_observations();
    let raw = crate::decide_with_signed_longitudinal_evidence_v3(
        fixture.bundle.clone(),
        fixture.roles.clone(),
        &fixture.evidence,
        &fixture.timing,
        fixture.policy.minimum_future_window_micros,
        &fixture.signers.verifier,
        /*now_unix_micros*/ 70,
    )
    .unwrap();
    assert_eq!(raw.decision, fixture.qualification.decision.decision);
    assert!(matches!(
        fixture.prepare(),
        Err(SelfEvolutionSelectionError::QualificationRejected)
    ));
}

#[test]
fn public_preparation_retains_observed_time_and_authoritative_dataset_checks() {
    let mut fixture = Fixture::new(digest("publication"));
    fixture.timing.windows[1].ends_unix_micros = 61;
    fixture.resign_observations();
    assert!(matches!(
        fixture.prepare(),
        Err(SelfEvolutionSelectionError::Evaluation(
            SignedEvaluationError::Timing("window_not_observed")
        ))
    ));
    let mut fixture = Fixture::new(digest("publication"));
    fixture.policy.minimum_dataset_records = 2;
    assert!(matches!(
        fixture.prepare(),
        Err(SelfEvolutionSelectionError::DatasetTooSmall)
    ));
    fixture.policy.minimum_dataset_records = 1;
    fixture.dataset_request.source_record_digests = vec![digest("absent-ledger-record")];
    fixture.dataset =
        freeze_dataset_receipt_v3(fixture.dataset_request.clone(), /*now*/ 70).unwrap();
    assert!(matches!(
        fixture.prepare(),
        Err(SelfEvolutionSelectionError::Dataset(
            DatasetReceiptError::LedgerSourceSetMismatch
        ))
    ));
}

#[test]
fn selector_signature_commits_the_exact_qualification_publication() {
    let first = Fixture::new(digest("first-publication"));
    let second = Fixture::new(digest("second-publication"));
    assert_eq!(first.qualification.decision, second.qualification.decision);
    let first_prepared = first.prepare().unwrap();
    let second_prepared = second.prepare().unwrap();
    let first_payload = selection_signing_payload_v2(first_prepared.receipt()).unwrap();
    let second_payload = selection_signing_payload_v2(second_prepared.receipt()).unwrap();
    let wrong_use = first.signers.sign(
        /*signer*/ 3,
        LearningEvidenceRoleV1::Selector,
        /*issued_at*/ 70,
        &first_payload,
    );
    assert!(matches!(
        admit_self_evolution_selection_v1(
            second_prepared,
            &wrong_use,
            &second.signers.verifier,
            /*now*/ 70
        ),
        Err(SelfEvolutionSelectionError::Evidence(_))
    ));
    assert_ne!(first_payload, second_payload);
    let correct_use = second.signers.sign(
        /*signer*/ 3,
        LearningEvidenceRoleV1::Selector,
        /*issued_at*/ 70,
        &second_payload,
    );
    assert!(
        admit_self_evolution_selection_v1(
            second.prepare().unwrap(),
            &correct_use,
            &second.signers.verifier,
            /*now*/ 70
        )
        .is_ok()
    );
}
