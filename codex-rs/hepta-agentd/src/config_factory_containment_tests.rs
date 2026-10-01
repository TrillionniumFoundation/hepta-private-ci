//! Exercise the installed canonical provider, rather than a watchdog helper.

use std::io::Read;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::AuthorityPosture;

use super::*;
use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdIntelligenceInvocationPolicyV1;
use crate::AgentdIntelligenceInvocationV1;
use crate::HostOwnedAgentdIntelligenceInvocationProviderV1;

const CHILD_CASE: &str = "HEPTA_CANONICAL_FACTORY_CONTAINMENT_CHILD_CASE";
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn registered_config(root: &std::path::Path) -> AgentdConfig {
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse(AGENT_ID).expect("agent identity");
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("workspace binding");
    let manifest = AgentManifest::new(agent_id.clone(), binding, ResourceBudget::local_default())
        .expect("manifest");
    let record = registry.register(manifest).expect("registration");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("spawn generation");
    AgentdConfig::load(
        fleet_path,
        agent_id,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .expect("registered configuration")
}

fn guarded_runner(
    root: &std::path::Path,
    value: &Fixture,
    grace: Duration,
) -> Arc<AgentdIntelligenceProductRunnerV1> {
    let manifest_path = root.join("authority.json");
    write_authority_file(
        &manifest_path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let manifest: IntelligenceAuthorityFileV1 =
        serde_json::from_slice(&std::fs::read(&manifest_path).expect("test manifest bytes"))
            .expect("signed test manifest");
    let guard = crate::IntelligenceAuthorityRollbackGuardV1::open(
        &root.join("authority-floor.json"),
        manifest.authority_epoch,
        intelligence_authority_manifest_digest_v1(&manifest).expect("manifest digest"),
    )
    .expect("independently provisioned rollback floor");
    Arc::new(
        AgentdIntelligenceProductRunnerV1::new(manifest_path, authority_verifier())
            .expect("runner")
            .with_authority_rollback_guard(Arc::new(guard))
            .expect("rollback boundary")
            .with_hard_timeout_process_exit(grace)
            .expect("nonzero process containment"),
    )
}

fn run_start(
    request: &CanonicalIntelligenceRunRequestV1,
    identity: &crate::AgentdIdentity,
    case: &str,
) -> RunStartRecordV1 {
    let now = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis(),
    )
    .expect("Unix milliseconds");
    let deadline_ms = now
        + if matches!(case, "manual" | "manual-grace") {
            2_000
        } else {
            200
        };
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.factory-test"),
            key_epoch: 1,
            message_id: id("message.factory-test"),
            sequence: 1,
            expires_at_ms: now + 10_000,
            scope_digest: digest("factory-scope"),
            signed_body_digest: digest("factory-signed-body"),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.factory-test"),
            profile_revision: 1,
            profile_digest: digest("factory-profile"),
            supplied_source_digest: digest("factory-supplied-source"),
            intent_digest: digest("factory-intent"),
            admitted_source_digest: digest("factory-admitted-source"),
            observed_at_unix_micros: now * 1_000,
            deadline_unix_micros: deadline_ms * 1_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: request.run_id.clone(),
            objective_digest: request.snapshot.objective_digest(),
            hard_constraint_digest: digest("factory-hard-constraints"),
            preference_state_digest: digest("factory-preferences"),
            model_tuple_digest: digest("factory-model"),
            prompt_registry_digest: digest("factory-prompts"),
            artifact_set_digest: digest("factory-artifacts"),
            authority_epoch: request.snapshot.authority_epoch(),
            generation: identity.spawn_generation + 1,
            fence_digest: crate::objective_run_fence_digest_v1(
                identity.agent_id.as_str(),
                identity.spawn_generation,
                identity.spawn_generation + 1,
            ),
        },
        runtime_body_digest: digest("factory-runtime-body"),
        objective_semantic_bytes: b"factory-test-objective".to_vec(),
        objective_function_v1_digest: digest("factory-objective-protocol"),
        objective_function_v1_bytes: b"factory-test-objective-protocol".to_vec(),
    }
}

fn execute_child(case: &str) {
    let directory = tempfile::tempdir().expect("temporary host root");
    let root = directory
        .path()
        .canonicalize()
        .expect("canonical host root");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private host root");
    }
    let value = fixture();
    let request = value.request.clone();
    let returns = matches!(case, "returned" | "failed");
    let grace = if returns {
        Duration::from_nanos(1)
    } else if case == "manual-grace" {
        Duration::from_secs(2)
    } else {
        Duration::from_millis(30)
    };
    let runner = guarded_runner(&root, &value, grace);
    let invocation = Mutex::new(Some(AgentdIntelligenceInvocationV1 {
        request: value.request,
        inputs: value.inputs,
    }));
    let (entered, observed) = std::sync::mpsc::sync_channel(1);
    let factory_case = case.to_string();
    let factory = move |_identity: &crate::AgentdIdentity, _record: &RunStartRecordV1| {
        println!("canonical-factory-entered:{factory_case}");
        if matches!(factory_case.as_str(), "manual" | "manual-grace") {
            // Independent of Tokio and the later two-second RunStart fence.
            let _sentry = std::thread::spawn(|| {
                std::thread::sleep(Duration::from_millis(500));
                std::process::exit(71);
            });
        }
        entered.send(()).expect("record factory entry");
        match factory_case.as_str() {
            "returned" => Ok(invocation
                .lock()
                .expect("fixture lock")
                .take()
                .expect("invocation")),
            "failed" => Err(AgentdError::Protocol("test factory rejection".to_string())),
            _ => loop {
                std::thread::park();
            },
        }
    };
    let config = registered_config(&root);
    let config = if matches!(case, "manual" | "manual-grace") {
        let provider = HostOwnedAgentdIntelligenceInvocationProviderV1::with_policy(
            factory,
            AgentdIntelligenceInvocationPolicyV1 {
                timeout: Duration::from_millis(40),
                max_in_flight: 1,
                hard_timeout_process_exit_grace: (case == "manual-grace")
                    .then_some(Duration::from_millis(30)),
            },
        )
        .expect("standalone compatibility policy");
        config
            .with_intelligence_product_runner(runner)
            .expect("manual runner installation")
            .with_intelligence_invocation_provider(Arc::new(provider))
            .expect("manual provider installation")
    } else {
        config
            .with_canonical_intelligence_profile(runner, factory)
            .expect("atomic canonical profile installation")
    };
    let runner = config
        .intelligence_product_runner()
        .expect("installed runner");
    let provider = config
        .intelligence_invocation_provider()
        .expect("installed provider");
    let identity = config.identity().clone();
    let record = run_start(&request, &identity, case);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()
        .expect("runtime");
    runtime.block_on(async {
        let mut caller = tokio::spawn(async move {
            runner
                .build_host_invocation(provider, identity, record)
                .await
        });
        observed
            .recv_timeout(Duration::from_secs(2))
            .expect("actual factory entered");
        match case {
            "abort" => {
                caller.abort();
                assert!(matches!(caller.await, Err(error) if error.is_cancelled()));
            }
            "timeout" => {
                assert!(
                    tokio::time::timeout(Duration::from_millis(10), &mut caller)
                        .await
                        .is_err()
                );
                drop(caller);
            }
            "returned" => {
                caller
                    .await
                    .expect("caller joined")
                    .expect("factory returned");
            }
            "failed" => {
                assert!(matches!(
                    caller.await.expect("caller joined"),
                    Err(AgentdError::Protocol(reason)) if reason == "test factory rejection"
                ));
            }
            "waiting" | "manual" | "manual-grace" => {
                assert!(caller.await.expect("caller joined").is_err());
            }
            _ => panic!("unknown child case"),
        }
    });
    // Keep the runtime alive long enough to observe containment or the sentry.
    let observation = if case == "manual-grace" {
        Duration::from_millis(600)
    } else {
        Duration::from_millis(400)
    };
    std::thread::sleep(observation);
    assert!(
        returns,
        "surviving actual factory escaped canonical containment"
    );
}

#[test]
fn installed_canonical_factory_contains_actual_work_after_caller_detaches() {
    if let Ok(case) = std::env::var(CHILD_CASE) {
        execute_child(&case);
        return;
    }
    let executable = std::env::current_exe().expect("test executable");
    let test_name = format!(
        "{}::installed_canonical_factory_contains_actual_work_after_caller_detaches",
        module_path!().split_once("::").expect("crate prefix").1,
    );
    for case in [
        "waiting",
        "timeout",
        "abort",
        "manual",
        "manual-grace",
        "returned",
        "failed",
    ] {
        let mut child = Command::new(&executable)
            .args(["--exact", &test_name, "--nocapture"])
            .env(CHILD_CASE, case)
            .stdout(Stdio::piped())
            .spawn()
            .expect("containment child");
        let deadline = Instant::now() + Duration::from_secs(5);
        let status = loop {
            if let Some(status) = child.try_wait().expect("observe child") {
                break status;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("canonical factory child did not terminate: {case}");
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        let mut stdout = String::new();
        child
            .stdout
            .take()
            .expect("child output")
            .read_to_string(&mut stdout)
            .expect("child output bytes");
        assert_eq!(
            stdout
                .matches(&format!("canonical-factory-entered:{case}"))
                .count(),
            1,
            "actual factory entry count: {case}\n{stdout}"
        );
        let expected = if matches!(case, "returned" | "failed") {
            0
        } else {
            70
        };
        assert_eq!(
            status.code(),
            Some(expected),
            "canonical factory case: {case}"
        );
    }
}
