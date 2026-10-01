//! Compose a real Running Fleet owner, signed durable RunStart, and the default
//! authenticated product path. Objective wire decoding is covered separately.

#![allow(
    clippy::expect_used,
    reason = "Signed durable fixture construction and success assertions must fail on contract drift."
)]

use super::*;
use std::collections::VecDeque;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV2;
use codex_hepta_intelligence::ObjectiveRunBindingsV1;
use codex_hepta_intelligence::build_legal_candidates;
use codex_hepta_intelligence::compile_and_publish_objective_run_v1;
use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::PolicyGeneration;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_assignment_distribution_digest_v2;
use codex_hepta_intuition::canonical_candidate_identity_digest_v2;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::canonical_profile_qualification_payload_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::RunStartAppendDisposition;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdIntelligenceInvocationProviderV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::AgentdIntuitionPolicyHostV1;
use crate::AgentdIntuitionPolicyPinsV2;
use crate::AgentdIntuitionProductInvocationV1;
use crate::AgentdState;
use crate::IntuitionPolicyLearningSink;
use crate::authbus_ingress::TextIngress;
use crate::intuition_policy_serving::ServingProfile;
use crate::intuition_risk_rule_digest_v1;

fn open_rw(path: &Path) -> File {
    OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
        .expect("owner file")
}

fn write_private(path: &Path, value: &serde_json::Value) {
    std::fs::write(path, serde_json::to_vec(value).expect("owner JSON")).expect("owner file");
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).expect("private file");
}

fn live_fixture(now: u64) -> (Fixture, ActivatedLearningTrustV1) {
    let mut value = fixture();
    // Preserve the existing structured objective fixture while qualifying its
    // source-age/deadline under a profile that deliberately permits this source.
    value.inputs.objective_profile.maximum_source_age_micros = u64::MAX;
    value.inputs.objective_envelope.deadline = Some("2030-01-01T00:00:00Z".to_string());
    value.inputs.objective_context.now_unix_micros = now.checked_mul(1_000).expect("clock");
    value.inputs.objective_context.selected_profile_digest = value
        .inputs
        .objective_profile
        .digest()
        .expect("profile digest");
    let objective = admit_and_compile_objective_v1(
        &value.inputs.objective_envelope,
        &value.inputs.objective_profile,
        &value.inputs.objective_context,
    )
    .expect("live source admission")
    .compile_result
    .expect("live objective");
    let objective_digest = objective.objective.semantic_digest;
    value.inputs.utility_contributions.objective_digest = objective_digest;
    for contribution in &mut value.inputs.utility_contributions.contributions {
        contribution.objective_digest = objective_digest;
    }
    let utility = evaluate_candidates_with_policy(
        value.inputs.utility_contributions.clone(),
        value.inputs.utility_profile.clone(),
        value.inputs.utility_scalarization.clone(),
        value.inputs.utility_policy.clone(),
    )
    .expect("live utility");
    value.inputs.neural_tick.objective_digest = objective_digest;
    value.inputs.neural_tick.ndu_digest = utility.evaluation_digest_v2;
    let (_, neural) = sparse_tick(
        &value.inputs.neural_config,
        &value.inputs.neural_tick,
        /*previous*/ None,
    )
    .expect("live neural receipt");
    value.inputs.prompt_request.objective_digest = objective_digest;
    value.inputs.intuition_request.objective_digest = objective_digest;
    value.inputs.intuition_request.state_digest = neural.checkpoint_after;
    value.request.legal_candidates.state_digest = objective_digest;
    let key = SigningKey::from_bytes(&[47; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest,
        authority_epoch: snapshot.authority_epoch(),
        body_generation: generation(/*value*/ 1),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("process body snapshot");
    value.inputs.context_request.objective_digest = objective_digest;
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    value.inputs.evaluation_request.objective_digest = objective_digest;
    let context = compile(value.inputs.context_request.clone()).expect("live context");
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("live legal");
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(),
        objective_digest,
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) =
        crate::intelligence_product::evaluation_tests::evidence_fixture(&binding, now);
    value.inputs.signed_evaluation = Some(signed);
    (value, trust)
}

fn policy_trust(objective: Digest32, now: u64) -> (ActivatedLearningTrustV1, [SigningKey; 3]) {
    let keys = [
        SigningKey::from_bytes(&[11; 32]),
        SigningKey::from_bytes(&[23; 32]),
        SigningKey::from_bytes(&[37; 32]),
    ];
    let scope = digest("objective-replay-learning-scope");
    let roles = [
        LearningEvidenceRoleV1::Generator,
        LearningEvidenceRoleV1::Evaluator,
        LearningEvidenceRoleV1::Observer,
    ];
    let signers = keys
        .iter()
        .zip(roles)
        .enumerate()
        .map(|(index, (key, role))| TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(&format!("policy-signer-{index}")),
                credential_chain_digest: digest(&format!("policy-credential-{index}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: scope,
                authority_epoch: 11,
                authenticated_at: now - 100,
                expires_at: now + 60_000,
            },
            controller_id: id(&format!("policy-controller-{index}")),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        })
        .collect();
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("policy-replay-root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: now - 200,
        expires_at: now + 120_000,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("policy-replay-distribution"),
            generation: 1,
            effective_at: now - 100,
            trust: LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: objective,
                authority_epoch: 11,
                signers,
            },
        },
        root_id: root.root_id.clone(),
        issued_at: now - 150,
        expires_at: now + 60_000,
        signature: [0; 64],
    };
    signed.signature = root_key
        .sign(&signed.signing_bytes().expect("root payload"))
        .to_bytes();
    (
        activate_learning_trust(&root, signed, /*previous*/ None, now).expect("root admission"),
        keys,
    )
}

struct ChangingProvider {
    fixtures: Mutex<VecDeque<Fixture>>,
    head: Mutex<Digest32>,
    calls: AtomicU64,
    host: Arc<AgentdIntuitionPolicyHostV1>,
    verifier: Arc<LearningEvidenceVerifierV1>,
    keys: [SigningKey; 3],
    now: u64,
}

impl ChangingProvider {
    fn signed(
        &self,
        role: LearningEvidenceRoleV1,
        index: usize,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!(
                "replay-evidence-{index}:{}",
                Digest32::of_bytes(payload)
            )),
            principal_id: id(&format!("policy-signer-{index}")),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: digest("objective-replay-learning-scope"),
            objective_digest: self.verifier.objective_digest(),
            authority_epoch: 11,
            issued_at: self.now - 10,
            expires_at: self.now + 50_000,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
}

impl AgentdIntelligenceInvocationProviderV1 for ChangingProvider {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<AgentdIntelligenceInvocationV1, AgentdError> {
        self.calls.fetch_add(/*val*/ 1, Ordering::AcqRel);
        let value = self
            .fixtures
            .lock()
            .expect("fixture queue")
            .pop_front()
            .expect("one fixture per actual build");
        let request = &value.inputs.intuition_request;
        let profile = routing_profile(request, CanonicalRiskRuleV1::HighOnlySlowPath);
        let scoring = ScoringCommitmentV2 {
            model_artifact_digest: profile.scorer.model_digest,
            feature_snapshot_digest: digest("objective-replay-features"),
            feature_schema_digest: profile.scorer.feature_schema_digest,
            candidate_identity_digest: canonical_candidate_identity_digest_v2(&request.candidates)
                .expect("candidate identity"),
            scored_outputs_digest: canonical_scored_outputs_digest_v2(request).expect("scores"),
            scorer_contract_digest: profile.scorer.scorer_contract_digest,
            policy_digest: profile.policy_digest,
            policy_generation: PolicyGeneration::new(profile.generation)
                .expect("policy generation"),
        };
        let assignment = AssignmentCommitmentV2::Deterministic {
            distribution_digest: canonical_assignment_distribution_digest_v2(request)
                .expect("assignment distribution"),
        };
        let completeness = self.signed(
            LearningEvidenceRoleV1::Generator,
            /*index*/ 0,
            &canonical_completeness_evidence_payload_v1(request).expect("completeness payload"),
        );
        let qualification = self.signed(
            LearningEvidenceRoleV1::Evaluator,
            /*index*/ 1,
            &canonical_profile_qualification_payload_v1(&profile).expect("profile payload"),
        );
        let runtime = self.signed(
            LearningEvidenceRoleV1::Observer,
            /*index*/ 2,
            &canonical_runtime_commitment_payload_v2(request, &profile, &scoring, &assignment)
                .expect("runtime payload"),
        );
        let prepared = self
            .host
            .prepare_v3(
                &identity.agent_id,
                identity.spawn_generation,
                request.clone(),
                profile.clone(),
                scoring.clone(),
                assignment.clone(),
                IntuitionQualificationEvidenceV2 {
                    completeness: &completeness,
                    profile_qualification: &qualification,
                    runtime: &runtime,
                },
                record.snapshot.run_id.clone(),
                value.request.snapshot.digest(),
                self.now,
            )
            .expect("real product policy preparation");
        let decision_evidence = prepared
            .decision_signing_payload()
            .expect("Decision payload")
            .map(|payload| {
                self.signed(
                    LearningEvidenceRoleV1::Generator,
                    /*index*/ 0,
                    &payload,
                )
            });
        Ok(AgentdIntelligenceInvocationV1 {
            request: value.request,
            inputs: value.inputs,
            intuition_product: Some(AgentdIntuitionProductInvocationV1 {
                profile,
                scoring,
                assignment,
                completeness_evidence: completeness,
                profile_qualification_evidence: qualification,
                runtime_evidence: runtime,
                expected_ledger_head: *self.head.lock().expect("ledger predecessor"),
                decision_evidence,
            }),
        })
    }
}

struct RunningFixture {
    _directory: tempfile::TempDir,
    state: AgentdState,
    provider: Arc<ChangingProvider>,
    journal: DurableRunStartJournal,
    record: RunStartRecordV1,
    ledger_path: PathBuf,
    witness_path: PathBuf,
    ledger_binding: Digest32,
}

impl RunningFixture {
    async fn new() -> Self {
        let now = wall_clock_ms().expect("host clock");
        let (first, evaluation_trust) = live_fixture(now);
        let (mut second, _) = live_fixture(now);
        second.inputs.intuition_request.decision_id = id("policy:replayed-runstart");
        second.inputs.intuition_request.sequence = 2;
        let directory = tempfile::tempdir().expect("owner directory");
        let root = directory.path().canonicalize().expect("owner root");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("owner root mode");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("Fleet root");
        let registry = FleetRegistry::initialize(fleet.clone()).expect("Fleet owner");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        let registered = registry.register(manifest).expect("register");
        registry
            .compare_and_transition(
                &agent_id,
                /*expected_generation*/ 0,
                AgentLifecycle::Starting,
            )
            .expect("Starting 1");
        registry
            .compare_and_transition(
                &agent_id,
                /*expected_generation*/ 1,
                AgentLifecycle::Running,
            )
            .expect("Running 2");
        let identity = AgentdIdentity {
            agent_id,
            spawn_generation: 1,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace,
            resources: registered.manifest.resources,
            home_root: registered.layout.home_root().to_path_buf(),
            run_root: registered.layout.run_root().to_path_buf(),
            control_socket: registered.layout.agentd_control_socket().to_path_buf(),
            app_server_socket: registered.layout.app_server_socket().to_path_buf(),
            layout: registered.layout,
        };
        std::fs::set_permissions(&identity.home_root, std::fs::Permissions::from_mode(0o700))
            .expect("private home");
        let state = AgentdState::new_with_intuition_profile(
            identity.clone(),
            registry,
            /*event_capacity*/ 32,
            ServingProfile::Production,
        )
        .expect("default Production composition");
        state.refresh_generation().expect("current Fleet");
        assert_eq!(state.current_generation().expect("Fleet generation"), 2);
        let cognitive = codex_hepta_cognitive_store::DurableCognitiveStore::open(&identity.layout)
            .await
            .expect("cognitive owner");
        state
            .attach_cognitive_store(Arc::new(cognitive))
            .expect("cognitive attachment");
        state
            .mark_runtime_prerequisites_ready()
            .expect("owner readiness");
        state.mark_app_server_ready().expect("App Server readiness");

        let issuer = SigningKey::from_bytes(&[83; 32]);
        let trust_path = identity.home_root.join("objective-trust.json");
        write_private(
            &trust_path,
            &serde_json::json!({ "schema_version": 1, "agent_id": identity.agent_id.as_str(), "issuer_id": "issuer.objective", "key_epoch": 1, "public_key_hex": issuer.verifying_key().as_bytes().iter().map(|byte| format!("{byte:02x}")).collect::<String>(), "revoked": false, "thread_ids": ["thread.objective"] }),
        );
        let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
            &codex_state::SqliteConfig::from_sqlite_home(
                codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&identity.home_root)
                    .expect("owner home"),
            ),
        )
        .await
        .expect("evidence owner");
        let frontier = evidence
            .authbus_replay_frontier_digest()
            .await
            .expect("empty replay frontier");
        drop(evidence);
        let checkpoint = root.join("authbus-checkpoint.json");
        write_private(
            &checkpoint,
            &serde_json::json!({ "schema_version": 1, "agent_id": identity.agent_id.as_str(), "generation": 1, "digest": frontier.to_string() }),
        );
        assert!(
            state
                .authbus
                .set(Arc::new(
                    TextIngress::open(&identity, trust_path, checkpoint)
                        .await
                        .expect("AuthBus owner")
                ))
                .is_ok()
        );

        let authority = root.join("intelligence-authority.json");
        write_authority_file(
            &authority,
            &first.owners,
            first.request.snapshot.revocation_frontier_digest(),
        );
        let runner = AgentdIntelligenceProductRunnerV1::new(authority, authority_verifier())
            .expect("seven-owner runner")
            .with_evaluation_trust(evaluation_trust)
            .expect("evaluation root trust");
        assert!(state.intelligence_product.set(Arc::new(runner)).is_ok());
        let (trust, keys) = policy_trust(first.request.snapshot.objective_digest(), now);
        let verifier = Arc::new(trust.verifier().clone());
        let ledger_path = root.join("policy-ledger");
        let witness_path = root.join("policy-witness");
        let ledger_binding = digest("objective-replay-ledger");
        let parent = File::open(&root).expect("owner directory handle");
        let writer = LedgerWriter::from_durable(
            DurableLedger::create(
                open_rw(&ledger_path),
                ledger_binding,
                /*max_records*/ 16,
            )
            .expect("ledger owner"),
            LedgerWitnessStore::create(open_rw(&witness_path), ledger_binding)
                .expect("independent witness"),
            trust,
            &parent,
            &parent,
        )
        .expect("sole writer");
        let profile = routing_profile(
            &first.inputs.intuition_request,
            CanonicalRiskRuleV1::HighOnlySlowPath,
        );
        let pins = AgentdIntuitionPolicyPinsV2 {
            policy_profile_digest: canonical_policy_profile_digest_v1(&profile)
                .expect("profile digest"),
            policy_digest: profile.policy_digest,
            policy_generation: PolicyGeneration::new(profile.generation)
                .expect("policy generation"),
            objective_class_digest: profile.objective_class_digest,
            model_artifact_digest: profile.scorer.model_digest,
            scorer_contract_digest: profile.scorer.scorer_contract_digest,
            calibration_artifact_digest: profile.calibration_artifact_digest,
            ood_artifact_digest: profile.ood_artifact_digest,
            risk_rule_digest: intuition_risk_rule_digest_v1(profile.risk_rule),
            rng_owner_digest: None,
        };
        let host = Arc::new(
            AgentdIntuitionPolicyHostV1::new_product(
                identity.agent_id.clone(),
                identity.spawn_generation,
                verifier.clone(),
                pins,
                Arc::new(IntuitionPolicyLearningSink::new(writer)),
            )
            .expect("default product host"),
        );
        assert!(state.intuition_policy.set(host.clone()).is_ok());

        let mut scope = b"hepta:agentd:signed-objective:v1\0".to_vec();
        scope.extend_from_slice(identity.agent_id.as_str().as_bytes());
        let claims = SignedMessageClaims {
            issuer_id: id("issuer.objective"),
            key_epoch: generation(/*value*/ 1),
            message_id: id("objective-replay-request"),
            subject_id: id(identity.agent_id.as_str()),
            scope_digest: Digest32::of_bytes(&scope),
            payload_digest: digest("signed-objective-replay-body"),
            sequence: 1,
            expires_at_ms: now + 60_000,
        };
        let message = SignedMessage {
            signature: issuer.sign(&claims.signing_bytes()).to_bytes(),
            claims,
        };
        let mut journal = DurableRunStartJournal::create(
            open_rw(&root.join("run-start-journal")),
            digest("objective-replay-runstart-owner"),
            /*max_records*/ 16,
        )
        .expect("RunStart owner");
        compile_and_publish_objective_run_v1(
            &first.inputs.objective_envelope,
            &first.inputs.objective_profile,
            &first.inputs.objective_context,
            ObjectiveRunBindingsV1 {
                authentication: RunStartAuthenticationV1 {
                    issuer_id: message.claims.issuer_id,
                    key_epoch: message.claims.key_epoch.get(),
                    message_id: message.claims.message_id,
                    sequence: message.claims.sequence,
                    expires_at_ms: message.claims.expires_at_ms,
                    scope_digest: message.claims.scope_digest,
                    signed_body_digest: message.claims.payload_digest,
                    signature: message.signature,
                },
                run_id: first.request.run_id.clone(),
                runtime_body_digest: digest("runtime-body"),
                preference_state_digest: digest("preference"),
                model_tuple_digest: digest("model-tuple"),
                prompt_registry_digest: digest("prompt-registry"),
                artifact_set_digest: digest("artifacts"),
                authority_epoch: first.request.snapshot.authority_epoch(),
                generation: state.current_generation().expect("current lifecycle"),
                fence_digest: Digest32::from_str(&crate::state::objective_run_fence(
                    &identity, /*current_generation*/ 2,
                ))
                .expect("lifecycle fence"),
                expected_run_start_head: Digest32::ZERO,
            },
            &mut journal,
        )
        .expect("signed current RunStart publication");
        let record = journal
            .get(&first.request.run_id)
            .expect("RunStart lookup")
            .expect("published RunStart")
            .clone();
        let provider = Arc::new(ChangingProvider {
            fixtures: Mutex::new(VecDeque::from([first, second])),
            head: Mutex::new(Digest32::ZERO),
            calls: AtomicU64::default(),
            host,
            verifier,
            keys,
            now,
        });
        assert!(state.intelligence_invocation.set(provider.clone()).is_ok());
        Self {
            _directory: directory,
            state,
            provider,
            journal,
            record,
            ledger_path,
            witness_path,
            ledger_binding,
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn running_lifecycle_generation_is_distinct_from_canonical_body_generation() {
    let fixture = RunningFixture::new().await;
    assert_eq!(fixture.record.snapshot.generation, 2);
    assert_eq!(fixture.state.identity().spawn_generation, 1);
    let admitted = fixture
        .state
        .start_canonical_intelligence(&fixture.record)
        .await
        .expect("Running 2 must admit its process body 1")
        .expect("canonical product outcome");
    assert_eq!(admitted.disposition(), "canonical_ready");
    assert_eq!(
        admitted
            .policy_receipt()
            .expect("authenticated product receipt")
            .learning
            .as_ref()
            .expect("selected durable fact")
            .sequence
            .get(),
        1
    );
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stale_runstart_rejects_before_rebuilding_owner_invocation() {
    let fixture = RunningFixture::new().await;
    let ledger_before = std::fs::read(&fixture.ledger_path).expect("ledger before");
    let witness_before = std::fs::read(&fixture.witness_path).expect("witness before");
    for field in ["generation", "fence"] {
        let mut stale = fixture.record.clone();
        match field {
            "generation" => stale.snapshot.generation = 1,
            "fence" => stale.snapshot.fence_digest = digest("wrong-fence"),
            _ => unreachable!(),
        }
        assert!(matches!(
            fixture.state.start_canonical_intelligence(&stale).await,
            Err(AgentdError::GenerationFenced(_))
        ));
    }
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 0);
    {
        let mut fixtures = fixture.provider.fixtures.lock().expect("fixture queue");
        let first = fixtures.front_mut().expect("first owner invocation");
        let snapshot = &first.request.snapshot;
        first.request.snapshot =
            CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
                objective_digest: snapshot.objective_digest(),
                authority_epoch: snapshot.authority_epoch(),
                body_generation: generation(/*value*/ 2),
                configuration_digest: snapshot.configuration_digest(),
                revocation_frontier_digest: snapshot.revocation_frontier_digest(),
                owner_bindings: first.owners.clone(),
            })
            .expect("wrong process body");
    }
    assert!(matches!(
        fixture
            .state
            .start_canonical_intelligence(&fixture.record)
            .await,
        Err(AgentdError::Invalid(_))
    ));
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 1);
    assert_eq!(
        std::fs::read(&fixture.ledger_path).expect("ledger after"),
        ledger_before
    );
    assert_eq!(
        std::fs::read(&fixture.witness_path).expect("witness after"),
        witness_before
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exact_runstart_replay_rejects_changed_policy_material_before_append() {
    let mut fixture = RunningFixture::new().await;
    let first = fixture
        .state
        .start_canonical_intelligence(&fixture.record)
        .await
        .expect("first admission")
        .expect("first canonical result");
    let first_receipt = first
        .policy_receipt()
        .expect("first policy receipt")
        .clone();
    let first_append = first_receipt
        .learning
        .as_ref()
        .expect("first selected append");
    assert_eq!(first_append.sequence.get(), 1);
    let ledger_after_first = std::fs::read(&fixture.ledger_path).expect("ledger after first");
    let witness_after_first = std::fs::read(&fixture.witness_path).expect("witness after first");
    *fixture.provider.head.lock().expect("predecessor") = first_append.chain_digest;
    let publication = fixture
        .journal
        .append(fixture.journal.head_digest(), fixture.record.clone())
        .expect("exact authenticated publication replay");
    assert_eq!(
        publication.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    let error = fixture
        .state
        .start_canonical_intelligence(&fixture.record)
        .await
        .expect_err("existing run requires durable handoff reconciliation");
    let AgentdError::Invalid(code) = error else {
        panic!("retry must reject before creating a second policy fact");
    };
    assert_eq!(
        code,
        "agentd.intuition.service.run_admission_replay_requires_reconciliation"
    );
    assert_eq!(
        std::fs::read(&fixture.ledger_path).expect("ledger after replay"),
        ledger_after_first
    );
    assert_eq!(
        std::fs::read(&fixture.witness_path).expect("witness after replay"),
        witness_after_first
    );
    assert_eq!(fixture.provider.calls.load(Ordering::Acquire), 1);

    let RunningFixture {
        _directory,
        state,
        provider,
        journal,
        record,
        ledger_path,
        witness_path,
        ledger_binding,
    } = fixture;
    drop(state);
    drop(provider);
    drop(journal);
    let witness = LedgerWitnessStore::recover(open_rw(&witness_path), ledger_binding)
        .expect("independent witness reopen");
    let anchor = witness.frontier().expect("acknowledged frontier").anchor;
    assert_eq!(anchor.sequence, 1);
    let ledger = DurableLedger::recover(
        open_rw(&ledger_path),
        ledger_binding,
        /*max_records*/ 16,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: anchor.sequence,
            chain_digest: anchor.chain_digest,
        }),
    )
    .expect("durable policy reopen");
    let records = ledger.records().expect("authoritative facts");
    assert_eq!(records.len(), 1);
    assert!(records.iter().all(|stored| matches!(&stored.event, LedgerEvent::AuthenticatedDecisionV2(decision) if decision.episode_id == record.snapshot.run_id)));
}

#[path = "intelligence_objective_host_replay_tests.rs"]
mod host_replay;
