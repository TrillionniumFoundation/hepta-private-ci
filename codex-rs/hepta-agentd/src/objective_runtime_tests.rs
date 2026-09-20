use std::fs::OpenOptions;

use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use tempfile::TempDir;

use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn record(
    run_id: &str,
    sequence: u64,
    disposition: RunStartObjectiveDispositionV1,
) -> RunStartRecordV1 {
    let objective = format!("objective:{run_id}").into_bytes();
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.objective"),
            key_epoch: 1,
            message_id: id(&format!("message.{run_id}")),
            sequence,
            expires_at_ms: 9_999_999,
            scope_digest: digest("scope"),
            signed_body_digest: digest(&format!("signed:{run_id}")),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.objective"),
            profile_revision: 1,
            profile_digest: digest("profile"),
            supplied_source_digest: digest(&format!("supplied:{run_id}")),
            intent_digest: digest("intent"),
            admitted_source_digest: digest(&format!("source:{run_id}")),
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 100_000_000,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        },
        disposition,
        snapshot: RunStartSnapshotV1 {
            run_id: id(run_id),
            objective_digest: Digest32::of_bytes(&objective),
            hard_constraint_digest: digest(&format!("hard:{run_id}")),
            preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompt"),
            artifact_set_digest: digest("artifact"),
            authority_epoch: 7,
            generation: 3,
            fence_digest: digest("fence"),
        },
        runtime_body_digest: digest(&format!("body:{run_id}")),
        objective_semantic_bytes: objective,
        objective_function_v1_digest: Digest32::of_bytes(
            b"{\"objectiveId\":\"fixture\"}",
        ),
        objective_function_v1_bytes: b"{\"objectiveId\":\"fixture\"}".to_vec(),
    }
}

fn state_with(record: RunStartRecordV1) -> (TempDir, ObjectiveHostState) {
    let temp = TempDir::new().expect("temp");
    let path = temp.path().join("journal");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("journal");
    let mut journal =
        DurableRunStartJournal::create(file, digest("binding"), 16).expect("create journal");
    journal
        .append(Digest32::ZERO, record)
        .expect("append record");
    let highest_sequences = replay_frontier(&journal).expect("frontier");
    (
        temp,
        ObjectiveHostState {
            journal,
            coordinator_generation: None,
            coordinator: None,
            highest_sequences,
        },
    )
}

#[test]
fn durable_authentication_frontier_allows_only_exact_replay() {
    let first = record("run.1", 7, RunStartObjectiveDispositionV1::Compiled);
    let (_temp, state) = state_with(first.clone());
    assert!(
        require_replay_admission(&state, &first.authentication, &first.snapshot.run_id).is_ok()
    );

    let other = record("run.2", 7, RunStartObjectiveDispositionV1::Compiled);
    assert!(
        require_replay_admission(&state, &other.authentication, &other.snapshot.run_id).is_err()
    );

    let newer = record("run.2", 8, RunStartObjectiveDispositionV1::Compiled);
    assert!(
        require_replay_admission(&state, &newer.authentication, &newer.snapshot.run_id).is_ok()
    );
}

#[test]
fn runtime_consumes_compiled_record_but_not_explicit_abstain() {
    let fence = digest("fence");
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: fence.to_string(),
    })
    .expect("coordinator");

    let compiled = record("run.1", 1, RunStartObjectiveDispositionV1::Compiled);
    ensure_runtime_record(&mut coordinator, &compiled, 1).expect("compiled run");
    assert!(coordinator.run("run.1").is_some());

    let abstain = record("run.2", 2, RunStartObjectiveDispositionV1::ExplicitAbstain);
    ensure_runtime_record(&mut coordinator, &abstain, 1).expect("abstain");
    assert!(coordinator.run("run.2").is_none());
}


#[test]
fn generation_and_fence_drift_fail_closed_before_runtime_admission() {
    let fence = digest("fence");
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: fence.to_string(),
    })
    .expect("coordinator");

    let mut wrong_generation = record("run.generation", 10, RunStartObjectiveDispositionV1::Compiled);
    wrong_generation.snapshot.generation = 4;
    assert!(ensure_runtime_record(&mut coordinator, &wrong_generation, 1).is_err());

    let mut wrong_fence = record("run.fence", 11, RunStartObjectiveDispositionV1::Compiled);
    wrong_fence.snapshot.fence_digest = digest("other-fence");
    assert!(ensure_runtime_record(&mut coordinator, &wrong_fence, 1).is_err());
}

#[test]
fn legacy_record_without_protocol_identity_is_rejected_at_final_use() {
    let fence = digest("fence");
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: fence.to_string(),
    })
    .expect("coordinator");
    let mut legacy = record("run.legacy", 12, RunStartObjectiveDispositionV1::Compiled);
    legacy.objective_function_v1_digest = Digest32::ZERO;
    legacy.objective_function_v1_bytes.clear();
    assert!(ensure_runtime_record(&mut coordinator, &legacy, 1).is_err());
}

#[cfg(unix)]
#[test]
fn recovered_authentication_rejects_revoked_and_stale_owner_trust() {
    use std::os::unix::fs::PermissionsExt;

    use codex_hepta_authbus::SignedMessageClaims;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::AgentdIdentity;
    use crate::authbus_trust::TextTrust;

    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let registered = registry.register(manifest).expect("register");
    let identity = AgentdIdentity {
        agent_id: agent,
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
    std::fs::set_permissions(
        &identity.home_root,
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private home");

    let key = SigningKey::from_bytes(&[83; 32]);
    let trust_path = identity.home_root.join("objective-trust.json");
    let write_trust = |key_epoch: u64, revoked: bool| {
        let public_key_hex = key
            .verifying_key()
            .as_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let json = serde_json::json!({
            "schema_version": 1,
            "agent_id": identity.agent_id.as_str(),
            "issuer_id": "issuer.objective",
            "key_epoch": key_epoch,
            "public_key_hex": public_key_hex,
            "revoked": revoked,
            "thread_ids": ["thread.objective"]
        });
        std::fs::write(
            &trust_path,
            serde_json::to_vec(&json).expect("trust json"),
        )
        .expect("write trust");
        std::fs::set_permissions(&trust_path, std::fs::Permissions::from_mode(0o600))
            .expect("private trust");
    };

    let now_ms = 10_000;
    let mut durable = record(
        "run.trust",
        21,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let claims = SignedMessageClaims {
        issuer_id: id("issuer.objective"),
        key_epoch: codex_hepta_types::Generation::new(1).expect("epoch"),
        message_id: id("message.run.trust"),
        subject_id: StableId::new(identity.agent_id.as_str()).expect("subject"),
        scope_digest: objective_scope(&identity),
        payload_digest: digest("signed:run.trust"),
        sequence: 21,
        expires_at_ms: now_ms + 60_000,
    };
    durable.authentication = RunStartAuthenticationV1 {
        issuer_id: claims.issuer_id.clone(),
        key_epoch: claims.key_epoch.get(),
        message_id: claims.message_id.clone(),
        sequence: claims.sequence,
        expires_at_ms: claims.expires_at_ms,
        scope_digest: claims.scope_digest,
        signed_body_digest: claims.payload_digest,
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
    };

    write_trust(/*key_epoch*/ 1, /*revoked*/ false);
    let current = TextTrust::load(&trust_path, &identity).expect("current trust");
    assert!(
        authentication_is_current(&durable, &current, &identity, now_ms)
            .expect("current authentication")
    );

    write_trust(/*key_epoch*/ 1, /*revoked*/ true);
    let revoked = TextTrust::load(&trust_path, &identity).expect("revoked trust");
    assert!(
        !authentication_is_current(&durable, &revoked, &identity, now_ms)
            .expect("revoked authentication")
    );

    write_trust(/*key_epoch*/ 2, /*revoked*/ false);
    let stale = TextTrust::load(&trust_path, &identity).expect("rotated trust");
    assert!(
        !authentication_is_current(&durable, &stale, &identity, now_ms)
            .expect("stale authentication")
    );
}

