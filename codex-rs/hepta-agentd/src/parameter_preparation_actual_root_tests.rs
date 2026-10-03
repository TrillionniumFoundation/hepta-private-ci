//! Whole original owner/context preparation over an actual kernel Root peer.
use super::*;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::neuron::*;
use codex_hepta_agent_components::plasticity::*;
use serde_json::Value;
use serde_json::json;
use std::os::unix::fs::PermissionsExt;

#[path = "parameter_preparation_root_context_test_support.rs"]
mod context_support;
use context_support::*;
#[path = "parameter_dataset_root_test_support.rs"]
mod dataset_support;
use dataset_support::*;
#[path = "parameter_context_projection_actual_root_tests.rs"]
mod projection_support;

struct UnusedTickProvider;
impl crate::AgentdNeuronTickProviderV2 for UnusedTickProvider {
    fn build_tick(
        &self,
        _: &crate::AgentdIdentity,
        _: &RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
    ) -> Result<NeuronTickInputV1, AgentdError> {
        Err(AgentdError::Invalid(
            "preparation must not dispatch a tick".into(),
        ))
    }
}

struct UnusedGoalFactory;
impl crate::AgentdNeuronGoalScopeFactoryV3 for UnusedGoalFactory {
    fn open_goal_scope(
        &self,
        _: &crate::AgentdIdentity,
        _: &RunStartRecordV1,
        _: &crate::AgentdIntelligenceInvocationV1,
        _: &codex_hepta_agent_components::intelligence::CanonicalPortInputV1,
        _: &crate::AgentdNeuronGoalScopeV3,
    ) -> Result<crate::AgentdNeuronHandleV2, AgentdError> {
        Err(AgentdError::Invalid(
            "context reads must not create or reload another Goal owner".into(),
        ))
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual UID0 and independently protected complete fixture sources"]
async fn actual_root_peer_prepares_from_whole_context_and_same_acknowledged_v2_owner_without_writes()
 {
    assert_eq!(unsafe { libc::geteuid() }, 0, "actual kernel Root peer");
    let root = tempfile::Builder::new()
        .prefix("hepta-prepare-root-")
        .permissions(fs::Permissions::from_mode(0o700))
        .tempdir_in("/root")
        .expect("private independent Root fixture");
    let mut fixture = clock_fixture(crate::authbus_ingress::now_ms);
    fixture.owner.guard_elapsed_ms = crate::plasticity_runtime::monotonic_elapsed_ms;
    let now = crate::authbus_ingress::now_ms().expect("actual clock");
    let expires = (now / 1000 + 120) * 1000;
    let objective = fixture.parameter.admission.objective_digest;
    let (neuron, neuron_material) =
        crate::neuron_runtime_v2::lock_metrics_tests::runtime_fixture_for_parameter_preparation(
            id(fixture.state.identity().agent_id.as_str()),
            digest("actual Serving Goal objective distinct from training"),
        );
    let mut material = neuron_material.clone();
    material.scope = NeuronTickInputV1::journal_scope_for_subject(
        &id(fixture.state.identity().agent_id.as_str()),
        objective,
    )
    .expect("original training scope");
    material.store_context.scope = material.scope;
    material.index_context.scope = material.scope;
    material.witness_context.scope = material.scope;
    material.generation_store = root.path().join("registered-training-generation.hptngs02");
    material.runtime_index = root.path().join("registered-training-index.hptngi02");
    material.witness = root.path().join("registered-training-witness.hptnwv02");
    assert_ne!(material.scope, neuron_material.scope);
    crate::neuron_runtime_v2::lock_metrics_tests::commit_parameter_preparation_checkpoint(&neuron);
    let (_, anchor) = neuron
        .handle
        .current_tick_anchor()
        .expect("actual owner frontier");
    let anchor = anchor.expect("whole acknowledged V2 checkpoint");
    let host = crate::AgentdNeuronRuntimeV2Config::new(
        neuron.handle.clone(),
        root.path().join("neuron-control.json"),
        Arc::new(UnusedTickProvider),
    )
    .expect("same original owner")
    .with_goal_scope_factory_v3(
        crate::AgentdNeuronGoalScopeV3::capture(/*ordinal*/ 1, &neuron.handle)
            .expect("actual original Goal scope"),
        Arc::new(UnusedGoalFactory),
    )
    .expect("original installed Goal mode with the same held owner")
    .start()
    .expect("Serving original V2 owner");
    fixture
        .state
        .neuron_runtime_v2
        .set(host.clone())
        .unwrap_or_else(|_| panic!("one installed V2 host"));
    let (trust, trust_json) = learning_trust(material.scope, now, expires);
    populate_original_dataset_ledger(&mut fixture, root.path(), &trust, now);
    let dataset_witness_before = fs::read(root.path().join("authenticated-dataset-witness.bin"))
        .expect("same original acknowledged Ledger witness");
    let expected_dataset_snapshot = fixture
        .owner
        .ledger
        .snapshot()
        .expect("same production ledger");
    let (runtime, iteration) =
        crate::AgentdSelfIterationRuntimeConfigV1::new(root.path().join("iteration.json"), trust)
            .expect("original sole iteration journal");
    fixture
        .state
        .self_iteration_handle
        .set(iteration.clone())
        .unwrap_or_else(|_| panic!("one installed iteration handle"));
    let cancellation = CancellationToken::new();
    let iteration_task = tokio::spawn(
        runtime
            .start(host.clone())
            .expect("original runtime")
            .run(cancellation.clone()),
    );
    let (canonical, envelope) = envelopes(objective, expires);
    let round = iteration
        .reserve_round(id("goal.actual-root-prepare"), canonical, envelope)
        .await
        .expect("actual durable reservation");
    let artifacts = PublishedArtifacts::new(root.path(), &material, now, expires);
    let context = write_context(
        root.path(),
        RootContextInputs {
            fixture: &fixture,
            material: &material,
            neuron_material: &neuron_material,
            anchor,
            round: &round,
            artifacts: &artifacts,
            trust: trust_json,
            now,
            expires,
        },
    );
    let (search_path, search_pin) = write_search(root.path(), &artifacts.profile);
    let stage = std::time::Instant::now();
    let authenticated_context = crate::plasticity_process_bootstrap::load_input_context_v2(
        &context.0,
        context.1,
        fixture.state.identity(),
        &fixture.owner.ledger,
        host.clone(),
        crate::authbus_ingress::now_ms().expect("actual clock"),
    )
    .expect("actual original complete context fixture must authenticate before socket preparation");
    eprintln!("original protected context load: {:?}", stage.elapsed());
    let stage = std::time::Instant::now();
    fixture
        .owner
        .prepare_with_context(
            &fixture.state,
            &CancellationToken::new(),
            fixture.state.current_generation().expect("actual runtime"),
            search_path.clone(),
            search_pin,
            authenticated_context,
        )
        .expect("actual original owner must prepare the complete fixture without changing context");
    eprintln!("original direct preparation: {:?}", stage.elapsed());
    assert!(
        fixture.owner.input_context.is_none(),
        "pure original facts do not install context"
    );
    let initial_installed_artifact_head = fixture.owner.artifacts.head_digest();
    fixture.owner.current_artifacts = Some(
        crate::plasticity_runtime::current_artifacts::PlasticityCurrentArtifactsV1::new(
            artifacts.current_reader(),
            ["policy:update-rule", "policy:mutation", "policy:broadcast"].map(id),
            &fixture.owner.artifacts,
            &fixture.owner.owner_evidence_policy,
        )
        .expect(
            "original bootstrap reader pins actual CURRENT without replacing installed snapshot",
        ),
    );
    let durable_before = persistent_bytes(&fixture.files);
    let ledger_before = fs::read(&fixture.files.ledger).expect("same held Ledger");
    let owner = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        fixture.state.clone(),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let journal_before =
        fs::read(root.path().join("iteration.json")).expect("original durable reservation");
    let physical_before = [
        neuron_material.generation_store.clone(),
        neuron_material.runtime_index.clone(),
        neuron_material.witness.clone(),
    ]
    .map(|path| fs::read(path).expect("original actual V2 store"));
    let source_before = artifacts.source_bytes();
    let socket = root.path().join("parameter-prepare.sock");
    let server =
        AgentdControlServer::bind(socket.clone(), fixture.state.clone(), cancellation.clone())
            .await
            .expect("original socket");
    let serving = tokio::spawn(server.run());
    let client = AgentdClient::new(socket, fixture.state.identity().agent_id.clone(), 1)
        .expect("spawn bound client");
    let expected_runtime = fixture
        .state
        .current_generation()
        .expect("original Running generation");
    assert_eq!(expected_runtime, 2);
    let dataset = verify_actual_dataset_socket(
        &client,
        &round,
        &context,
        root.path(),
        &expected_dataset_snapshot,
        initial_installed_artifact_head,
    )
    .await;
    let context = projection_support::project_and_check_context(
        &context,
        root.path(),
        projection_support::ProjectionInputs {
            identity: fixture.state.identity(),
            round: &round,
            training: &material,
            goal: &neuron_material,
            anchor,
            artifacts: &artifacts,
            dataset: &dataset,
        },
    );
    let stage = std::time::Instant::now();
    let temporary = client
        .prepare_parameter_input_from_context_v2(
            round.clone(),
            context.0.clone(),
            context.1,
            search_path.clone(),
            search_pin,
        )
        .await;
    eprintln!("original socket preparation: {:?}", stage.elapsed());
    let temporary = temporary.expect("actual Root temporary whole context with no installation");
    assert_eq!(temporary.0, expected_runtime);
    assert_eq!(
        temporary.3.proposal_registry_predecessor,
        Digest32::ZERO.to_string()
    );
    assert_eq!(
        client
            .prepare_parameter_input_from_context_v2(
                round.clone(),
                context.0.clone(),
                context.1,
                search_path.clone(),
                search_pin,
            )
            .await
            .expect("read-only exact temporary preparation"),
        temporary
    );
    assert!(
        client
            .prepare_parameter_input_v1(round.clone(), search_path.clone(), search_pin)
            .await
            .is_err(),
        "new Round requires its original context first"
    );
    assert_ne!(
        initial_installed_artifact_head,
        artifacts.registry.head_digest()
    );
    verify_actual_dataset_socket(
        &client,
        &round,
        &context,
        root.path(),
        &expected_dataset_snapshot,
        initial_installed_artifact_head,
    )
    .await;
    assert_eq!(
        client
            .refresh_parameter_input_context_v2(round.clone(), context.0.clone(), context.1)
            .await
            .expect("actual Root socket refresh on original Round command turn"),
        expected_runtime
    );
    let mut foreign_round = serde_json::to_value(&round).expect("original typed Round");
    foreign_round["goal"] = json!("goal.foreign-root-prepare");
    let foreign_round: crate::AgentdSelfIterationRoundV1 =
        serde_json::from_value(foreign_round).expect("valid different Round");
    assert!(
        client
            .prepare_parameter_input_from_context_v2(
                foreign_round.clone(),
                context.0.clone(),
                context.1,
                search_path.clone(),
                search_pin,
            )
            .await
            .is_err(),
        "temporary preparation requires the exact sealed Round"
    );
    assert!(
        client
            .prepare_parameter_input_from_context_v2(
                round.clone(),
                context.0.clone(),
                digest("wrong temporary context pin"),
                search_path.clone(),
                search_pin,
            )
            .await
            .is_err(),
        "temporary preparation rejects wrong protected whole source"
    );
    assert!(
        client
            .refresh_parameter_input_context_v2(foreign_round, context.0.clone(), context.1)
            .await
            .is_err(),
        "full current Round mismatch must preserve installed context"
    );
    assert!(
        client
            .refresh_parameter_input_context_v2(
                round.clone(),
                context.0.clone(),
                digest("wrong context pin")
            )
            .await
            .is_err(),
        "wrong protected source pin must preserve installed context"
    );
    assert_eq!(
        client
            .refresh_parameter_input_context_v2(round.clone(), context.0.clone(), context.1)
            .await
            .expect("exact refresh rechecks the same whole context"),
        expected_runtime
    );
    let (runtime_generation, prepared, admission, metadata) = client
        .prepare_parameter_input_v1(round.clone(), search_path.clone(), search_pin)
        .await
        .expect("actual Root whole-context preparation");
    assert_eq!(runtime_generation, expected_runtime);
    assert_eq!(
        (
            runtime_generation,
            prepared.clone(),
            admission.clone(),
            metadata.clone()
        ),
        (
            temporary.0,
            temporary.1.clone(),
            temporary.2.clone(),
            temporary.3.baseline.clone()
        )
    );
    println!(
        "actual_root_prepared_metadata={}",
        serde_json::to_string(&metadata).expect("public metadata")
    );
    assert_eq!(metadata.artifact_id, "artifact.parameters.actual-head");
    assert_eq!(metadata.model_id, material.runtime.model_id.as_str());
    assert_ne!(metadata.artifact_id, metadata.model_id);
    assert_ne!(
        material.native.model_digest,
        material.runtime.weights_digest
    );
    assert_eq!(
        metadata.model_content_digest,
        material.native.model_digest.to_string()
    );
    assert_eq!(metadata.model_generation, material.runtime.generation.get());
    assert_eq!(
        metadata.registry_head_digest,
        artifacts.registry.head_digest().to_string()
    );
    assert_eq!(
        metadata.registry_head_digest,
        admission.artifact_registry_head_digest.to_string()
    );
    assert_eq!(
        metadata.material_digest,
        Digest32::of_bytes(
            &encode_neuron_generation_material_v2(&material).expect("sole complete codec")
        )
        .to_string()
    );
    assert_eq!(metadata.context_source, context.0.to_str().expect("path"));
    assert_eq!(metadata.context_digest, context.1.to_string());
    assert_eq!(prepared.baseline_id.as_str(), metadata.artifact_id);
    assert_eq!(
        prepared.generator_profile.selected_artifact_digest,
        material.native.model_digest
    );
    assert_ne!(
        prepared.generator_profile.signals[0].evidence_digest,
        artifacts.profile.signals[0].evidence_digest
    );
    assert_ne!(prepared.eligibility_digest, Digest32::ZERO);
    assert_ne!(prepared.modulator_digest, Digest32::ZERO);
    assert!(prepared.generated.candidates.len() <= round.candidate_admissions() as usize);
    verify_actual_dataset_socket(
        &client,
        &round,
        &context,
        root.path(),
        &expected_dataset_snapshot,
        artifacts.registry.head_digest(),
    )
    .await;
    assert_ne!(
        initial_installed_artifact_head,
        artifacts.registry.head_digest(),
        "final refresh changes the held snapshot only through the original owner"
    );
    let repeated = client
        .prepare_parameter_input_v1(round.clone(), search_path, search_pin)
        .await
        .expect("read-only exact repetition");
    assert_eq!(
        repeated,
        (runtime_generation, prepared, admission, metadata)
    );
    assert_eq!(
        iteration
            .inspect_current_round()
            .await
            .expect("same original journal")
            .expect("round")
            .status
            .round,
        round
    );
    assert_eq!(
        fs::read(root.path().join("iteration.json")).expect("journal"),
        journal_before
    );
    assert_eq!(persistent_bytes(&fixture.files), durable_before);
    assert_eq!(
        fs::read(&fixture.files.ledger).expect("Ledger"),
        ledger_before
    );
    assert_eq!(
        fs::read(root.path().join("authenticated-dataset-witness.bin"))
            .expect("original Ledger witness"),
        dataset_witness_before
    );
    assert_eq!(
        [
            neuron_material.generation_store,
            neuron_material.runtime_index,
            neuron_material.witness
        ]
        .map(|path| fs::read(path).expect("V2 store")),
        physical_before
    );
    assert_eq!(artifacts.source_bytes(), source_before);
    assert_eq!(
        neuron.calls.load(std::sync::atomic::Ordering::SeqCst),
        1,
        "preparation never dispatches model/tick"
    );
    cancellation.cancel();
    serving
        .await
        .expect("server join")
        .expect("server shutdown");
    owner.await.expect("owner join").expect("owner shutdown");
    iteration_task
        .await
        .expect("iteration join")
        .expect("iteration shutdown");
    host.shutdown().expect("retire same owner");
}

fn envelopes(
    objective: Digest32,
    expires: u64,
) -> (crate::CanonicalIterationEnvelopeV1, IterationEnvelopeV1) {
    let commit = "1".repeat(40);
    let tree = "2".repeat(40);
    let grammar = digest("actual-root-prepare-grammar");
    let value = json!({"envelopeId":"actual.root.prepare.window","baseCommit":commit,"baseTree":tree,
        "objectiveDigest":objective.to_string(),"grammarDigest":grammar.to_string(),
        "allowedPaths":["parameters/neuron.sparse.rates.q24.v1"],"deniedAuthorities":["promote"],
        "maximumFiles":1,"maximumBytes":4096,"maximumCandidates":2,"wallTimeMicros":120_000_000,
        "computeBudget":{"profile":"hepta.iteration-compute-budget.v1","maximumParallelSandboxes":1,"maximumMemoryBytes":4096,"maximumProcesses":2},
        "mandatoryChecks":["original/native-receipt"],"expiresUnixMs":expires});
    let canonical = crate::CanonicalIterationEnvelopeV1::decode(
        &serde_json::to_vec(&value).expect("canonical input"),
    )
    .expect("original canonical owner");
    let execution = IterationEnvelopeV1 {
        envelope_id: id("actual.root.prepare.window"),
        base_commit: Digest32::of_bytes(commit.as_bytes()),
        base_tree: Digest32::of_bytes(tree.as_bytes()),
        objective_digest: objective,
        grammar_digest: grammar,
        maximum_files: 1,
        maximum_diff_bytes: 4096,
        maximum_candidates: 2,
        maximum_parallel_sandboxes: 1,
        expiry_unix_seconds: expires / 1000,
    };
    (canonical, execution)
}

fn principal_json(p: &AuthenticatedPrincipalV1) -> Value {
    json!({"principal_id":p.principal_id.as_str(),"credential_chain_digest":p.credential_chain_digest.to_string(),
        "signing_key_digest":p.signing_key_digest.to_string(),"scope_digest":p.scope_digest.to_string(),
        "authority_epoch":p.authority_epoch,"authenticated_at":p.authenticated_at,"expires_at":p.expires_at})
}
fn learning_trust(
    scope: JournalScope,
    now: u64,
    expires: u64,
) -> (Arc<ActivatedLearningTrustV1>, Value) {
    let mut signers = Vec::new();
    let mut encoded = Vec::new();
    for (index, role) in [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Observer,
        LearningEvidenceRoleV1::Evaluator,
        LearningEvidenceRoleV1::Selector,
    ]
    .into_iter()
    .enumerate()
    {
        let key =
            SigningKey::from_bytes(&[u8::try_from(index + 11).expect("fixed fixture byte"); 32]);
        let principal = AuthenticatedPrincipalV1 {
            principal_id: id(&format!("fixture.signer.{index}")),
            credential_chain_digest: digest(&format!("fixture.chain.{index}")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: scope.scope_digest,
            authority_epoch: 7,
            authenticated_at: now - 1,
            expires_at: expires,
        };
        let controller = id(&format!("fixture.controller.{index}"));
        encoded.push(json!({"principal":principal_json(&principal),"controller_id":controller.as_str(),"verifying_key_hex":crate::client::encode_hex(&key.verifying_key().to_bytes()),"roles":[match role {LearningEvidenceRoleV1::Generator=>"generator",LearningEvidenceRoleV1::Observer=>"observer",LearningEvidenceRoleV1::Selector=>"selector",_=>"evaluator"}],"revoked_at":null}));
        signers.push(TrustedLearningSignerV1 {
            principal,
            controller_id: controller,
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        });
    }
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("fixture.root"),
        scope_digest: scope.scope_digest,
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: now - 2,
        expires_at: expires,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("fixture.distribution"),
            generation: 1,
            effective_at: now - 1,
            trust: LearningEvidenceTrustV1 {
                scope_digest: scope.scope_digest,
                objective_digest: scope.objective_digest,
                authority_epoch: 7,
                signers,
            },
        },
        root_id: root.root_id.clone(),
        issued_at: now - 2,
        expires_at: expires,
        signature: [0; 64],
    };
    distribution.signature = key
        .sign(&distribution.signing_bytes().expect("original trust codec"))
        .to_bytes();
    (
        Arc::new(
            activate_learning_trust(&root, distribution, None, now)
                .expect("actual original public trust"),
        ),
        json!({"scope_digest":scope.scope_digest.to_string(),"objective_digest":scope.objective_digest.to_string(),"authority_epoch":7,"signers":encoded}),
    )
}
