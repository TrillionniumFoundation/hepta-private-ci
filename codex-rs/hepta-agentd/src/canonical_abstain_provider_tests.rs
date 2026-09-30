use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_agent_components::learning_ledger::RunStartAuthenticationV1;
use codex_hepta_agent_components::learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_agent_components::learning_ledger::RunStartRecordV1;
use codex_hepta_agent_components::learning_ledger::RunStartSnapshotV1;
use codex_hepta_agent_components::objective::admit_and_compile_objective_v1;
use codex_hepta_agent_components::objective::canonical_native_objective_semantic_bytes_v1;
use codex_hepta_agent_components::objective::encode_objective_function_v1;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::StableId;

use super::*;
use crate::AgentdIntelligenceProductOutcomeV1;
use crate::AgentdObjectiveOwnerInputV1;
use crate::RuntimeComposition;
use crate::intelligence_product::tests::Fixture;
use crate::intelligence_product::tests::authority_verifier;
use crate::intelligence_product::tests::digest;
use crate::intelligence_product::tests::fixture;
use crate::intelligence_product::tests::write_authority_file;

const TEST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn identity(root: &Path, generation: u64) -> AgentdIdentity {
    let root = root.canonicalize().expect("canonical root");
    let agent_id = AgentId::parse(TEST_AGENT_ID).expect("agent id");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let layout = fleet_root.layout().agent(&agent_id);
    AgentdIdentity {
        agent_id,
        layout: layout.clone(),
        spawn_generation: generation,
        fleet_root: fleet_root.as_path().to_path_buf(),
        workspace: root.join("workspace"),
        resources: ResourceBudget::local_default(),
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
    }
}

fn now_micros() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_micros(),
    )
    .expect("u64 clock")
}

fn durable_record(value: &Fixture) -> RunStartRecordV1 {
    let AgentdObjectiveOwnerInputV1::Admission {
        envelope,
        profile,
        context,
    } = &value.inputs.objective
    else {
        panic!("fixture must retain admission inputs")
    };
    let outcome =
        admit_and_compile_objective_v1(envelope, profile, context).expect("objective admission");
    let compiled = outcome.compile_result.as_ref().expect("compiled objective");
    let protocol = encode_objective_function_v1(compiled, envelope, profile, &outcome.receipt)
        .expect("objective protocol");
    let semantic = canonical_native_objective_semantic_bytes_v1(&compiled.objective);
    let observed = now_micros();
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: StableId::new("issuer.product").expect("issuer"),
            key_epoch: 1,
            message_id: StableId::new("message.product").expect("message"),
            sequence: 1,
            expires_at_ms: observed / 1_000 + 120_000,
            scope_digest: digest("auth-scope"),
            signed_body_digest: digest("signed-body"),
            signature: [0; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: StableId::new("objective-profile.product").expect("profile"),
            profile_revision: 1,
            profile_digest: digest("objective-profile"),
            supplied_source_digest: digest("supplied-source"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest("admitted-source"),
            observed_at_unix_micros: observed,
            deadline_unix_micros: observed + 120_000_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: value.request.run_id.clone(),
            objective_digest: compiled.objective.semantic_digest,
            hard_constraint_digest: digest("hard-constraints"),
            preference_state_digest: digest("preference-state"),
            model_tuple_digest: digest("model-tuple"),
            prompt_registry_digest: digest("prompt-registry"),
            artifact_set_digest: digest("artifact-set"),
            authority_epoch: value.request.snapshot.authority_epoch(),
            generation: value.request.snapshot.body_generation().get(),
            fence_digest: crate::intelligence_ingress::objective_run_fence_digest_v1(
                TEST_AGENT_ID,
                value.request.snapshot.body_generation().get() - 1,
                value.request.snapshot.body_generation().get(),
            ),
        },
        runtime_body_digest: digest("runtime-body"),
        objective_semantic_bytes: semantic,
        objective_function_v1_digest: protocol.protocol_digest(),
        objective_function_v1_bytes: protocol.canonical_bytes().to_vec(),
    }
}

fn composition(identity: &AgentdIdentity) -> RuntimeComposition {
    RuntimeComposition {
        agent_id: identity.agent_id.as_str().to_string(),
        supervisor_generation: identity.spawn_generation,
        agentd_generation: identity.spawn_generation,
        configuration_digest: digest("runtime-config").to_string(),
        ports_digest: digest("runtime-ports").to_string(),
        max_active_runs: 1,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_profile_uses_real_run_start_and_abstains_before_effectful_stages() {
    let value = fixture();
    let record = durable_record(&value);
    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let verifier = authority_verifier();
    let provider =
        AgentdDurableAbstainInvocationProviderV1::new(authority.clone(), verifier.clone())
            .expect("provider");
    let identity = identity(directory.path(), record.snapshot.generation - 1);
    let invocation = provider.build(&identity, &record).expect("invocation");
    invocation
        .validate(&identity, &record)
        .expect("durable invocation binding");

    let runner = AgentdIntelligenceProductRunnerV1::new(authority, verifier).expect("runner");
    let outcome = runner
        .prepare_for_composition(
            &composition(&identity),
            invocation.request,
            invocation.inputs,
        )
        .await
        .expect("conservative preparation");
    assert_eq!(outcome, AgentdIntelligenceProductOutcomeV1::Abstained);
}

#[test]
fn provider_rejects_stale_epoch_expired_deadline_and_relative_authority_path() {
    let value = fixture();
    let mut record = durable_record(&value);
    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let provider = AgentdDurableAbstainInvocationProviderV1::new(authority, authority_verifier())
        .expect("provider");
    let identity = identity(directory.path(), record.snapshot.generation - 1);

    let exact_fence = record.snapshot.fence_digest;
    record.snapshot.fence_digest = digest("foreign-run-fence");
    assert!(matches!(
        provider.build(&identity, &record),
        Err(AgentdError::Invalid(message)) if message.contains("not current")
    ));
    record.snapshot.fence_digest = exact_fence;
    record.snapshot.authority_epoch += 1;
    assert!(matches!(
        provider.build(&identity, &record),
        Err(AgentdError::Invalid(message)) if message.contains("authority epoch")
    ));
    record.snapshot.authority_epoch -= 1;
    record.admission.deadline_unix_micros = 1;
    assert!(matches!(
        provider.build(&identity, &record),
        Err(AgentdError::Invalid(message)) if message.contains("deadline")
    ));
    assert!(matches!(
        AgentdDurableAbstainInvocationProviderV1::new(
            PathBuf::from("relative-authority.json"),
            authority_verifier(),
        ),
        Err(AgentdError::Invalid(message)) if message.contains("absolute")
    ));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn tampered_durable_objective_is_rejected_by_existing_objective_owner_stage() {
    let value = fixture();
    let mut record = durable_record(&value);
    let directory = tempfile::tempdir().expect("directory");
    let authority = directory.path().join("authority.json");
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let verifier = authority_verifier();
    let provider =
        AgentdDurableAbstainInvocationProviderV1::new(authority.clone(), verifier.clone())
            .expect("provider");
    let identity = identity(directory.path(), record.snapshot.generation - 1);
    record.objective_semantic_bytes.push(0);
    let invocation = provider
        .build(&identity, &record)
        .expect("bounded invocation");
    let runner = AgentdIntelligenceProductRunnerV1::new(authority, verifier).expect("runner");
    assert!(matches!(
        runner
            .prepare_for_composition(
                &composition(&identity),
                invocation.request,
                invocation.inputs,
            )
            .await,
        Err(crate::AgentdIntelligenceProductError::Canonical(
            codex_hepta_agent_components::intelligence::CanonicalIntelligenceError::PortFailure {
                stage:
                    codex_hepta_agent_components::intelligence::CanonicalStageV1::ObjectiveValidated,
                ..
            }
        ))
    ));
}

#[test]
fn canonical_provider_profile_parsing_is_closed() {
    assert!(matches!(
        "durable-safe-abstain-v1".parse(),
        Ok(CanonicalIntelligenceProviderProfileV1::DurableSafeAbstainV1)
    ));
    assert!(
        "future-profile"
            .parse::<CanonicalIntelligenceProviderProfileV1>()
            .is_err()
    );
}

#[test]
fn durable_identity_binds_body_authentication_and_original_deadline() {
    let value = fixture();
    let record = durable_record(&value);
    let directory = tempfile::tempdir().expect("directory");
    let identity = identity(directory.path(), record.snapshot.generation - 1);
    let inherited = crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &record)
        .expect("Running identity");
    assert_eq!(inherited.body_digest, record.runtime_body_digest);
    assert_eq!(
        inherited.deadline_ms,
        record.admission.deadline_unix_micros / 1_000
    );
    let mut changed = record.clone();
    changed.runtime_body_digest = digest("different-durable-body");
    let changed_identity =
        crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &changed)
            .expect("changed body");
    assert_ne!(inherited.request_digest, changed_identity.request_digest);
    changed = record.clone();
    changed.authentication.sequence += 1;
    let changed_identity =
        crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &changed)
            .expect("changed authenticated replay identity");
    assert_ne!(inherited.request_digest, changed_identity.request_digest);
    changed = record.clone();
    changed.snapshot.generation = identity.spawn_generation;
    assert!(crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &changed).is_err());
    changed = record;
    changed.snapshot.fence_digest = digest("foreign-process-fence");
    assert!(crate::AgentdIntelligenceRunIdentityV1::from_run_start(&identity, &changed).is_err());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn timed_out_invocation_workers_keep_capacity_until_the_provider_retires() {
    struct BlockingProvider(std::sync::Arc<(std::sync::Mutex<bool>, std::sync::Condvar)>);
    impl crate::AgentdIntelligenceInvocationProviderV1 for BlockingProvider {
        fn build(
            &self,
            _: &AgentdIdentity,
            _: &RunStartRecordV1,
        ) -> Result<crate::AgentdIntelligenceInvocationV1, AgentdError> {
            let (released, notification) = &*self.0;
            let mut released = released.lock().expect("release lock");
            while !*released {
                released = notification.wait(released).expect("release notification");
            }
            Err(AgentdError::Protocol("provider retired".to_string()))
        }
    }
    struct ReleaseWorkers(std::sync::Arc<(std::sync::Mutex<bool>, std::sync::Condvar)>);
    impl Drop for ReleaseWorkers {
        fn drop(&mut self) {
            *self.0.0.lock().expect("release lock") = true;
            self.0.1.notify_all();
        }
    }
    let directory = tempfile::tempdir().expect("directory");
    let runner = AgentdIntelligenceProductRunnerV1::new(
        directory.path().join("unused-authority.json"),
        authority_verifier(),
    )
    .expect("runner");
    let record = durable_record(&fixture());
    let identity = identity(directory.path(), record.snapshot.generation - 1);
    let release = std::sync::Arc::new((std::sync::Mutex::new(false), std::sync::Condvar::new()));
    let release_workers = ReleaseWorkers(std::sync::Arc::clone(&release));
    let provider: std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1> =
        std::sync::Arc::new(BlockingProvider(release));
    for _ in 0..4 {
        let mut short = record.clone();
        short.admission.deadline_unix_micros = now_micros() + 50_000;
        assert!(matches!(
            runner.build_host_invocation(std::sync::Arc::clone(&provider), identity.clone(), short, /*neuron_host*/ None).await,
            Err(AgentdError::Protocol(message)) if message.contains("timed out")
        ));
    }
    let mut current = record.clone();
    current.admission.deadline_unix_micros = now_micros() + 2_000_000;
    assert!(matches!(
        runner.build_host_invocation(std::sync::Arc::clone(&provider), identity.clone(), current.clone(), /*neuron_host*/ None).await,
        Err(AgentdError::Protocol(message)) if message.contains("Busy")
    ));
    drop(release_workers);
    let retirement_deadline = std::time::Instant::now() + std::time::Duration::from_secs(1);
    loop {
        let result = runner
            .build_host_invocation(
                std::sync::Arc::clone(&provider),
                identity.clone(),
                current.clone(),
                /*neuron_host*/ None,
            )
            .await;
        match result {
            Err(AgentdError::Protocol(message)) if message == "provider retired" => break,
            Err(AgentdError::Protocol(message)) if message.contains("Busy") => {
                assert!(
                    std::time::Instant::now() < retirement_deadline,
                    "workers must retire after release"
                );
                tokio::task::yield_now().await;
            }
            _ => panic!("unexpected provider retirement result"),
        }
    }
}
