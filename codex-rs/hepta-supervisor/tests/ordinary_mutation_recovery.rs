#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::DurableMutationPhaseV1;
use codex_hepta_supervisor::DurableMutationStatusV1;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordHealth;
use codex_hepta_supervisor::SupervisordMethod;
use codex_hepta_supervisor::SupervisordMutation;
use codex_hepta_supervisor::mark_mutation_ambiguous;
use codex_hepta_supervisor::mark_mutation_effect_started;
use codex_hepta_supervisor::prepare_mutation;
use codex_hepta_supervisor::read_mutation_status;
use codex_hepta_supervisor::run_supervisord;
use pretty_assertions::assert_eq;
use tokio_util::sync::CancellationToken;

struct Fleet {
    _directory: tempfile::TempDir,
    root: HeptaFleetRoot,
    agent: AgentId,
    release: ReleaseId,
    run_root: PathBuf,
    client: SupervisordClient,
    cancellation: CancellationToken,
}

impl Fleet {
    fn new(program: &str) -> Self {
        let directory = tempfile::Builder::new()
            .prefix("h7-mutation-")
            .tempdir_in("/tmp")
            .expect("short Unix socket directory");
        let root = HeptaFleetRoot::parse(directory.path().join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(root.clone()).expect("initialize registry");
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("Agent id");
        let record = registry
            .register(
                AgentManifest::new(
                    agent.clone(),
                    WorkspaceBinding::new(workspace.canonicalize().expect("workspace path"), &root)
                        .expect("workspace binding"),
                    ResourceBudget::local_default(),
                )
                .expect("manifest"),
            )
            .expect("register agent");
        let source = directory.path().join("agentd");
        std::fs::write(&source, program).expect("process fixture");
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o700))
            .expect("executable fixture");
        let release = ReleaseId::parse("release-v1").expect("release");
        registry
            .install_release(release.clone(), &source, Vec::new())
            .expect("install release");
        registry
            .allow_release(&agent, &release)
            .expect("allow release");
        let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())
            .expect("client");
        Self {
            _directory: directory,
            root,
            agent,
            release,
            run_root: record.layout.run_root().to_path_buf(),
            client,
            cancellation: CancellationToken::new(),
        }
    }

    async fn wait_for_mutation_status(
        &self,
        request_id: u64,
        phase: DurableMutationPhaseV1,
    ) -> DurableMutationStatusV1 {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let result = self
                .client
                .ordinary_mutation_status(self.agent.clone(), request_id)
                .await;
            match result {
                Ok(Some(status)) if status.phase == phase => return status,
                result => {
                    assert!(
                        Instant::now() < deadline,
                        "durable outcome {phase:?} was not observed: {result:?}"
                    );
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            }
        }
    }

    async fn wait_for_socket(&self) -> SupervisordHealth {
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            match self.client.health().await {
                Ok(health) => return health,
                Err(error) => {
                    assert!(Instant::now() < deadline, "daemon failed to bind: {error}");
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            }
        }
    }
}

impl Drop for Fleet {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

#[tokio::test(flavor = "current_thread")]
async fn socket_reconnect_preserves_outcome_and_emergency_kill_preserves_ambiguity() {
    let fleet = Fleet::new("#!/bin/sh\nexec /bin/sleep 20\n");
    let daemon = tokio::spawn(run_supervisord(
        fleet.root.clone(),
        fleet.cancellation.clone(),
    ));
    let health = fleet.wait_for_socket().await;
    assert!(health.ready);
    let before = fleet
        .client
        .snapshot(fleet.agent.clone())
        .await
        .expect("initial snapshot");
    let start_id = fleet.client.reserve_request_id();
    let start_method = SupervisordMethod::Start {
        fence: before.control_fence,
        release_id: fleet.release.clone(),
    };
    let started = fleet
        .client
        .execute_mutation_with_request_id(start_id, start_method.clone())
        .await
        .expect("start process");
    assert!(started.agent.active);
    assert!(started.agent.process_id.is_some());
    let committed = read_mutation_status(&fleet.run_root)
        .expect("read durable outcome")
        .expect("outcome");
    assert_eq!(committed.phase, DurableMutationPhaseV1::Committed);
    // Each client method opens a new socket: a disconnected response consumer
    // recovers the full durable outcome without issuing another physical spawn.
    assert_eq!(
        fleet
            .client
            .ordinary_mutation_status(fleet.agent.clone(), start_id)
            .await
            .expect("reconnect and query"),
        Some(committed.clone())
    );
    let replay = fleet
        .client
        .execute_mutation_with_request_id(start_id, start_method)
        .await
        .expect_err("old fence cannot spawn again");
    assert!(replay.to_string().contains("stale_control_fence"));
    assert_eq!(
        fleet
            .client
            .snapshot(fleet.agent.clone())
            .await
            .expect("same owned process"),
        started.agent
    );
    assert_eq!(
        read_mutation_status(&fleet.run_root).expect("unchanged journal"),
        Some(committed)
    );

    let pending_id = fleet.client.reserve_request_id();
    let pending = prepare_mutation(
        &fleet.run_root,
        pending_id,
        &fleet.agent,
        health.supervisor_epoch.as_str(),
        SupervisordMutation::Restart,
        started.agent.control_fence.state_digest.as_str(),
        /*intent_sequence*/ 2,
    )
    .expect("inject a crash after durable admission");
    mark_mutation_effect_started(&fleet.run_root, &pending.idempotency_key)
        .expect("persist effect boundary");
    let ambiguous = mark_mutation_ambiguous(
        &fleet.run_root,
        &pending.idempotency_key,
        /*observed_state_digest*/ None,
        "lost driver result",
    )
    .expect("persist crash ambiguity");
    let rejected = fleet
        .client
        .restart(started.agent.control_fence.clone())
        .await
        .expect_err("no replay of ambiguous operation");
    assert!(rejected.to_string().contains("mutation_journal_rejected"));
    assert!(
        !fleet
            .client
            .health()
            .await
            .expect("live recovery health")
            .ready
    );

    let kill_id = fleet.client.reserve_request_id();
    let killed = fleet
        .client
        .execute_mutation_with_request_id(
            kill_id,
            SupervisordMethod::Kill {
                fence: started.agent.control_fence,
            },
        )
        .await
        .expect("emergency kill bypasses pending ordinary journal");
    assert_eq!(killed.operation, SupervisordMutation::Kill);
    assert_eq!(
        fleet
            .wait_for_mutation_status(pending_id, DurableMutationPhaseV1::Ambiguous)
            .await,
        ambiguous.clone()
    );
    let kill_status = fleet
        .wait_for_mutation_status(kill_id, DurableMutationPhaseV1::Committed)
        .await;
    assert_eq!(kill_status.phase, DurableMutationPhaseV1::Committed);
    assert_eq!(
        read_mutation_status(&fleet.run_root).expect("preserved crash evidence"),
        Some(ambiguous)
    );
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if !fleet
            .client
            .snapshot(fleet.agent.clone())
            .await
            .expect("exit snapshot")
            .active
        {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "owned process did not exit after kill"
        );
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    fleet.cancellation.cancel();
    daemon
        .await
        .expect("join daemon")
        .expect("clean daemon shutdown");
}

#[tokio::test(flavor = "current_thread")]
async fn startup_pending_ordinary_mutation_is_reachable_but_never_ready_or_replayed() {
    let fleet = Fleet::new("#!/bin/sh\nexec /bin/sleep 20\n");
    let request_id = 7;
    let pending = prepare_mutation(
        &fleet.run_root,
        request_id,
        &fleet.agent,
        "prior-owner",
        SupervisordMutation::Start,
        &"00".repeat(32),
        /*intent_sequence*/ 1,
    )
    .expect("persist prepared operation");
    let daemon = tokio::spawn(run_supervisord(
        fleet.root.clone(),
        fleet.cancellation.clone(),
    ));
    assert!(!fleet.wait_for_socket().await.ready);
    let snapshot = fleet
        .client
        .snapshot(fleet.agent.clone())
        .await
        .expect("recovery snapshot");
    assert!(!snapshot.active);
    assert_eq!(
        fleet
            .client
            .ordinary_mutation_status(fleet.agent.clone(), request_id)
            .await
            .expect("query pending operation"),
        Some(pending)
    );
    let error = fleet
        .client
        .start(snapshot.control_fence, fleet.release.clone())
        .await
        .expect_err("pending admission cannot be replayed");
    assert!(error.to_string().contains("recovery_observation_required"));
    assert!(
        !fleet
            .client
            .snapshot(fleet.agent.clone())
            .await
            .expect("still stopped")
            .active
    );
    fleet.cancellation.cancel();
    daemon
        .await
        .expect("join daemon")
        .expect("clean daemon shutdown");
}

#[tokio::test(flavor = "current_thread")]
async fn a_real_spawn_failure_immediately_blocks_readiness_and_further_mutations() {
    let fleet = Fleet::new("#!/definitely-missing-hepta-interpreter\n");
    let daemon = tokio::spawn(run_supervisord(
        fleet.root.clone(),
        fleet.cancellation.clone(),
    ));
    assert!(fleet.wait_for_socket().await.ready);
    let before = fleet
        .client
        .snapshot(fleet.agent.clone())
        .await
        .expect("initial snapshot");
    let request_id = fleet.client.reserve_request_id();
    let error = fleet
        .client
        .execute_mutation_with_request_id(
            request_id,
            SupervisordMethod::Start {
                fence: before.control_fence,
                release_id: fleet.release.clone(),
            },
        )
        .await
        .expect_err("Unix spawn fails after persisted effect boundary");
    // The transport can expire before the owner completes its journal writes.
    // Only the exact durable outcome determines whether the effect is known;
    // an error string is not a recovery witness.
    assert!(!error.to_string().is_empty());
    let outcome = fleet
        .wait_for_mutation_status(request_id, DurableMutationPhaseV1::Ambiguous)
        .await;
    assert_eq!(outcome.phase, DurableMutationPhaseV1::Ambiguous);
    assert_eq!(
        fleet
            .wait_for_mutation_status(request_id, DurableMutationPhaseV1::Ambiguous)
            .await,
        outcome
    );
    assert!(
        !fleet
            .client
            .health()
            .await
            .expect("health after spawn failure")
            .ready
    );
    let after = fleet
        .client
        .snapshot(fleet.agent.clone())
        .await
        .expect("failed spawn snapshot");
    assert!(!after.active);
    let retry = fleet
        .client
        .start(after.control_fence, fleet.release.clone())
        .await
        .expect_err("recovery gate precedes another physical spawn");
    assert!(retry.to_string().contains("recovery_observation_required"));
    fleet.cancellation.cancel();
    daemon
        .await
        .expect("join daemon")
        .expect("clean daemon shutdown");
}
