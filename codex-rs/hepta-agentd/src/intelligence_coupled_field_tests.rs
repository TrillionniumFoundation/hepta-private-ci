//! Exercise the ordinary evaluation stage using two actually published file-backed
//! registry members, a fenced file-backed holdout, and independent test-only keys.
use super::*;
use crate::intelligence_product::AgentdCoupledFieldEvidenceOwnerV1;
use crate::intelligence_product::coupled_field::CoupledReadback;
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::*;
use codex_hepta_types::ProbabilityQ32;
use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::sync::Mutex;

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

struct Sink(File);

impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"test.evaluated-shadow.product-evidence".to_vec();
        bytes.extend_from_slice(execution_digest.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        self.0
            .write_all(&bytes)
            .and_then(|()| self.0.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}

fn temporal_plan(name: &str, objective_digest: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(&format!("{name}-evaluation")),
        objective_digest,
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope-plan")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(3_i64 << 31),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

fn provider_inputs(snapshot_id: StableId) -> Provider {
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("training-{action}-{index}")),
                principal_lineage: id(&format!("training-principal-{action}-{index}")),
                episode_lineage: id(&format!("training-episode-{action}-{index}")),
                window_id: id(&format!("training-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest("training-outcome"),
            });
        }
    }

    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..1024 {
        let decision_id = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("held-principal-{index}")),
            episode_lineage: id(&format!("held-episode-{index}")),
            window_id: id("window-1"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let observation = |a_probability: u64, b_probability: u64| OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(a_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(b_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("held-out-outcome"),
            outcome_model_evidence: digest("ignored-caller-model"),
        };
        candidate_observations.push(observation(3 << 30, 1 << 30));
        baseline_observations.push(observation(1 << 30, 3 << 30));
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Provider {
        manifest: digest("test-holdout"),
        inputs: Some(TemporalComparisonInputsV1 {
            training,
            targets,
            candidate_observations,
            baseline_observations,
            assignments,
            snapshot_ids: vec![snapshot_id],
            future_window_ids: vec![id("window-1")],
        }),
    }
}

pub(in crate::intelligence_product) fn published_qualification(
    binding: &AgentdEvaluationBindingV1,
    now: u64,
    bytes: &[u8],
) -> (
    AgentdEvaluationSessionV1,
    ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    ProductQualificationReceiptV1,
    SignedLearningEvidenceV1,
) {
    let mut session = session(binding, now);
    let verifier = session.trust.verifier();
    let generator = session.signed.bundle.generator.clone();
    let evaluator = session.signed.bundle.evaluator.clone();
    let generator_key = SigningKey::from_bytes(&[31; 32]);
    let evaluator_key = SigningKey::from_bytes(&[47; 32]);
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("qualification-metric"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![ProductMetricSourceContractV1 {
        metric_id: id("qualification-metric"),
        source: ProductMetricSourceV1::DoublyRobust,
    }];
    let candidate_plan = temporal_plan("candidate", binding.objective_digest);
    let baseline_plan = temporal_plan("baseline", binding.objective_digest);
    let frozen = freeze_product_evaluation_plan_v1(
        CrossFoldPlanV1 {
            plan_id: id("plan"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            candidate_id: binding.selected_candidate_id.clone(),
            baseline_id: id("baseline"),
            objective_digest: binding.objective_digest,
            dataset_digest: digest("qualification-dataset"),
            estimand_digest: digest("qualification-estimand"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("qualification-metric"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: None,
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: vec![
                CrossFoldPartitionV1 {
                    fold_id: id("fold-0"),
                    training_principals: vec![id("training-person-0")],
                    training_episodes: vec![id("training-episode-0")],
                    training_windows: vec![id("training-window-0")],
                    holdout_principals: vec![id("person-0")],
                    holdout_episodes: vec![id("episode-0")],
                    holdout_windows: vec![id("window-0")],
                    model_digest: digest("test-fold-model-0"),
                    predictions_digest: digest("test-predictions-0"),
                },
                CrossFoldPartitionV1 {
                    fold_id: id("fold-1"),
                    training_principals: vec![id("training-person-1")],
                    training_episodes: vec![id("training-episode-1")],
                    training_windows: vec![id("training-window-1")],
                    holdout_principals: vec![id("person-1")],
                    holdout_episodes: vec![id("episode-1")],
                    holdout_windows: vec![id("window-1")],
                    model_digest: digest("test-fold-model-1"),
                    predictions_digest: digest("test-predictions-1"),
                },
            ],
            final_holdout_window_id: id("window-1"),
            final_holdout_digest: digest("test-holdout"),
        },
        roles.clone(),
        sources,
        &candidate_plan,
        &baseline_plan,
    )
    .unwrap();

    let store = LockedFileFinalHoldoutCasStoreV1::create(
        tempfile::tempfile().unwrap(),
        digest("test-holdout-owner"),
    )
    .unwrap();
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        store,
        digest("test-holdout-owner"),
        HoldoutWriterFenceV1 {
            owner_id: id("learning-eval-owner"),
            generation: 1,
            lease_digest: digest("test-holdout-lease"),
        },
    )
    .unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let mut provider = provider_inputs(id("qualified-snapshot"));
    let temporal = runner
        .evaluate_temporal_comparison(&frozen, &candidate_plan, &baseline_plan, &mut provider)
        .unwrap();
    let context = ProductQualificationContextV1 {
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();

    let objective = binding.objective_digest;
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            verifier,
            &generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
            objective,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            verifier,
            &evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            objective,
            &evaluation_signing_payload_v2(&bundle, &roles).unwrap(),
        ),
    };
    let mut sink = Sink(tempfile::tempfile().unwrap());
    let q = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            verifier,
            now,
            &mut sink,
        )
        .unwrap();
    let signature = sign(
        verifier,
        &evaluator,
        &evaluator_key,
        LearningEvidenceRoleV1::Evaluator,
        objective,
        &codex_hepta_intelligence::evaluated_candidate_signing_payload_v2(&q, bytes, 2).unwrap(),
    );
    let use_attestation = sign(
        verifier,
        &evaluator,
        &evaluator_key,
        LearningEvidenceRoleV1::Evaluator,
        objective,
        &intelligence_evaluation_binding_payload_v1(binding, &evidence).unwrap(),
    );
    session.signed = AgentdSignedEvaluationV1 {
        bundle,
        roles,
        evidence,
        use_attestation,
    };
    (session, runner, q, signature)
}

fn scope() -> DatasetWithdrawalScopeV1 {
    DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    }
}

fn signer(key: &SigningKey, until: u64) -> TrustedArtifactSignerV1 {
    TrustedArtifactSignerV1 {
        signer_id: id("owner-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: until,
        revoked_at: None,
    }
}

fn trust(key: &SigningKey, scope_digest: Digest32, until: u64) -> ArtifactOwnerTrustV1 {
    ArtifactOwnerTrustV1 {
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).unwrap(),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer(key, until)],
        head_signers: vec![signer(key, until)],
    }
}

fn lease(key: &SigningKey, scope_digest: Digest32, until: u64) -> SignedArtifactWriterLeaseV1 {
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("writer-lease"),
        producer_id: id("trainer"),
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("owner-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: until,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    lease
}

fn manifest(until: u64) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("candidate"),
        kind: ArtifactKind::Model,
        generation: Generation::new(1).unwrap(),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset")],
        lineage_digests: vec![digest("lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("trainer"),
        created_at: 10,
        expires_at: until,
    }
}

pub(in crate::intelligence_product) fn published_parameter_family(
    path: &Path,
    candidate: &StableId,
    bytes: &[u8],
    objective: Digest32,
    now: u64,
) -> (LearningArtifactOwnerService, ParameterFamilyGuardV1) {
    let until = now + 60_000;
    let key = SigningKey::from_bytes(&[9; 32]);
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().unwrap();
    let root = path.join("service");
    let preview_root = path.join("preview");
    std::fs::create_dir(&root).unwrap();
    std::fs::create_dir(&preview_root).unwrap();
    let preview_host = LearningArtifactOwnerHost::open(
        &preview_root,
        trust(&key, scope_digest, until),
        lease(&key, scope_digest, until),
        20,
    )
    .unwrap();
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: root.clone(),
        trust: trust(&key, scope_digest, until),
        writer_lease: lease(&key, scope_digest, until),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .unwrap();
    let ids = [id("baseline"), candidate.clone()];
    for (index, (artifact, payload)) in ids.iter().zip([b"parent".as_slice(), bytes]).enumerate() {
        let mut m = manifest(until);
        m.artifact_id = artifact.clone();
        m.kind = ArtifactKind::Parameters;
        m.generation = Generation::new(1 + index as u64).unwrap();
        m.bytes_digest = Digest32::of_bytes(payload);
        m.encoded_size_bytes = payload.len() as u64;
        m.objective_class_digest = objective;
        m.predecessor_ids = ids[..index].to_vec();
        let admission =
            admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), m, 20)
                .unwrap();
        let predecessor = service.registry().snapshot().head_digest;
        let mut staged = service.registry().clone();
        let op = id(&format!("publish-{index}"));
        let tx = ArtifactPublicationTransactionV1::begin(
            op.clone(),
            admission.clone(),
            &withdrawals,
            &staged,
            predecessor,
            20,
        )
        .unwrap();
        preview_host
            .stage_compatibility_registration(&tx, &mut staged, 20)
            .unwrap();
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: scope_digest,
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("learning-artifacts"),
                generation: Generation::new(1 + index as u64).unwrap(),
                head_digest: staged.snapshot().head_digest,
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("owner-authority"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: until,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        service
            .publish(LearningArtifactPublishRequestV1 {
                operation_id: op,
                admission,
                payload: payload.to_vec(),
                signed_current_head: signed,
                expected_registry_predecessor_head: predecessor,
                now: 20,
            })
            .unwrap();
    }
    let current = service.current_registry_view(20).unwrap();
    let receipt = current.receipt();
    let registry = root.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    let pin = |artifact: &StableId| {
        let manifest = service.registry().manifest(artifact).unwrap().clone();
        let path = root
            .join("payloads")
            .join(format!("{}-{}.bin", artifact, manifest.content_digest));
        load_pinned_candidate(
            File::open(&registry).unwrap(),
            File::open(path).unwrap(),
            PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
        )
        .unwrap()
    };
    let guard = ParameterFamilyGuardV1::new(
        pin(&ids[0]),
        vec![pin(&ids[1])],
        &ids[1..],
        current.trust_digest(),
    )
    .unwrap();
    (service, guard)
}

#[test]
fn ordinary_signed_evaluation_returns_the_current_qualified_parameter_pin_and_rejects_substitution()
{
    let now = 500;
    let binding = AgentdEvaluationBindingV1 {
        selected_candidate_id: id(&format!(
            "candidate:field:{}",
            digest("registered-weight-candidate")
        )),
        ..binding()
    };
    let bytes = [0x52, 0x00, 0xA7, 0x02];
    let (mut session, runner, qualification, signature) =
        published_qualification(&binding, now, &bytes);
    session.original_record_digest = Some(digest("original-published-run"));
    let recorded = runner
        .verified_qualification_use(&qualification)
        .unwrap()
        .clone();
    let qualification_digest = qualification.evidence_digest;
    let dir = tempfile::tempdir().unwrap();
    let (service, family) = published_parameter_family(
        dir.path(),
        &binding.selected_candidate_id,
        &bytes,
        binding.objective_digest,
        now,
    );
    let witness = service.current_registry_view(now).unwrap().witness_digest();
    let owner = Arc::new(
        AgentdCoupledFieldEvidenceOwnerV1::new(
            Arc::new(Mutex::new(service)),
            family,
            Arc::new(runner),
            vec![(qualification.clone(), signature)],
        )
        .unwrap(),
    );
    let mut different = qualification.decision.clone();
    different.authentication_digest = digest("different-signed-decision");
    assert!(
        owner
            .read(&different, session.trust.verifier(), now)
            .is_err()
    );
    let exact = owner
        .readback(&qualification.decision, session.trust.verifier(), now)
        .unwrap();
    for substitute_view in [false, true] {
        let mut other = AgentdEvaluationSessionV1 {
            run_id: session.run_id.clone(),
            current_owner: session.current_owner.clone(),
            trust: Arc::clone(&session.trust),
            signed: session.signed.clone(),
            original_record_digest: session.original_record_digest,
            coupled_field_owner: Some(owner.clone()),
        };
        if substitute_view {
            let mut stale = exact.clone();
            stale.registry_witness = digest("other-registry-view");
            sign_readback(&mut other, &binding, &stale);
        }
        // The original generic use signature and a genuinely signed different
        // CURRENT view both fail when the daemon resolves its own owner.
        assert!(matches!(
            other.evaluate(&input(&binding), &binding.selected_candidate_id, now),
            Err(AgentdIntelligenceEvaluationError::Evidence(_))
        ));
    }
    sign_readback(&mut session, &binding, &exact);
    session.coupled_field_owner = Some(owner);
    let (receipt, readback) = session
        .evaluate(&input(&binding), &binding.selected_candidate_id, now)
        .unwrap();
    let expected = super::super::AgentdCoupledFieldReadbackV1 {
        binding:
            codex_hepta_intelligence::coupled_field_admission::CoupledFieldCandidateBindingV1 {
                candidate_id: binding.selected_candidate_id.clone(),
                artifact_bytes_digest: Digest32::of_bytes(&bytes),
                evaluation_dataset_digest: recorded.dataset_digest,
                plan_digest: recorded.plan_digest,
                holdout_use_digest: recorded.use_digest,
            },
        registry_witness: witness,
        qualification_digest,
    };
    assert_eq!(readback.map(|r| r.readback), Some(expected));
    assert!(!receipt.is_zero());
}

pub(in crate::intelligence_product) fn sign_readback(
    session: &mut AgentdEvaluationSessionV1,
    binding: &AgentdEvaluationBindingV1,
    readback: &super::super::AgentdCoupledFieldReadbackV1,
) {
    session.signed.use_attestation = sign(
        session.trust.verifier(),
        &session.signed.bundle.evaluator,
        &SigningKey::from_bytes(&[47; 32]),
        LearningEvidenceRoleV1::Evaluator,
        binding.objective_digest,
        &intelligence_coupled_field_use_payload_v1(
            binding,
            &session.signed.evidence,
            readback,
            session.original_record_digest.expect("published RunStart"),
        )
        .unwrap(),
    );
}
