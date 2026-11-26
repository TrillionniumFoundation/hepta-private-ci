//! Controlled composition through the public dataset/evaluation/selection owners.
//! The declared intervals, source windows and ephemeral signers are fixtures,
//! not independent future-task efficacy or a production installation receipt.
use super::*;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger as ledger;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

enum EvidenceLifetime {
    Live,
    AlreadyExpired,
    ExpiresDuringRead,
}

fn selected_fixture(lifetime: EvidenceLifetime) -> (Fixture, VerifiedSelfEvolutionSelectionV1) {
    let wall_now = current_unix_micros().unwrap();
    let now = match lifetime {
        EvidenceLifetime::AlreadyExpired => wall_now - 10_000_000,
        EvidenceLifetime::Live | EvidenceLifetime::ExpiresDuringRead => wall_now,
    };
    let base = now - 1_000_000;
    let expires_at = match lifetime {
        EvidenceLifetime::Live => now + 60_000_000,
        EvidenceLifetime::AlreadyExpired => now + 1_000_000,
        EvidenceLifetime::ExpiresDuringRead => now + 5_000_000,
    };
    let role_names = ["generator", "evaluator", "observer", "selector"];
    let role_kinds = [
        ledger::LearningEvidenceRoleV1::Generator,
        ledger::LearningEvidenceRoleV1::Evaluator,
        ledger::LearningEvidenceRoleV1::Observer,
        ledger::LearningEvidenceRoleV1::Selector,
    ];
    let keys = [31_u8, 47, 53, 61].map(|seed| SigningKey::from_bytes(&[seed; 32]));
    let scope = hash("controlled-selection-scope");
    let objective = hash("read-ranking-task");
    let principals = std::array::from_fn::<_, 4, _>(|index| ledger::AuthenticatedPrincipalV1 {
        principal_id: id(role_names[index]),
        credential_chain_digest: hash(&format!("{}-credential", role_names[index])),
        signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 11,
        authenticated_at: base,
        expires_at,
    });
    let verifier = ledger::LearningEvidenceVerifierV1::new(ledger::LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: objective,
        authority_epoch: 11,
        signers: (0..4)
            .map(|index| ledger::TrustedLearningSignerV1 {
                principal: principals[index].clone(),
                controller_id: id(&format!("controller-{}", role_names[index])),
                verifying_key: keys[index].verifying_key().to_bytes(),
                roles: vec![role_kinds[index]],
                revoked_at: None,
            })
            .collect(),
    })
    .unwrap();
    let sign = |index: usize, payload: &[u8], issued_at| {
        let mut evidence = ledger::SignedLearningEvidenceV1 {
            evidence_id: id(&format!("{}-evidence", role_names[index])),
            principal_id: principals[index].principal_id.clone(),
            role: role_kinds[index],
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: objective,
            authority_epoch: 11,
            issued_at,
            expires_at,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    };
    let mut learning = ledger::LearningLedger::new();
    learning
        .append(ledger::LedgerEvent::Decision(ledger::EpisodeDecision {
            record_id: id("controlled-source"),
            episode_id: id("controlled-episode"),
            objective_digest: objective,
            policy_id: id("controlled-policy"),
            candidate_ids: vec![id("abstain"), id("read-ranker")],
            selected_candidate_id: id("read-ranker"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: ledger::CandidateSetCompleteness::Complete,
            support_digest: hash("controlled-ledger-support"),
        }))
        .unwrap();
    let ledger_snapshot = learning.snapshot();
    let dataset = ledger::freeze_dataset_receipt_v3(
        ledger::DatasetFreezeRequestV1 {
            snapshot_id: id("snapshot-1"),
            producer: principals[0].clone(),
            ledger_head_digest: ledger_snapshot.head_digest,
            objective_digest: objective,
            eligible_frontier: 1,
            outcome_watermark: now,
            correction_cut_digest: hash("correction-cut"),
            revocation_cut_digest: hash("revocation-cut"),
            inclusion_policy_digest: hash("inclusion-policy"),
            source_record_digests: vec![ledger_snapshot.records()[0].event_digest],
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        now,
    )
    .unwrap();
    let parent = ArtifactManifest {
        artifact_id: id("baseline-ranker"),
        kind: ArtifactKind::Policy,
        generation: Generation::new(2).unwrap(),
        predecessor_id: None,
        content_digest: hash("controlled-parent-bytes"),
        objective_digest: objective,
        support_digest: dataset.snapshot.dataset_digest,
        producer_id: id("fixture-trainer"),
        compatibility_digest: hash("ranker-consumer-v1"),
        encoded_size_bytes: 1,
    };
    let original = [item("one"), item("two")];
    let fixture = fixture_with_lineage(
        &original,
        &[0, 10],
        FixtureLineage::Candidate {
            parent: Box::new(parent.clone()),
            dataset: dataset.snapshot.dataset_digest,
            generation: parent.generation.next().unwrap(),
        },
    );
    let roles = vec![eval::MetricRoleContractV2 {
        metric_id: id("task-utility"),
        role: eval::MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let plan = eval::freeze_cross_fold_plan_v2(
        eval::CrossFoldPlanV1 {
            plan_id: id("controlled-plan"),
            claim_scope: eval::EvaluationClaimScopeV1::SystemLongitudinal,
            candidate_id: fixture.selected.manifest.artifact_id.clone(),
            baseline_id: parent.artifact_id.clone(),
            objective_digest: objective,
            dataset_digest: dataset.snapshot.dataset_digest,
            estimand_digest: hash("controlled-estimand"),
            metric_contracts: vec![eval::MetricContractV1 {
                metric_id: id("task-utility"),
                direction: eval::EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(75)),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: (1..=2)
                .map(|index| eval::CrossFoldPartitionV1 {
                    fold_id: id(&format!("fold-{index}")),
                    training_principals: vec![id(&format!("training-principal-{index}"))],
                    training_episodes: vec![id(&format!("training-episode-{index}"))],
                    training_windows: vec![id(&format!("training-window-{index}"))],
                    holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                    holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                    holdout_windows: vec![id(&format!("w-{index}"))],
                    model_digest: hash(&format!("model-{index}")),
                    predictions_digest: hash(&format!("predictions-{index}")),
                })
                .collect(),
            final_holdout_window_id: id("w-2"),
            final_holdout_digest: hash("controlled-final-holdout"),
        },
        roles.clone(),
    )
    .unwrap();
    let holdout = eval::FinalHoldoutRegistry::new().consume(&plan).unwrap();
    let bundle = eval::IndependentEvaluationBundleV1 {
        evaluation_id: id("controlled-evaluation"),
        candidate_id: fixture.selected.manifest.artifact_id.clone(),
        baseline_id: parent.artifact_id.clone(),
        claim_scope: eval::EvaluationClaimScopeV1::SystemLongitudinal,
        generator: principals[0].clone(),
        evaluator: principals[1].clone(),
        frozen_plan: plan,
        holdout_use: holdout,
        objective_digest: objective,
        dataset_digest: dataset.snapshot.dataset_digest,
        estimand_digest: hash("controlled-estimand"),
        estimate_receipt_digest: hash("controlled-estimate"),
        support_audit_digest: hash("controlled-support-audit"),
        confidence_receipt_digest: hash("controlled-confidence"),
        retention_receipt_digests: vec![hash("controlled-retention")],
        unlearning_receipt_digest: hash("controlled-unlearning"),
        snapshot_ids: vec![id("snapshot-1"), id("snapshot-2"), id("snapshot-3")],
        future_window_ids: vec![id("w-1"), id("w-2")],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        metrics: vec![eval::MetricGateV1 {
            metric_id: id("task-utility"),
            direction: eval::EvaluationDirectionV1::Maximize,
            candidate: eval::EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(80),
                upper: FixedQ32::from_raw(90),
            },
            baseline: eval::EvaluationIntervalV1 {
                lower: FixedQ32::from_raw(50),
                upper: FixedQ32::from_raw(70),
            },
            safety_floor: Some(FixedQ32::from_raw(75)),
            support_digest: hash("controlled-metric-support"),
        }],
    };
    let mut timing = eval::LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: base + 10,
        windows: (1..=2)
            .map(|index| eval::ObservedFutureWindowV1 {
                window_id: id(&format!("w-{index}")),
                snapshot_id: id(&format!("snapshot-{}", index + 1)),
                starts_unix_micros: base + 11 + (index - 1) * 15,
                ends_unix_micros: base + 25 + (index - 1) * 15,
                observation_count: 400,
                observed_source_cut: hash(&format!("controlled-cut-{index}")),
            })
            .collect(),
        observer: sign(2, b"placeholder", base + 45),
    };
    timing.observer = sign(
        2,
        &eval::future_window_signing_payload_v1(&bundle, &timing, 10).unwrap(),
        base + 45,
    );
    let evaluation = eval::SignedEvaluationEvidenceV1 {
        generator_plan: sign(0, bundle.frozen_plan.plan_digest.as_array(), base + 10),
        evaluator_bundle: sign(
            1,
            &eval::longitudinal_evaluation_signing_payload_v3(&bundle, &roles, &timing, 10)
                .unwrap(),
            base + 50,
        ),
    };
    let prepared = eval::prepare_self_evolution_selection_v1(
        &eval::SelfEvolutionSelectionPolicyV1 {
            no_change_baseline_id: parent.artifact_id.clone(),
            no_change_baseline_digest: parent.content_digest,
            minimum_dataset_records: 1,
            minimum_future_window_micros: 10,
        },
        eval::SelfEvolutionSelectionRequestV1 {
            selection_id: id("controlled-selection"),
            predecessor_id: parent.artifact_id,
            predecessor_generation: parent.generation,
            predecessor_artifact_digest: parent.content_digest,
            candidate_id: fixture.selected.manifest.artifact_id.clone(),
            candidate_generation: fixture.selected.manifest.generation,
            candidate_artifact_digest: fixture.selected.manifest.content_digest,
        },
        bundle,
        roles,
        &evaluation,
        &timing,
        &dataset,
        &ledger_snapshot,
        &verifier,
        now,
    )
    .unwrap();
    let selector = sign(
        3,
        &eval::selection_signing_payload_v1(prepared.receipt()).unwrap(),
        now,
    );
    let selected =
        eval::admit_self_evolution_selection_v1(prepared, &selector, &verifier, now).unwrap();
    (fixture, selected)
}

fn evaluated_load(
    fixture: &Fixture,
    selection: &VerifiedSelfEvolutionSelectionV1,
) -> Result<PinnedCognitiveRanker, String> {
    PinnedCognitiveRanker::load_evaluated(
        owner(),
        fixture.selected.manifest.generation.get(),
        File::open(fixture.directory.path().join("snapshot")).unwrap(),
        File::open(fixture.directory.path().join("payload")).unwrap(),
        fixture.selected.clone(),
        fixture.model_pin.clone(),
        fixture.view.clone(),
        selection,
    )
}

#[test]
fn evaluated_selection_model_lineage_is_independent_of_launch_epoch() {
    let (fixture, selection) = selected_fixture(EvidenceLifetime::Live);
    let actual_launch_epoch = 19;
    let ranker = PinnedCognitiveRanker::load_evaluated(
        owner(),
        actual_launch_epoch,
        File::open(fixture.directory.path().join("snapshot")).unwrap(),
        File::open(fixture.directory.path().join("payload")).unwrap(),
        fixture.selected.clone(),
        fixture.model_pin.clone(),
        fixture.view.clone(),
        &selection,
    )
    .unwrap();
    assert_ne!(actual_launch_epoch, fixture.model_pin.generation.get());
    let mut records = [item("one"), item("two")];
    ranker
        .rank(&owner(), actual_launch_epoch, "lemon", &mut records)
        .unwrap();
    assert_eq!(records, [item("two"), item("one")]);
    let original = records.clone();
    assert!(
        ranker
            .rank(
                &owner(),
                fixture.model_pin.generation.get(),
                "lemon",
                &mut records
            )
            .is_err()
    );
    assert_eq!(
        records, original,
        "model generation cannot replace the launch identity fence"
    );
}

#[test]
fn public_independent_selection_reaches_the_actual_ranker_without_receipt_casts() {
    let (fixture, selection) = selected_fixture(EvidenceLifetime::Live);
    let ranker = evaluated_load(&fixture, &selection).unwrap();
    let mut ranked = vec![item("one"), item("two")];
    ranker
        .rank(
            &owner(),
            fixture.selected.manifest.generation.get(),
            "lemon",
            &mut ranked,
        )
        .unwrap();
    assert_eq!(ranked, vec![item("two"), item("one")]);
}

#[test]
fn valid_selection_cannot_bind_to_a_different_registry_parent_digest_or_generation() {
    let (fixture, selection) = selected_fixture(EvidenceLifetime::Live);
    for changed_parent in ["digest", "generation"] {
        let mut parent = fixture
            .registry
            .manifest(&selection.receipt().predecessor_id)
            .unwrap()
            .clone();
        match changed_parent {
            "digest" => parent.content_digest = hash("different-native-owner-parent"),
            "generation" => parent.generation = Generation::new(1).unwrap(),
            _ => unreachable!(),
        }
        let transplant = fixture_with_lineage(
            &[item("one"), item("two")],
            &[0, 10],
            FixtureLineage::Candidate {
                parent: Box::new(parent),
                dataset: fixture.selected.manifest.support_digest,
                generation: fixture.selected.manifest.generation,
            },
        );
        assert_eq!(transplant.selected.manifest, fixture.selected.manifest);
        let error = evaluated_load(&transplant, &selection)
            .err()
            .expect("parent substitution accepted");
        assert!(error.contains("registry predecessor differs"), "{error}");
    }
}

#[test]
fn a_past_verified_selection_cannot_be_loaded_after_its_original_window() {
    let (fixture, selection) = selected_fixture(EvidenceLifetime::AlreadyExpired);
    assert!(evaluated_load(&fixture, &selection).is_err());
}

#[test]
fn late_current_acquisition_leaves_the_items_unchanged_and_the_cache_closed() {
    let (fixture, selection) = selected_fixture(EvidenceLifetime::ExpiresDuringRead);
    let ranker = evaluated_load(&fixture, &selection).unwrap();
    fixture
        .view
        .2
        .store(6_000_000, std::sync::atomic::Ordering::SeqCst);
    let original = vec![item("one"), item("two")];
    let mut ranked = original.clone();
    assert!(
        ranker
            .rank(
                &owner(),
                fixture.selected.manifest.generation.get(),
                "lemon",
                &mut ranked
            )
            .is_err()
    );
    assert_eq!(ranked, original);
    fixture.view.2.store(0, std::sync::atomic::Ordering::SeqCst);
    assert!(
        ranker
            .rank(
                &owner(),
                fixture.selected.manifest.generation.get(),
                "lemon",
                &mut ranked
            )
            .is_err()
    );
    assert_eq!(ranked, original);
}
