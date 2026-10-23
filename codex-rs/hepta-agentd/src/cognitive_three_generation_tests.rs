//! Executed local learning study, not neural, organizational or service qualification.
use super::*;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::Value;
use serde_json::json;

#[path = "cognitive_three_generation_admission.rs"]
mod admission;
#[path = "cognitive_three_generation_controls.rs"]
mod controls;
#[path = "cognitive_three_generation_process.rs"]
mod process;
#[path = "cognitive_three_generation_provider.rs"]
mod provider;
#[path = "cognitive_three_generation_publication.rs"]
mod publication;
#[path = "cognitive_three_generation_support.rs"]
mod support;
#[path = "cognitive_three_generation_temporal.rs"]
mod temporal;
use support::Roles;
use support::fit;
use support::save;

struct Host {
    fleet: FleetRegistry,
    fleet_path: PathBuf,
    workspace: PathBuf,
    layout: codex_hepta_paths::HeptaAgentLayout,
    store: Arc<CognitiveStore>,
    launch: u64,
}
impl Host {
    async fn new(root: &std::path::Path) -> Self {
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).unwrap();
        let fleet = FleetRegistry::initialize(fleet_root.clone()).unwrap();
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).unwrap();
        let record = fleet
            .register(
                AgentManifest::new(
                    owner(),
                    WorkspaceBinding::new(&workspace, &fleet_root).unwrap(),
                    ResourceBudget::local_default(),
                )
                .unwrap(),
            )
            .unwrap();
        fleet
            .compare_and_transition(&owner(), 0, AgentLifecycle::Starting)
            .unwrap();
        let store = Arc::new(CognitiveStore::open(&record.layout).await.unwrap());
        Self {
            fleet,
            fleet_path,
            workspace,
            layout: record.layout,
            store,
            launch: 1,
        }
    }
    fn config(&self) -> crate::AgentdConfig {
        crate::AgentdConfig::load(
            self.fleet_path.clone(),
            owner(),
            self.launch,
            self.layout.home_root().into(),
            self.layout.run_root().into(),
            self.layout.home_root().into(),
            self.workspace.clone(),
        )
        .unwrap()
    }
    fn running(&self) {
        self.fleet
            .compare_and_transition(&owner(), self.launch, AgentLifecycle::Running)
            .unwrap();
    }
    async fn restart(&mut self) {
        self.fleet
            .compare_and_transition(&owner(), self.launch + 1, AgentLifecycle::Draining)
            .unwrap();
        self.fleet
            .compare_and_transition(&owner(), self.launch + 2, AgentLifecycle::Stopped)
            .unwrap();
        self.fleet
            .compare_and_transition(&owner(), self.launch + 3, AgentLifecycle::Starting)
            .unwrap();
        self.launch += 4;
        self.store = Arc::new(CognitiveStore::open(&self.layout).await.unwrap());
    }
    async fn seed(&self) -> Vec<(CognitiveContextItem, String)> {
        let access = CognitiveAccess::agent_private(owner());
        let scope = CognitiveScope::AgentPrivate;
        let observed_at = i64::try_from(support::micros() / 1_000_000).unwrap();
        let citation = self
            .store
            .append_source(
                &access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: "three-generation-source".into(),
                    content: b"four permitted arithmetic instructions".to_vec(),
                    observed_at_unix_seconds: observed_at,
                },
            )
            .await
            .unwrap();
        for operation in ["add", "multiply", "xor", "subtract"] {
            self.store.remember_memory(&access, &MemoryDraft {stable_key:operation.into(), revision:MemoryRevisionDraft {
                scope:scope.clone(), content:format!("bootstrap familyalpha familybeta familygamma instruction {operation}"),
                verification:MemoryVerification::Verified, lifecycle:MemoryLifecycleState::Active, valid_from_unix_seconds:100,
                valid_to_unix_seconds:None, citations:vec![citation.clone()]}}).await.unwrap();
        }
        let baseline = crate::cognitive_context::read(
            &self.store,
            &owner(),
            self.launch,
            "familyalpha",
            4,
            None,
        )
        .await
        .unwrap();
        assert_eq!(baseline.items.len(), 4);
        baseline
            .items
            .into_iter()
            .map(|item| {
                let operation = item.content.split_whitespace().last().unwrap().to_owned();
                (item, operation)
            })
            .collect()
    }
    async fn prove_candidate_withdrawal(
        &self,
        root: &std::path::Path,
        fitted: &support::Fitted,
        roles: &mut Roles,
    ) {
        let root = root.join("withdrawal-control");
        std::fs::create_dir(&root).unwrap();
        let view = Arc::new(publication::StudyView::new(root.join("owner"), roles));
        let published = view.publish(&root, fitted, None, roles);
        let current: Arc<dyn CurrentCognitiveRegistry> = view.clone();
        let ranker = Arc::new(
            PinnedCognitiveRanker::load_source(
                owner(),
                self.launch,
                File::open(&published.snapshot).unwrap(),
                File::open(&published.payload).unwrap(),
                published.selected.clone(),
                fitted.pin.clone(),
                current,
                Some(published.source),
            )
            .unwrap(),
        );
        crate::cognitive_context::read(
            &self.store,
            &owner(),
            self.launch,
            "bootstrap",
            1,
            Some(&ranker),
        )
        .await
        .unwrap();
        view.revoke(&root, published.selected.manifest.artifact_id, roles);
        view.suspend();
        view.resume();
        let error = crate::cognitive_context::read(
            &self.store,
            &owner(),
            self.launch,
            "bootstrap",
            1,
            Some(&ranker),
        )
        .await
        .unwrap_err();
        save(
            &root.join("observed.json"),
            &json!({"candidate":fitted.pin.payload_digest.to_string(),
            "native_error":format!("{error:?}"),"reopened_original_owner":true,
            "revocation_receipt_digest":Digest32::of_bytes(&std::fs::read(root.join("revocation.json")).unwrap()).to_string(),
            "scope":"actual artifact withdrawal and cached consumption refusal; no claim of data erasure or parameter unlearning"}),
        );
    }
    async fn actual_choices(
        &self,
        ranker: &Arc<PinnedCognitiveRanker>,
        root: &std::path::Path,
        label: &str,
    ) -> Value {
        let mut result = serde_json::Map::new();
        for query in ["bootstrap", "familyalpha", "familybeta", "familygamma"] {
            // This is the production cognitive read owner used by ordinary
            // Agentd requests. AF_UNIX/App Server startup is separately blocked
            // in this host; no readiness or socket success is manufactured.
            let response = crate::cognitive_context::read(
                &self.store,
                &owner(),
                self.launch,
                query,
                1,
                Some(ranker),
            )
            .await
            .unwrap();
            assert_eq!(response.items.len(), 1);
            let operation = response.items[0].content.split_whitespace().last().unwrap();
            result.insert(query.into(), json!(operation));
            save(
                &root.join(format!("{label}-{query}-native-context.json")),
                &serde_json::to_value(response).unwrap(),
            );
        }
        Value::Object(result)
    }
}

fn holdout_fence() -> codex_hepta_intelligence_eval::HoldoutWriterFenceV1 {
    codex_hepta_intelligence_eval::HoldoutWriterFenceV1 {
        owner_id: id("study-product-evaluator"),
        generation: 1,
        lease_digest: hash("local-study-exclusive-file-cas-fence-v1"),
    }
}

#[tokio::test]
#[ignore = "explicit retained 3-generation learning study with fresh process-owned keys and full native owners"]
async fn three_actual_fits_installations_future_instances_no_update_and_revocation() {
    let root = PathBuf::from(
        std::env::var("HEPTA_LEARNING_STUDY_DIRECTORY")
            .expect("new study output directory required"),
    );
    std::fs::create_dir(&root).unwrap();
    let root = root.canonicalize().unwrap();
    let script = PathBuf::from(
        std::env::var("HEPTA_LEARNING_CUSTODIAN").expect("exact custodian source required"),
    );
    let started = std::time::Instant::now();
    let mut host = Host::new(&root).await;
    let actions = host.seed().await;
    let mut roles = Roles::new(&script, &root);
    let operation_order: Vec<_> = actions.iter().map(|(_, op)| op.clone()).collect();
    let material_keys = json!({"evaluator":support::hex(&roles.processes[1].key), "future-custodian":support::hex(&roles.processes[6].key)});
    let observer_key = support::hex(&roles.processes[2].key);
    for role in &mut roles.processes {
        role.call(json!({"command":"configure", "operations":operation_order, "material_keys":material_keys, "observer_key":observer_key}));
    }
    save(
        &root.join("profile.json"),
        &json!({"schema":"hepta.local-three-generation-study.v1", "operations":operation_order,
        "query_families":["bootstrap","familyalpha","familybeta","familygamma"],
        "operand_strata":{"generator":{"a_modulus":2,"a_residue":1},"evaluator":{"a_modulus":4,"a_residue":0},"future-custodian":{"a_modulus":4,"a_residue":2}},
        "final_estimation_population":"future-custodian a modulo4 equals2; uniform family, b in3..100002; distinct from training stratum",
        "actions":actions.iter().map(|(item,op)|json!({"item":item,"operation":op})).collect::<Vec<_>>(),
        "keys":roles.processes.iter().map(|r|json!({"role":r.name,"public_key":support::hex(&r.key),"pid":r.pid})).collect::<Vec<_>>(),
        "custodian_sha256":Digest32::of_bytes(&std::fs::read(&script).unwrap()).to_string(),
        "domain":"synthetic finite arithmetic instruction retrieval; observed rewards, native fitted means",
        "organizational_independence":false, "general_neural_model_efficacy":false, "parameter_unlearning_proven":false, "data_erasure_proven":false, "full_service_startup":false}),
    );
    let view = Arc::new(publication::StudyView::new(
        root.join("artifact-owner"),
        &mut roles,
    ));
    let holdout_file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(root.join("holdouts"))
        .unwrap();
    let store = codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1::create(
        holdout_file,
        hash("three-generation-holdouts"),
    )
    .unwrap();
    let holdout_owner = codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1::initialize(
        store,
        hash("three-generation-holdouts"),
        holdout_fence(),
    )
    .unwrap();
    let mut holdouts = codex_hepta_intelligence_eval::ProductEvaluationRunnerV1::new(holdout_owner);
    File::open(&root).unwrap().sync_all().unwrap();
    let bootstrap_root = root.join("generation-0");
    std::fs::create_dir(&bootstrap_root).unwrap();
    let mut fitted = fit(&bootstrap_root, 0, &mut roles, &actions);
    let mut published = view.publish(&bootstrap_root, &fitted, None, &mut roles);
    // This negative publishes a fully legitimate V2/V1 pair through the real
    // writer, but its dataset differs from the payload's native training pin.
    let wrong_root = root.join("wrong-source-dataset");
    std::fs::create_dir(&wrong_root).unwrap();
    let wrong_view = Arc::new(publication::StudyView::new(
        wrong_root.join("owner"),
        &mut roles,
    ));
    let wrong = wrong_view.publish_declared_dataset(
        &wrong_root,
        &fitted,
        None,
        hash("different-actual-dataset"),
        &mut roles,
    );
    let wrong_result = PinnedCognitiveRanker::load_source(
        owner(),
        host.launch,
        File::open(&wrong.snapshot).unwrap(),
        File::open(&wrong.payload).unwrap(),
        wrong.selected,
        fitted.pin.clone(),
        wrong_view,
        Some(wrong.source),
    );
    assert!(
        wrong_result.is_err(),
        "valid full source cannot substitute a different dataset for the payload"
    );
    save(
        &wrong_root.join("rejection.json"),
        &json!({"error":wrong_result.err().unwrap()}),
    );
    let current: Arc<dyn CurrentCognitiveRegistry> = view.clone();
    let mut ranker = Arc::new(
        PinnedCognitiveRanker::load_source(
            owner(),
            host.launch,
            File::open(&published.snapshot).unwrap(),
            File::open(&published.payload).unwrap(),
            published.selected.clone(),
            fitted.pin.clone(),
            current.clone(),
            Some(published.source.clone()),
        )
        .unwrap(),
    );
    let configured = host.config().with_cognitive_ranker(ranker.clone()).unwrap();
    let (_, _, mut writer_lock) = configured.into_parts();
    host.running();
    let mut parent_choices = host
        .actual_choices(&ranker, &bootstrap_root, "installed")
        .await;
    assert_eq!(parent_choices, admission::choices(&fitted, &actions));
    let mut generations = Vec::new();
    for generation in 1..=3 {
        let generation_started = std::time::Instant::now();
        let directory = root.join(format!("generation-{generation}"));
        std::fs::create_dir(&directory).unwrap();
        let candidate = fit(&directory, generation, &mut roles, &actions);
        let next = view.publish(
            &directory,
            &candidate,
            Some(&published.selected.manifest),
            &mut roles,
        );
        host.prove_candidate_withdrawal(&directory, &candidate, &mut roles)
            .await;
        let predicted = admission::choices(&candidate, &actions);
        let (selection, compatibility) = admission::evaluate(
            &directory,
            generation,
            &format!("generation-{generation}"),
            &candidate,
            &published.selected.manifest,
            &predicted,
            &parent_choices,
            &mut roles,
            &mut holdouts,
        )
        .unwrap();
        let compatibility_error = PinnedCognitiveRanker::load_evaluated_published(
            owner(),
            host.launch,
            File::open(&next.snapshot).unwrap(),
            File::open(&next.payload).unwrap(),
            next.selected.clone(),
            candidate.pin.clone(),
            next.source.clone(),
            current.clone(),
            &compatibility,
        )
        .err()
        .expect("published installation must refuse compatibility-only token");
        assert_eq!(compatibility_error, codex_hepta_intelligence_eval::SelfEvolutionSelectionError::CanonicalQualificationRequired.to_string());
        save(
            &directory.join("compatibility-install-rejection.json"),
            &json!({"error":compatibility_error}),
        );
        drop(writer_lock);
        host.restart().await;
        ranker = Arc::new(
            PinnedCognitiveRanker::load_evaluated_published(
                owner(),
                host.launch,
                File::open(&next.snapshot).unwrap(),
                File::open(&next.payload).unwrap(),
                next.selected.clone(),
                candidate.pin.clone(),
                next.source.clone(),
                current.clone(),
                &selection,
            )
            .unwrap(),
        );
        let configured = host.config().with_cognitive_ranker(ranker.clone()).unwrap();
        let (_, _, next_lock) = configured.into_parts();
        writer_lock = next_lock;
        host.running();
        let actual = host.actual_choices(&ranker, &directory, "installed").await;
        assert_eq!(
            actual, predicted,
            "ordinary consumer must execute the evaluated artifact"
        );
        let consumer = roles.processes[1].call(json!({"command":"consumer", "generation":generation,
            "name":format!("generation-{generation}-installed-consumer"), "candidate":directory.join("payload"),
            "candidate_sha256":candidate.pin.payload_digest.to_string(), "choices":actual, "parent_choices":parent_choices}));
        assert_eq!(
            consumer["body"]["counts"]["candidate"],
            consumer["body"]["sample_count"]
        );
        save(&directory.join("installed-consumer.json"), &consumer);
        generations.push(json!({"generation":generation, "model_generation":candidate.artifact.generation.get(), "launch_generation":host.launch,
            "candidate":candidate.pin.payload_digest.to_string(), "parent":published.selected.manifest.content_digest.to_string(),
            "selection":selection.selection_digest().to_string(), "wall_ns":generation_started.elapsed().as_nanos(),
            "actual_consumer_count":consumer["body"]["sample_count"]}));
        parent_choices = actual;
        fitted = candidate;
        published = next;
    }
    let no_update = root.join("no-update");
    std::fs::create_dir(&no_update).unwrap();
    let equal = fit(&no_update, 4, &mut roles, &actions);
    let _registered = view.publish(
        &no_update,
        &equal,
        Some(&published.selected.manifest),
        &mut roles,
    );
    host.prove_candidate_withdrawal(&no_update, &equal, &mut roles)
        .await;
    let equal_choices = admission::choices(&equal, &actions);
    assert_eq!(equal_choices, parent_choices);
    let rejected = admission::evaluate(
        &no_update,
        3,
        "no-update",
        &equal,
        &published.selected.manifest,
        &equal_choices,
        &parent_choices,
        &mut roles,
        &mut holdouts,
    )
    .unwrap_err();
    assert!(matches!(
        rejected,
        codex_hepta_intelligence_eval::SelfEvolutionSelectionError::EvaluationRejected
    ));
    let retained = host
        .actual_choices(&ranker, &no_update, "retained-parent")
        .await;
    assert_eq!(retained, parent_choices);
    let anchor = holdouts.holdout_anchor();
    drop(holdouts);
    // Real process-input reconstruction uses the original read-only CURRENT
    // owner while the single named producer remains alive and holds its fence.
    drop(writer_lock);
    drop(ranker);
    let mut process_restarts = Vec::new();
    let mut live_process = None;
    for restart in 0..2 {
        host.restart().await;
        let (path, digest) =
            process::descriptor(&root, &published, &fitted, &view, host.launch, anchor);
        let config = host.config();
        assert!(
            crate::load_cognitive_process_bootstrap_v1(&path, Digest32::ZERO, config.identity())
                .is_err()
        );
        let bytes = std::fs::read(&path).unwrap();
        for (label, owned_root) in [
            ("workspace", host.workspace.as_path()),
            ("home", host.layout.home_root()),
            ("run", host.layout.run_root()),
        ] {
            let owned_path =
                owned_root.join(format!("body-{label}-bootstrap-{}.json", host.launch));
            std::fs::write(&owned_path, &bytes).unwrap();
            assert!(
                crate::load_cognitive_process_bootstrap_v1(&owned_path, digest, config.identity())
                    .is_err()
            );
        }
        let mut altered: Value = serde_json::from_slice(&bytes).unwrap();
        altered["current"]["required_current_head"]["signature_hex"] = json!("00".repeat(64));
        let altered_path = root.join(format!("altered-bootstrap-{}.json", host.launch));
        save(&altered_path, &altered);
        assert!(
            crate::load_cognitive_process_bootstrap_v1(&altered_path, digest, config.identity())
                .is_err()
        );
        let mut replay_denials = Vec::new();
        for label in ["new-fence", "unrecorded-plan"] {
            let mut changed: Value = serde_json::from_slice(&bytes).unwrap();
            if label == "new-fence" {
                changed["holdout"]["fence"]["generation"] = json!(holdout_fence().generation + 1);
            } else {
                // The ordinary product factory computes this valid plan's
                // digest; this plan has never been consumed by the owner.
                changed["frozen_plan"]["plan_id"] = json!("unrecorded-cognitive-bootstrap-plan");
            }
            let changed_path = root.join(format!("{label}-bootstrap-{}.json", host.launch));
            save(&changed_path, &changed);
            let changed_digest = Digest32::of_bytes(&std::fs::read(&changed_path).unwrap());
            let before = std::fs::read(root.join("holdouts")).unwrap();
            let error = crate::load_cognitive_process_bootstrap_v1(
                &changed_path,
                changed_digest,
                config.identity(),
            )
            .err()
            .expect("replay mutation must reject");
            assert!(
                error.to_string().contains("exact recorded plan and fence"),
                "{error}"
            );
            assert_eq!(std::fs::read(root.join("holdouts")).unwrap(), before);
            replay_denials.push(json!({"control":label,"error":error.to_string(),
                "cas_unchanged":true,"cas_sha256":Digest32::of_bytes(&before).to_string()}));
        }
        save(
            &root.join(format!(
                "process-{}-replay-negative-controls.json",
                host.launch
            )),
            &json!(replay_denials),
        );
        let input =
            crate::load_cognitive_process_bootstrap_v1(&path, digest, config.identity()).unwrap();
        let configured = config.with_evaluated_cognitive_bootstrap(input).unwrap();
        let process_ranker = configured.cognitive_ranker().unwrap();
        let (_, _, process_lock) = configured.into_parts();
        host.running();
        let actual = host
            .actual_choices(&process_ranker, &root, &format!("process-{}", host.launch))
            .await;
        assert_eq!(actual, parent_choices);
        process_restarts.push(json!({"launch_generation":host.launch,"descriptor":path,"digest":digest.to_string(),"holdout_record_count":anchor.record_count}));
        if restart == 1 {
            live_process = Some((process_ranker, process_lock));
        } else {
            drop(process_ranker);
            drop(process_lock);
        }
    }
    let (ranker, _writer_lock) = live_process.unwrap();
    view.revoke(
        &root,
        published.selected.manifest.artifact_id.clone(),
        &mut roles,
    );
    let live_error = crate::cognitive_context::read(
        &host.store,
        &owner(),
        host.launch,
        "familyalpha",
        1,
        Some(&ranker),
    )
    .await
    .unwrap_err();
    view.suspend();
    view.resume(); // Producer recovery; live process reader is never dropped.
    let recovered_error = crate::cognitive_context::read(
        &host.store,
        &owner(),
        host.launch,
        "familyalpha",
        1,
        Some(&ranker),
    )
    .await
    .unwrap_err();
    save(
        &root.join("revoke-observations.json"),
        &json!({"launch_generation":host.launch,
        "candidate":fitted.pin.payload_digest.to_string(), "live_current_error":format!("{live_error:?}"),
        "producer_recovered_error":format!("{recovered_error:?}"), "consumer_kept_alive":true,
        "revocation_receipt_digest":Digest32::of_bytes(&std::fs::read(root.join("revocation.json")).unwrap()).to_string()}),
    );
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(root.join("holdouts"))
        .unwrap();
    let recovered = codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1::recover(
        file,
        hash("three-generation-holdouts"),
        Some(anchor),
    )
    .unwrap();
    assert_eq!(recovered.anchor(), Some(anchor));
    let process_costs: Vec<_> = roles
        .processes
        .into_iter()
        .map(support::Role::close)
        .collect();
    save(
        &root.join("summary.json"),
        &json!({"schema":"hepta.local-three-generation-study.v1", "generations":generations,
        "installed_generations":3, "no_update_error":format!("{rejected:?}"), "retained_model":fitted.pin.payload_digest.to_string(),
        "revoked_reads_refused":2, "wall_ns":started.elapsed().as_nanos(), "role_process_costs":process_costs,
        "holdout_anchor":crate::cognitive_process_product_wire::FinalHoldoutCasAnchorV1Raw::from(anchor),
        "production_qualification":false, "organizational_independence":false, "general_neural_model_efficacy":false, "parameter_unlearning_proven":false, "data_erasure_proven":false,
        "named_writer_durable_revocation":true, "live_process_reader_external_revoke":true, "process_descriptor_restarts":process_restarts, "full_service_startup":false,
        "scope":"actual native fit/publication/selection/Agentd configuration and production cognitive-read owner; synthetic arithmetic task domain"}),
    );
}
