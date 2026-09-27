use std::sync::Mutex;

use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartCheckpointOwnerV1;
use codex_hepta_learning_ledger::RunStartCheckpointV1;
use codex_hepta_learning_ledger::RunStartJournal;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_learning_ledger::RunStartStoreError;
use tempfile::TempDir;

use super::*;
use crate::AgentRunCoordinator;
use crate::RuntimeComposition;

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
        objective_function_v1_digest: Digest32::of_bytes(b"{\"objectiveId\":\"fixture\"}"),
        objective_function_v1_bytes: b"{\"objectiveId\":\"fixture\"}".to_vec(),
    }
}

struct TestCheckpoint(Mutex<RunStartCheckpointV1>);

impl TestCheckpoint {
    fn new() -> Self {
        Self(Mutex::new(RunStartCheckpointV1::ZERO))
    }
}

impl RunStartCheckpointOwnerV1 for TestCheckpoint {
    fn current_checkpoint(&self) -> Result<RunStartCheckpointV1, RunStartStoreError> {
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| RunStartStoreError::Poisoned)
    }

    fn compare_and_swap(
        &self,
        expected: RunStartCheckpointV1,
        next: RunStartCheckpointV1,
    ) -> Result<(), RunStartStoreError> {
        let mut current = self.0.lock().map_err(|_| RunStartStoreError::Poisoned)?;
        if *current == next {
            return Ok(());
        }
        if *current != expected || !next.is_well_formed() {
            return Err(RunStartStoreError::RollbackDetected);
        }
        *current = next;
        Ok(())
    }
}

fn state_with(record: RunStartRecordV1) -> (TempDir, ObjectiveHostState) {
    let temp = TempDir::new().expect("temp");
    let mut journal = DurableRunStartStore::open(
        temp.path().join("run-start"),
        digest("binding"),
        16,
        Box::new(TestCheckpoint::new()),
    )
    .expect("create journal");
    journal
        .append_run_start(Digest32::ZERO, record)
        .expect("append record");
    let highest_sequences = replay_frontier(&journal).expect("frontier");
    (
        temp,
        ObjectiveHostState {
            journal,
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
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        max_active_runs: 16,
    })
    .expect("coordinator");

    let compiled = record("run.1", 1, RunStartObjectiveDispositionV1::Compiled);
    coordinator
        .start_revalidated_run_start(1, &compiled)
        .expect("compiled run");
    assert!(coordinator.run("run.1").is_some());

    let abstain = record("run.2", 2, RunStartObjectiveDispositionV1::ExplicitAbstain);
    assert!(
        coordinator
            .start_revalidated_run_start(1, &abstain)
            .is_err()
    );
    assert!(coordinator.run("run.2").is_none());
}

#[test]
fn legacy_record_without_protocol_identity_is_rejected_at_final_use() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        max_active_runs: 16,
    })
    .expect("coordinator");
    let mut legacy = record("run.legacy", 12, RunStartObjectiveDispositionV1::Compiled);
    legacy.objective_function_v1_digest = Digest32::ZERO;
    legacy.objective_function_v1_bytes.clear();
    assert!(coordinator.start_revalidated_run_start(1, &legacy).is_err());
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
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
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
    std::fs::set_permissions(&identity.home_root, std::fs::Permissions::from_mode(0o700))
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
        std::fs::write(&trust_path, serde_json::to_vec(&json).expect("trust json"))
            .expect("write trust");
        std::fs::set_permissions(&trust_path, std::fs::Permissions::from_mode(0o600))
            .expect("private trust");
    };

    let now_ms = 10_000;
    let mut durable = record("run.trust", 21, RunStartObjectiveDispositionV1::Compiled);
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

#[test]
fn sub_millisecond_deadline_never_extends_final_use() {
    assert!(deadline_is_expired(1_000_001, 1_000));
    assert!(!deadline_is_expired(1_001_000, 1_000));
}

#[test]
fn product_ingress_uses_the_registered_protocol_capacity() {
    assert_eq!(
        AuthBusObjectiveBody::MAX_SOURCE_ENVELOPE_JSON_BYTES,
        32 * 1024
    );
    assert_eq!(
        AuthBusObjectiveBody::MAX_CANONICAL_BODY_JSON_BYTES,
        48 * 1024
    );
}

#[test]
fn compiled_admission_exposes_exact_execution_binding_but_abstain_does_not() {
    let compiled = record("run.binding", 31, RunStartObjectiveDispositionV1::Compiled);
    let binding = objective_execution_binding(&compiled, "compiled").expect("compiled binding");
    assert_eq!(
        binding.request_digest,
        compiled.admission.admitted_source_digest.to_string()
    );
    assert_eq!(
        binding.objective_digest,
        compiled.snapshot.objective_digest.to_string()
    );
    assert_eq!(
        binding.body_digest,
        compiled.runtime_body_digest.to_string()
    );
    assert_eq!(
        binding.artifact_set_digest,
        compiled.snapshot.artifact_set_digest.to_string()
    );
    assert_eq!(binding.authority_epoch, compiled.snapshot.authority_epoch);
    assert_eq!(binding.generation, compiled.snapshot.generation);
    assert_eq!(
        binding.fence_digest,
        compiled.snapshot.fence_digest.to_string()
    );
    assert_eq!(binding.deadline_ms, 100_000);

    assert!(objective_execution_binding(&compiled, "canonical_ready").is_none());
    let abstain = record(
        "run.abstain.binding",
        32,
        RunStartObjectiveDispositionV1::ExplicitAbstain,
    );
    assert!(objective_execution_binding(&abstain, "explicit_abstain").is_none());
}

#[test]
fn exact_publication_replay_retains_original_result_without_new_admission() {
    let first = record(
        "run.replay.original",
        7,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let (_temp, mut state) = state_with(first.clone());
    let original = state
        .journal
        .index_entry(&first.snapshot.run_id)
        .unwrap()
        .unwrap()
        .clone();
    let later = record(
        "run.replay.later",
        8,
        RunStartObjectiveDispositionV1::ExplicitAbstain,
    );
    state
        .journal
        .append_run_start(state.journal.head_digest(), later)
        .unwrap();
    state.highest_sequences = replay_frontier(&state.journal).unwrap();
    let head = state.journal.head_digest();

    // The original observation is at 1s. A later clock must not readmit the
    // already-durable source or change a previously published decision.
    for now_ms in [1_001, 10_000, 99_999] {
        require_replay_admission(&state, &first.authentication, &first.snapshot.run_id).unwrap();
        match resolve_authenticated_replay(
            &state,
            &first.authentication,
            &first.snapshot.run_id,
            now_ms,
            first.snapshot.generation,
            first.snapshot.fence_digest,
        )
        .unwrap()
        .unwrap()
        {
            ObjectiveReplayPublication::Run {
                publication,
                record,
            } => {
                assert_eq!(*record, first);
                assert_eq!(
                    publication,
                    codex_hepta_learning_ledger::RunStartAppendReceipt {
                        disposition: RunStartAppendDisposition::IdempotentReplay,
                        sequence: original.sequence,
                        record_digest: original.record_digest,
                        chain_digest: original.chain_digest,
                    }
                );
            }
            ObjectiveReplayPublication::Conflict { .. } => panic!("run became a conflict"),
        }
        assert_eq!(state.journal.head_digest(), head);
    }
}

#[test]
fn exact_publication_replay_rejects_every_authentication_substitution() {
    let first = record(
        "run.replay.auth",
        7,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let (_temp, state) = state_with(first.clone());
    let mut variants = vec![first.authentication.clone(); 8];
    variants[0].issuer_id = id("issuer.other");
    variants[1].key_epoch += 1;
    variants[2].message_id = id("message.other");
    variants[3].sequence += 1;
    variants[4].expires_at_ms += 1;
    variants[5].scope_digest = digest("other-scope");
    variants[6].signed_body_digest = digest("modified-source-body");
    variants[7].signature[0] ^= 1;
    for authentication in variants {
        assert!(
            resolve_authenticated_replay(
                &state,
                &authentication,
                &first.snapshot.run_id,
                10_000,
                first.snapshot.generation,
                first.snapshot.fence_digest,
            )
            .is_err()
        );
    }
    assert!(require_replay_admission(&state, &first.authentication, &id("run.other")).is_err());
}

#[test]
fn exact_publication_replay_cannot_extend_deadline_generation_or_fence() {
    let first = record(
        "run.replay.current",
        7,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let (_temp, state) = state_with(first.clone());
    for (now_ms, generation, fence) in [
        (
            100_000,
            first.snapshot.generation,
            first.snapshot.fence_digest,
        ),
        (
            10_000,
            first.snapshot.generation + 1,
            first.snapshot.fence_digest,
        ),
        (10_000, first.snapshot.generation, digest("other-fence")),
    ] {
        assert!(
            resolve_authenticated_replay(
                &state,
                &first.authentication,
                &first.snapshot.run_id,
                now_ms,
                generation,
                fence,
            )
            .is_err()
        );
    }
    let mut short_auth = record(
        "run.replay.expired-auth",
        9,
        RunStartObjectiveDispositionV1::ExplicitAbstain,
    );
    short_auth.authentication.expires_at_ms = 2_000;
    let (_temp, state) = state_with(short_auth.clone());
    assert!(
        resolve_authenticated_replay(
            &state,
            &short_auth.authentication,
            &short_auth.snapshot.run_id,
            2_000,
            short_auth.snapshot.generation,
            short_auth.snapshot.fence_digest,
        )
        .is_err()
    );
}

#[test]
fn exact_conflict_replay_retains_terminal_outcome_without_recompilation() {
    let first = record(
        "run.replay.seed",
        1,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let (_temp, mut state) = state_with(first.clone());
    let mut authentication = first.authentication.clone();
    authentication.sequence = 2;
    authentication.message_id = id("message.conflict");
    let run_id = id("run.replay.conflict");
    let conflict_bytes = b"immutable-objective-conflict".to_vec();
    let conflict_digest = Digest32::of_bytes(&conflict_bytes);
    let head = state.journal.head_digest();
    state
        .journal
        .append_objective_conflict(
            head,
            codex_hepta_learning_ledger::RunStartConflictRecordV1 {
                authentication: authentication.clone(),
                admission: first.admission,
                run_id: run_id.clone(),
                runtime_body_digest: first.runtime_body_digest,
                conflict_digest,
                conflict_receipt_bytes: conflict_bytes,
            },
        )
        .unwrap();
    state.highest_sequences = replay_frontier(&state.journal).unwrap();
    let head = state.journal.head_digest();
    match resolve_authenticated_replay(&state, &authentication, &run_id, 99_999, 3, digest("fence"))
        .unwrap()
        .unwrap()
    {
        ObjectiveReplayPublication::Conflict {
            conflict_digest: actual,
        } => assert_eq!(actual, conflict_digest),
        ObjectiveReplayPublication::Run { .. } => panic!("conflict resurrected as a run"),
    }
    assert_eq!(state.journal.head_digest(), head);
}
