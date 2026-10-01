use super::*;
use codex_hepta_agent_components::bellman_operator::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;

#[path = "cognitive_ranker_paired_test_support.rs"]
mod paired;

struct Admission(Mutex<RankerAdmissionSnapshotV3>);
impl CurrentRankerAdmissionV3 for Admission {
    fn current(&self) -> Result<RankerAdmissionSnapshotV3, String> {
        Ok(self.0.lock().unwrap().clone())
    }
}

fn select(
    fixture: &Fixture,
    signing: &paired::SigningFixture,
) -> (VerifiedSelfEvolutionSelectionV2, Digest32) {
    let objective = fixture.model_pin.objective_digest;
    let mut ledger = LearningLedger::new();
    ledger
        .append(LedgerEvent::Decision(EpisodeDecision {
            record_id: id("independent-evaluation-source"),
            episode_id: id("independent-evaluation-episode"),
            objective_digest: objective,
            policy_id: id("installed-comparator"),
            candidate_ids: vec![id("control-action"), id("abstain")],
            selected_candidate_id: id("control-action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: hash("original-independent-evaluation-source"),
        }))
        .unwrap();
    let snapshot = ledger.snapshot();
    let dataset = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: id("independent-evaluation-cut"),
            producer: signing.principals[0].clone(),
            ledger_head_digest: snapshot.head_digest,
            objective_digest: objective,
            eligible_frontier: 1,
            outcome_watermark: signing.now - 1,
            correction_cut_digest: hash("original-evaluation-correction-cut"),
            revocation_cut_digest: hash("original-evaluation-revocation-cut"),
            inclusion_policy_digest: hash("fixed-original-cohort"),
            source_record_digests: snapshot.records().iter().map(|r| r.event_digest).collect(),
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        signing.now,
    )
    .unwrap();
    let mut inputs = paired::inputs(
        128,
        objective,
        dataset.snapshot.dataset_digest,
        fixture.model_pin.payload_digest,
    );
    inputs.base_plan.candidate_id = id("read-ranker");
    let runtime = inputs.runtime.clone();
    let tasks = inputs.tasks.clone();
    let plan = freeze_paired_supervised_plan_v1(inputs).unwrap();
    let registration = signing.register(&plan, &runtime);
    let mut provider = signing.provider(&plan, &tasks, &runtime);
    let mut runner = paired::runner();
    let execution = runner
        .evaluate_registered_paired_supervised(&registration, &mut provider, &signing.trust)
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(
        &execution,
        &context,
        signing.sign(
            0,
            plan.frozen_plan().plan_digest.as_array(),
            signing.now - 21,
        ),
    );
    let mut sink = paired::Sink::default();
    let qualification = runner
        .qualify_paired_and_persist(&execution, &context, &evidence, &signing.trust, &mut sink)
        .unwrap();
    let prepared = prepare_self_evolution_selection_v2(
        &SelfEvolutionSelectionPolicyV2 {
            no_change_baseline_id: plan.frozen_plan().baseline_id.clone(),
            no_change_baseline_digest: runtime.deployed_baseline_digest,
            minimum_dataset_records: 1,
        },
        SelfEvolutionSelectionRequestV1 {
            selection_id: id("original-paired-selector"),
            predecessor_id: plan.frozen_plan().baseline_id.clone(),
            predecessor_generation: Generation::new(1).unwrap(),
            predecessor_artifact_digest: runtime.deployed_baseline_digest,
            candidate_id: plan.frozen_plan().candidate_id.clone(),
            candidate_generation: Generation::new(2).unwrap(),
            candidate_artifact_digest: runtime.candidate_artifact_digest,
        },
        SelfEvolutionSelectionInputsV2 {
            execution: &execution,
            qualification: &qualification,
            context: &context,
            evaluation_evidence: &evidence,
            dataset_receipt: &dataset,
            ledger_snapshot: &snapshot,
        },
        &signing.trust,
    )
    .unwrap();
    let selected = admit_self_evolution_selection_v2(
        prepared.clone(),
        &signing.sign(
            3,
            &selection_signing_payload_v2(prepared.receipt()).unwrap(),
            paired::now_millis(),
        ),
        &signing.trust,
    )
    .unwrap();
    assert_eq!(provider.release_count, 1);
    assert_eq!(sink.calls, 1);
    (selected, dataset.snapshot.dataset_digest)
}

fn pin(
    fixture: &Fixture,
    selected: &PinnedCandidateSpec,
    trust: &ActivatedLearningTrustV1,
) -> TabularPayloadPinV2 {
    let old = &fixture.model_pin;
    TabularPayloadPinV2 {
        artifact_id: selected.manifest.artifact_id.clone(),
        producer_id: selected.manifest.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: old.payload_digest,
        artifact_digest: old.artifact_digest,
        objective_digest: old.objective_digest,
        dataset_digest: old.dataset_digest,
        sensor_core_digest: old.sensor_core_digest,
        training_profile_digest: old.training_profile_digest,
        runtime_profile_digest: selected.manifest.compatibility_digest,
        trust_digest: trust.verifier().trust_digest(),
        registry_head_digest: selected.registry_receipt.head_digest,
        authority_epoch: trust.verifier().authority_epoch(),
        generation: old.generation,
    }
}

#[test]
fn paired_v2_real_wall_clock_loads_original_owner_payload_and_closes_after_root_expiry() {
    let original = vec![item("one"), item("two")];
    let fixture = fixture_with_profile(
        &original,
        &[0, 10],
        Generation::new(2).unwrap(),
        hash("read-ranking-task"),
        hash("distinct-training-data"),
    );
    let signing = paired::SigningFixture::new(fixture.model_pin.objective_digest);
    let (selection, evaluation_dataset) = select(&fixture, &signing);
    let (view, snapshot, payload, selected) = owner_service::published_wall_clock_owner_view(
        &fixture,
        vec![fixture.model_pin.dataset_digest, evaluation_dataset],
    );
    let model_pin = pin(&fixture, &selected, &signing.trust);
    let artifact_trust = view.current().unwrap().trust_digest();
    let admission = Arc::new(Admission(Mutex::new(
        RankerAdmissionSnapshotV3::new(
            signing.trust.clone(),
            artifact_trust,
            model_pin.runtime_profile_digest,
        )
        .unwrap(),
    )));
    let ranker = PinnedCognitiveRanker::load_evaluated_v2(
        owner(),
        2,
        File::open(snapshot).unwrap(),
        File::open(payload).unwrap(),
        selected,
        model_pin.clone(),
        view,
        &selection,
        admission.clone(),
    )
    .unwrap();
    let mut ranked = original.clone();
    ranker.rank(&owner(), 2, "lemon", &mut ranked).unwrap();
    assert_eq!(ranked, vec![original[1].clone(), original[0].clone()]);
    *admission.0.lock().unwrap() = RankerAdmissionSnapshotV3::new(
        signing.expired_trust(),
        artifact_trust,
        model_pin.runtime_profile_digest,
    )
    .unwrap();
    let mut rejected = original.clone();
    assert!(ranker.rank(&owner(), 2, "lemon", &mut rejected).is_err());
    assert_eq!(rejected, original);
    assert!(ranker.cache.lock().unwrap().is_none());
    *admission.0.lock().unwrap() = RankerAdmissionSnapshotV3::new(
        signing.trust,
        artifact_trust,
        model_pin.runtime_profile_digest,
    )
    .unwrap();
    assert!(ranker.revalidate().is_err());
}

#[test]
fn paired_v2_requires_evaluation_provenance_and_complete_independent_model_pin() {
    let original = vec![item("one"), item("two")];
    let fixture = fixture_with_profile(
        &original,
        &[0, 10],
        Generation::new(2).unwrap(),
        hash("read-ranking-task"),
        hash("distinct-training-data"),
    );
    let signing = paired::SigningFixture::new(fixture.model_pin.objective_digest);
    let (selection, evaluation_dataset) = select(&fixture, &signing);
    // Publish through the true owner, but omit the signed evaluation source.
    let (view, snapshot, payload, selected) = owner_service::published_wall_clock_owner_view(
        &fixture,
        vec![fixture.model_pin.dataset_digest],
    );
    let model_pin = pin(&fixture, &selected, &signing.trust);
    let admission = Arc::new(Admission(Mutex::new(
        RankerAdmissionSnapshotV3::new(
            signing.trust.clone(),
            view.current().unwrap().trust_digest(),
            model_pin.runtime_profile_digest,
        )
        .unwrap(),
    )));
    assert!(
        PinnedCognitiveRanker::load_evaluated_v2(
            owner(),
            2,
            File::open(&snapshot).unwrap(),
            File::open(&payload).unwrap(),
            selected,
            model_pin,
            view,
            &selection,
            admission
        )
        .is_err()
    );
    // The independent pin mutations run against complete, valid provenance,
    // so the missing evaluation source cannot mask an identity failure.
    let complete = fixture_with_profile(
        &original,
        &[0, 10],
        Generation::new(2).unwrap(),
        hash("read-ranking-task"),
        hash("distinct-training-data"),
    );
    assert_eq!(complete.model_pin, fixture.model_pin);
    let (view, snapshot, payload, selected) = owner_service::published_wall_clock_owner_view(
        &complete,
        vec![complete.model_pin.dataset_digest, evaluation_dataset],
    );
    let model_pin = pin(&complete, &selected, &signing.trust);
    let admission = Arc::new(Admission(Mutex::new(
        RankerAdmissionSnapshotV3::new(
            signing.trust,
            view.current().unwrap().trust_digest(),
            model_pin.runtime_profile_digest,
        )
        .unwrap(),
    )));
    for mutation in 0..4 {
        let mut changed = model_pin.clone();
        match mutation {
            0 => changed.producer_id = id("unadmitted-producer"),
            1 => changed.runtime_profile_digest = hash("unadmitted-runtime"),
            2 => changed.registry_head_digest = hash("unadmitted-registry-head"),
            3 => changed.sensor_core_digest = hash("unadmitted-sensor-contract"),
            _ => unreachable!(),
        }
        assert!(
            PinnedCognitiveRanker::load_evaluated_v2(
                owner(),
                2,
                File::open(&snapshot).unwrap(),
                File::open(&payload).unwrap(),
                selected.clone(),
                changed,
                view.clone(),
                &selection,
                admission.clone()
            )
            .is_err()
        );
    }
}
