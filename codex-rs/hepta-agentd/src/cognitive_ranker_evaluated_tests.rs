//! Virtual-clock, fixture-key protocol E2E. These are not longitudinal product
//! efficacy observations. No opaque admission value is fabricated in this test.

use super::*;
use codex_hepta_bellman_operator::TabularOperatorArtifactV1;
use codex_hepta_bellman_operator::TabularOperatorPlanV1;
use codex_hepta_bellman_operator::TabularOperatorSampleV1;
use codex_hepta_bellman_operator::TabularPayloadPinV2;
use codex_hepta_bellman_operator::encode_tabular_payload_v1;
use codex_hepta_bellman_operator::fit_tabular_operator_verified_v3;
use codex_hepta_bellman_operator::tabular_training_signing_payload_v2;
use codex_hepta_bellman_operator::verify_tabular_operator_plan_v3;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::ArtifactEvent;
use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
use codex_hepta_learning_artifacts::StateChange;
use codex_hepta_learning_artifacts::write_candidate_payload;
use codex_hepta_learning_artifacts::write_registry_snapshot;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::OpenOptions;
use std::path::PathBuf;

fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn owner() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap()
}
fn item(name: &str) -> CognitiveContextItem {
    CognitiveContextItem {
        memory_id: name.to_string(),
        revision: 1,
        content: format!("lemon {name}"),
        content_sha256: hash(name).to_string(),
    }
}
struct View(Mutex<Option<(PathBuf, RegistrySnapshotReceipt, Digest32)>>);
impl CurrentCognitiveRegistry for View {
    fn current(&self) -> Result<VerifiedCurrentRegistryViewV1, String> {
        let view = self.0.lock().unwrap();
        let (path, receipt, predecessor) = view.as_ref().ok_or("missing current witness")?;
        verified_fixture_current_view(
            File::open(path).map_err(|error| error.to_string())?,
            *receipt,
            *predecessor,
        )
    }
}

struct LearningFixture {
    owner: LedgerWriter,
    receipt: DatasetSnapshotReceiptV3,
    freeze: SignedLearningEvidenceV1,
    trust: LearningEvidenceTrustV1,
    _directory: tempfile::TempDir,
}

impl LearningFixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let trust = LearningEvidenceTrustV1 {
            scope_digest: hash("evaluated-shadow-scope"),
            objective_digest: hash("read-ranking-task"),
            authority_epoch: 7,
            signers: [
                LearningEvidenceRoleV1::Generator,
                LearningEvidenceRoleV1::Observer,
                LearningEvidenceRoleV1::Evaluator,
                LearningEvidenceRoleV1::Selector,
            ]
            .into_iter()
            .enumerate()
            .map(|(index, role)| {
                let name = ["generator", "observer", "evaluator", "selector"][index];
                let key = SigningKey::from_bytes(&[index as u8 + 31; 32]);
                TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: id(name),
                        credential_chain_digest: hash(name),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: hash("evaluated-shadow-scope"),
                        authority_epoch: 7,
                        authenticated_at: 1,
                        expires_at: 200,
                    },
                    controller_id: id(&format!("independent-{name}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![role],
                    revoked_at: None,
                }
            })
            .collect(),
        };
        let root_key = SigningKey::from_bytes(&[97; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("test-root"),
            scope_digest: trust.scope_digest,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 200,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("test-trust"),
                generation: 1,
                effective_at: 1,
                trust: trust.clone(),
            },
            root_id: root.root_id.clone(),
            issued_at: 1,
            expires_at: 150,
            signature: [0; 64],
        };
        distribution.signature = root_key
            .sign(&distribution.signing_bytes().unwrap())
            .to_bytes();
        let activated = activate_learning_trust(&root, distribution, None, 2).unwrap();
        let file = |name: &str| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(directory.path().join(name))
                .unwrap()
        };
        let ledger = DurableLedger::create(file("ledger"), hash("ledger-binding"), 64).unwrap();
        let witness = LedgerWitnessStore::create(file("witness"), hash("ledger-binding")).unwrap();
        let dir = File::open(directory.path()).unwrap();
        let mut owner = LedgerWriter::from_durable(ledger, witness, activated, &dir, &dir).unwrap();
        let candidates = vec![id("read"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: id("training-decision"),
            episode_id: id("training-episode"),
            run_snapshot_digest: hash("training-run"),
            objective_digest: trust.objective_digest,
            policy_digest: hash("training-policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("read"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("set"),
                state_digest: hash("state"),
                generator_id: id("generator"),
                generator_code_digest: hash("generator-code"),
                grammar_digest: hash("grammar"),
                hard_filter_digest: hash("filter"),
                truncation_digest: hash("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: hash("training-decision-support"),
        };
        let signature = Self::sign(
            owner.verifier(),
            0,
            &decision_signing_payload_v2(&decision).unwrap(),
            2,
        );
        let appended = owner
            .append_decision(Digest32::ZERO, decision, &signature, 2)
            .unwrap();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id("training-outcome-record"),
            outcome_id: id("training-outcome"),
            episode_id: id("training-episode"),
            observer: trust.signers[1].principal.clone(),
            observed_at: Some(3),
            value: Some(FixedQ32::from_raw(20)),
            unit_profile_digest: hash("utility-q32"),
            support_digest: hash("outcome-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: 4,
                expected_delay_profile_digest: hash("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(4),
            },
        };
        let signature = Self::sign(
            owner.verifier(),
            1,
            &outcome_signing_payload_v2(&outcome),
            4,
        );
        owner
            .append_outcome(appended.chain_digest, outcome, &signature, 4)
            .unwrap();
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("rank-training-dataset"),
            objective_digest: trust.objective_digest,
            inclusion_policy_digest: hash("fixture-training-only"),
        };
        let freeze = Self::sign(
            owner.verifier(),
            2,
            &dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap(),
            5,
        );
        let receipt = owner.freeze_dataset(plan, &freeze, 5).unwrap();
        Self {
            owner,
            receipt,
            freeze,
            trust,
            _directory: directory,
        }
    }

    fn sign(
        verifier: &LearningEvidenceVerifierV1,
        index: usize,
        payload: &[u8],
        issued: u64,
    ) -> SignedLearningEvidenceV1 {
        let name = ["generator", "observer", "evaluator", "selector"][index];
        let role = [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Selector,
        ][index];
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("{name}-{issued}")),
            principal_id: id(name),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: verifier.authority_epoch(),
            issued_at: issued,
            expires_at: 100,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[index as u8 + 31; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    fn fit(&self, items: &[CognitiveContextItem], generation: u64) -> TabularOperatorArtifactV1 {
        let sensor = cognitive_sensor_id("lemon").unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(self.receipt.snapshot.source_record_digests.len(), 2);
        let actions: Vec<_> = items
            .iter()
            .map(|item| cognitive_action_id(item).unwrap())
            .collect();
        let plan = TabularOperatorPlanV1 {
            artifact_id: id(&format!("evaluated-ranker-{generation}")),
            producer_id: id("generator"),
            generation: Generation::new(generation).unwrap(),
            objective_digest: self.trust.objective_digest,
            dataset_digest: self.receipt.snapshot.dataset_digest,
            sensor_core_digest: hash("exact-query-revision-v1"),
            training_profile_digest: hash("signed-tabular-v3"),
            minimum_samples_per_cell: 1,
            sensor_ids: vec![sensor.clone()],
            action_ids: actions.clone(),
            samples: self
                .receipt
                .snapshot
                .source_record_digests
                .iter()
                .enumerate()
                .map(|(index, evidence)| TabularOperatorSampleV1 {
                    sample_id: id(&format!("row-{index}")),
                    sensor_id: sensor.clone(),
                    action_id: actions[index].clone(),
                    target: FixedQ32::from_raw(if index as u64 == generation - 1 {
                        20
                    } else {
                        0
                    }),
                    evidence_digest: *evidence,
                })
                .collect(),
        };
        let payload =
            tabular_training_signing_payload_v2(&plan, &self.receipt, &self.owner).unwrap();
        let rows = Self::sign(self.owner.verifier(), 1, &payload, 6);
        let verified = verify_tabular_operator_plan_v3(
            plan,
            &self.receipt,
            &self.owner,
            &self.freeze,
            &rows,
            6,
        )
        .unwrap();
        fit_tabular_operator_verified_v3(verified, 6).unwrap()
    }

    fn selection(
        &self,
        predecessor: &ArtifactManifest,
        candidate: &ArtifactManifest,
    ) -> VerifiedSelfEvolutionSelectionV1 {
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let frozen = freeze_cross_fold_plan_v2(
            CrossFoldPlanV1 {
                plan_id: id("read-ranking-evaluation"),
                claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
                candidate_id: candidate.artifact_id.clone(),
                baseline_id: predecessor.artifact_id.clone(),
                objective_digest: self.trust.objective_digest,
                dataset_digest: self.receipt.snapshot.dataset_digest,
                estimand_digest: hash("fixture-read-utility"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("task-utility"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: Some(FixedQ32::from_raw(75)),
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: (1..=2)
                    .map(|index| CrossFoldPartitionV1 {
                        fold_id: id(&format!("fold-{index}")),
                        training_principals: vec![id(&format!("train-principal-{index}"))],
                        training_episodes: vec![id(&format!("train-episode-{index}"))],
                        training_windows: vec![id(&format!("train-window-{index}"))],
                        holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                        holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                        holdout_windows: vec![id(&format!("future-{index}"))],
                        model_digest: candidate.content_digest,
                        predictions_digest: hash(&format!("fixed-predictions-{index}")),
                    })
                    .collect(),
                final_holdout_window_id: id("future-2"),
                final_holdout_digest: hash("fixed-holdout"),
            },
            roles.clone(),
        )
        .unwrap();
        let holdout_use = FinalHoldoutRegistry::new().consume(&frozen).unwrap();
        let bundle = IndependentEvaluationBundleV1 {
            evaluation_id: id("read-evaluation"),
            candidate_id: candidate.artifact_id.clone(),
            baseline_id: predecessor.artifact_id.clone(),
            claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
            generator: self.trust.signers[0].principal.clone(),
            evaluator: self.trust.signers[2].principal.clone(),
            frozen_plan: frozen,
            holdout_use,
            objective_digest: self.trust.objective_digest,
            dataset_digest: self.receipt.snapshot.dataset_digest,
            estimand_digest: hash("fixture-read-utility"),
            estimate_receipt_digest: hash("fixture-estimate"),
            support_audit_digest: hash("fixture-support"),
            confidence_receipt_digest: hash("fixture-confidence"),
            retention_receipt_digests: vec![hash("fixture-retention")],
            unlearning_receipt_digest: hash("fixture-unlearning"),
            snapshot_ids: vec![id("snapshot-0"), id("snapshot-1"), id("snapshot-2")],
            future_window_ids: vec![id("future-1"), id("future-2")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("task-utility"),
                direction: EvaluationDirectionV1::Maximize,
                candidate: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(80),
                    upper: FixedQ32::from_raw(90),
                },
                baseline: EvaluationIntervalV1 {
                    lower: FixedQ32::from_raw(50),
                    upper: FixedQ32::from_raw(70),
                },
                safety_floor: Some(FixedQ32::from_raw(75)),
                support_digest: hash("fixture-metric-support"),
            }],
        };
        let verifier = self.owner.verifier();
        let mut timing = LongitudinalTimeEvidenceV1 {
            frozen_unix_micros: 10,
            windows: (1..=2)
                .map(|index| ObservedFutureWindowV1 {
                    window_id: id(&format!("future-{index}")),
                    snapshot_id: id(&format!("snapshot-{index}")),
                    starts_unix_micros: if index == 1 { 11 } else { 26 },
                    ends_unix_micros: if index == 1 { 25 } else { 40 },
                    observation_count: 400,
                    observed_source_cut: hash(&format!("fixture-cut-{index}")),
                })
                .collect(),
            observer: Self::sign(verifier, 1, b"unsigned-placeholder", 45),
        };
        timing.observer = Self::sign(
            verifier,
            1,
            &future_window_signing_payload_v1(&bundle, &timing, 10).unwrap(),
            45,
        );
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: Self::sign(verifier, 0, bundle.frozen_plan.plan_digest.as_array(), 10),
            evaluator_bundle: Self::sign(
                verifier,
                2,
                &longitudinal_evaluation_signing_payload_v3(&bundle, &roles, &timing, 10).unwrap(),
                50,
            ),
        };
        let prepared = prepare_self_evolution_selection_v1(
            &SelfEvolutionSelectionPolicyV1 {
                no_change_baseline_id: predecessor.artifact_id.clone(),
                no_change_baseline_digest: predecessor.content_digest,
                minimum_dataset_records: 1,
                minimum_future_window_micros: 10,
            },
            SelfEvolutionSelectionRequestV1 {
                selection_id: id("read-selection"),
                predecessor_id: predecessor.artifact_id.clone(),
                predecessor_generation: predecessor.generation,
                predecessor_artifact_digest: predecessor.content_digest,
                candidate_id: candidate.artifact_id.clone(),
                candidate_generation: candidate.generation,
                candidate_artifact_digest: candidate.content_digest,
            },
            bundle,
            roles,
            &evidence,
            &timing,
            &self.receipt,
            &self.owner.snapshot().unwrap(),
            verifier,
            50,
        )
        .expect("actual signed longitudinal preparation");
        let selector = Self::sign(
            verifier,
            3,
            &selection_signing_payload_v1(prepared.receipt()).unwrap(),
            50,
        );
        admit_self_evolution_selection_v1(prepared, &selector, verifier, 50).unwrap()
    }
}

struct Admission(Mutex<RankerAdmissionSnapshotV2>);
impl CurrentRankerAdmission for Admission {
    fn current(&self) -> Result<RankerAdmissionSnapshotV2, String> {
        Ok(self.0.lock().unwrap().clone())
    }
}

struct EvaluatedFixture {
    directory: tempfile::TempDir,
    learning: LearningFixture,
    registry: ArtifactRegistry,
    view: Arc<View>,
    admission: Arc<Admission>,
    selection: VerifiedSelfEvolutionSelectionV1,
    specs: [PinnedCandidateSpec; 2],
    pins: [TabularPayloadPinV2; 2],
}

impl EvaluatedFixture {
    fn new(items: &[CognitiveContextItem]) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let learning = LearningFixture::new();
        let models = [learning.fit(items, 1), learning.fit(items, 2)];
        let mut registry = ArtifactRegistry::new();
        let runtime = hash("ranker-consumer-v2");
        let manifests: [ArtifactManifest; 2] = std::array::from_fn(|index| {
            let model = &models[index];
            let bytes = encode_tabular_payload_v1(model).unwrap();
            let manifest = ArtifactManifest {
                artifact_id: model.artifact_id.clone(),
                kind: ArtifactKind::Policy,
                generation: model.generation,
                predecessor_id: (index == 1).then(|| models[0].artifact_id.clone()),
                content_digest: Digest32::of_bytes(&bytes),
                objective_digest: model.objective_digest,
                support_digest: model.dataset_digest,
                producer_id: model.producer_id.clone(),
                compatibility_digest: runtime,
                encoded_size_bytes: bytes.len() as u64,
            };
            registry
                .append(ArtifactEvent::Register {
                    event_id: id(&format!("register-{index}")),
                    manifest: manifest.clone(),
                })
                .unwrap();
            write_candidate_payload(
                CreateOnlyArtifactFile::create(directory.path().join(format!("payload-{index}")))
                    .unwrap(),
                &registry,
                &manifest.artifact_id,
                &bytes,
            )
            .unwrap();
            manifest
        });
        let snapshot = directory.path().join("snapshot");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot).unwrap(),
            &registry,
            hash("fixture-host-binding"),
        )
        .unwrap();
        let view = Arc::new(View(Mutex::new(Some((snapshot, receipt, Digest32::ZERO)))));
        let admission = Arc::new(Admission(Mutex::new(RankerAdmissionSnapshotV2 {
            learning_verifier: learning.owner.verifier().clone(),
            artifact_trust_digest: view.current().unwrap().trust_digest(),
            runtime_profile_digest: runtime,
            now_unix_micros: 50,
        })));
        let selection = learning.selection(&manifests[0], &manifests[1]);
        let pins = std::array::from_fn(|index| TabularPayloadPinV2 {
            artifact_id: models[index].artifact_id.clone(),
            producer_id: models[index].producer_id.clone(),
            artifact_schema_version: 1,
            payload_schema_version: 1,
            payload_digest: manifests[index].content_digest,
            artifact_digest: models[index].artifact_digest,
            objective_digest: models[index].objective_digest,
            dataset_digest: models[index].dataset_digest,
            sensor_core_digest: models[index].sensor_core_digest,
            training_profile_digest: models[index].training_profile_digest,
            runtime_profile_digest: runtime,
            trust_digest: learning.owner.verifier().trust_digest(),
            registry_head_digest: receipt.head_digest,
            authority_epoch: 7,
            generation: models[index].generation,
        });
        let specs = manifests.map(|manifest| PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest,
        });
        Self {
            directory,
            learning,
            registry,
            view,
            admission,
            selection,
            specs,
            pins,
        }
    }
    fn load(&self) -> Result<PinnedCognitiveRanker, String> {
        self.load_pin(self.pins[1].clone())
    }
    fn load_pin(&self, pin: TabularPayloadPinV2) -> Result<PinnedCognitiveRanker, String> {
        PinnedCognitiveRanker::load_evaluated(
            owner(),
            2,
            File::open(self.directory.path().join("snapshot")).unwrap(),
            File::open(self.directory.path().join("payload-1")).unwrap(),
            self.specs[1].clone(),
            pin,
            self.view.clone(),
            &self.selection,
            self.admission.clone(),
        )
    }
    fn revoke_candidate(&mut self) {
        let predecessor = self.registry.snapshot().head_digest;
        self.registry
            .append(ArtifactEvent::Revoke(StateChange {
                event_id: id("revoke-evaluated-candidate"),
                artifact_id: self.specs[1].manifest.artifact_id.clone(),
                evaluator_id: id("artifact-evaluator"),
                reason_digest: hash("withdrawn"),
            }))
            .unwrap();
        let path = self.directory.path().join("revoked");
        let receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&path).unwrap(),
            &self.registry,
            hash("fixture-host-binding"),
        )
        .unwrap();
        *self.view.0.lock().unwrap() = Some((path, receipt, predecessor));
    }
}

#[test]
fn evaluated_load_uses_real_owner_training_selection_revocation_and_rollback() {
    let original = vec![item("one"), item("two")];
    let mut fixture = EvaluatedFixture::new(&original);
    let ranker = fixture.load().unwrap();
    let mut ranked = original.clone();
    assert!(
        ranker
            .rank(&owner(), 2, "lemon", &mut ranked)
            .unwrap()
            .applied
    );
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
    assert!(!fixture.selection.receipt().authority.grants_any());
    fixture.revoke_candidate();
    let before = ranked.clone();
    assert!(ranker.rank(&owner(), 2, "lemon", &mut ranked).is_err());
    assert_eq!(ranked, before);
    let regression = hash("independent-regression-observation");
    let payload = rollback_signing_payload_v1(&fixture.selection, regression).unwrap();
    let evidence = LearningFixture::sign(fixture.learning.owner.verifier(), 2, &payload, 50);
    let rollback = admit_self_evolution_rollback_v1(
        &fixture.selection,
        regression,
        &evidence,
        fixture.learning.owner.verifier(),
        50,
    )
    .unwrap();
    let restored = PinnedCognitiveRanker::load_evaluated_rollback(
        owner(),
        3,
        File::open(fixture.directory.path().join("snapshot")).unwrap(),
        File::open(fixture.directory.path().join("payload-0")).unwrap(),
        fixture.specs[0].clone(),
        fixture.pins[0].clone(),
        fixture.view.clone(),
        &rollback,
        fixture.admission.clone(),
    )
    .unwrap();
    let mut items = original.clone();
    restored.rank(&owner(), 3, "lemon", &mut items).unwrap();
    assert_eq!(items, original);
    assert!(restored.rank(&owner(), 1, "lemon", &mut items).is_err());
}

#[test]
fn evaluated_load_rejects_each_full_pin_substitution() {
    let original = vec![item("one"), item("two")];
    let fixture = EvaluatedFixture::new(&original);
    for mutation in 0..8 {
        let mut pin = fixture.pins[1].clone();
        match mutation {
            0 => pin.artifact_id = id("imposter"),
            1 => pin.producer_id = id("imposter"),
            2 => pin.runtime_profile_digest = hash("other-runtime"),
            3 => pin.trust_digest = hash("other-trust"),
            4 => pin.registry_head_digest = hash("other-head"),
            5 => pin.authority_epoch += 1,
            6 => pin.payload_schema_version += 1,
            7 => pin.generation = Generation::new(3).unwrap(),
            _ => unreachable!(),
        }
        assert!(fixture.load_pin(pin).is_err(), "pin mutation {mutation}");
    }
}

#[test]
fn evaluated_rank_rechecks_expiry_epoch_revocation_runtime_and_clock_without_resurrection() {
    for mutation in 0..5 {
        let original = vec![item("one"), item("two")];
        let fixture = EvaluatedFixture::new(&original);
        let ranker = fixture.load().unwrap();
        let saved = fixture.admission.0.lock().unwrap().clone();
        {
            let mut host = fixture.admission.0.lock().unwrap();
            match mutation {
                0 => host.now_unix_micros = 101,
                1 => {
                    let mut trust = fixture.learning.trust.clone();
                    trust.authority_epoch += 1;
                    for signer in &mut trust.signers {
                        signer.principal.authority_epoch += 1;
                    }
                    host.learning_verifier = LearningEvidenceVerifierV1::new(trust).unwrap();
                }
                2 => {
                    let mut trust = fixture.learning.trust.clone();
                    trust.signers[3].revoked_at = Some(50);
                    host.learning_verifier = LearningEvidenceVerifierV1::new(trust).unwrap();
                }
                3 => host.runtime_profile_digest = hash("other-runtime"),
                4 => host.now_unix_micros = 49,
                _ => unreachable!(),
            }
        }
        let mut items = original.clone();
        assert!(ranker.rank(&owner(), 2, "lemon", &mut items).is_err());
        assert_eq!(items, original);
        *fixture.admission.0.lock().unwrap() = saved;
        assert!(ranker.rank(&owner(), 2, "lemon", &mut items).is_err());
    }
}

#[tokio::test]
async fn evaluated_load_reaches_sqlite_read_boundary_before_limit_without_writes() {
    use codex_hepta_memory::*;
    use codex_hepta_paths::HeptaFleetRoot;
    let directory = tempfile::tempdir().unwrap();
    let fleet = directory.path().join("fleet");
    std::fs::create_dir(&fleet).unwrap();
    let layout = HeptaFleetRoot::parse(std::fs::canonicalize(fleet).unwrap())
        .unwrap()
        .layout()
        .agent(&owner());
    let store = CognitiveStore::open(&layout).await.unwrap();
    let access = CognitiveAccess::agent_private(owner());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "evaluated-ranker-source".to_string(),
                content: b"lemon orchard".to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await
        .unwrap();
    for name in ["alpha", "beta"] {
        store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: name.to_string(),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content: format!("lemon orchard {name}"),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 100,
                        valid_to_unix_seconds: None,
                        citations: vec![citation.clone()],
                    },
                },
            )
            .await
            .unwrap();
    }
    let baseline = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 4, None)
        .await
        .unwrap();
    let fixture = EvaluatedFixture::new(&baseline.items);
    let ranker = Arc::new(fixture.load().unwrap());
    let ranked = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 1, Some(&ranker))
        .await
        .unwrap();
    assert_eq!(ranked.items, vec![baseline.items[1].clone()]);
    let unchanged = crate::cognitive_context::read(&store, &owner(), 2, "lemon", 4, None)
        .await
        .unwrap();
    assert_eq!(
        unchanged.items, baseline.items,
        "read-only ranking must not mutate stored rows"
    );
}
