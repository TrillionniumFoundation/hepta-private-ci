use std::os::unix::fs::PermissionsExt;

use codex_hepta_learning_ledger::RunStartAdmissionProofV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

#[tokio::test]
async fn compiler_upgrade_recovers_current_runs_and_retains_old_proofs_inert() {
    let (temp, registry, previous) =
        crate::state::isolation_tests::fixture().expect("owner fixture");
    let identity = previous.identity().clone();
    drop(previous);
    let agentd =
        AgentdState::new(identity, registry, /*event_capacity*/ 16).expect("restarted owner");
    agentd
        .refresh_generation()
        .expect("current Fleet generation");
    std::fs::set_permissions(
        &agentd.identity().home_root,
        std::fs::Permissions::from_mode(0o700),
    )
    .expect("private owner home");
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&agentd.identity().layout)
            .await
            .expect("cognitive owner");
    agentd
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attach cognitive owner");
    agentd
        .mark_runtime_prerequisites_ready()
        .expect("owner prerequisites");
    agentd.mark_app_server_ready().expect("ready");

    let signer = SigningKey::from_bytes(&[81; 32]);
    let trust_file = agentd
        .identity()
        .home_root
        .join("objective-upgrade-trust.json");
    let public_key_hex = signer
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    std::fs::write(
        &trust_file,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "agent_id": agentd.identity().agent_id.as_str(),
            "issuer_id": "adapter.console",
            "key_epoch": 1,
            "public_key_hex": public_key_hex,
            "revoked": false,
            "thread_ids": []
        }))
        .expect("trust JSON"),
    )
    .expect("write trust");
    std::fs::set_permissions(&trust_file, std::fs::Permissions::from_mode(0o600))
        .expect("private trust");
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &agentd.identity().home_root,
            )
            .expect("owner home"),
        ),
    )
    .await
    .expect("evidence owner");
    let frontier = evidence
        .authbus_replay_frontier_digest()
        .await
        .expect("initial frontier");
    drop(evidence);
    let authbus_checkpoint = temp.path().join("objective-upgrade-replay-checkpoint.json");
    std::fs::write(
        &authbus_checkpoint,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1,
            "agent_id": agentd.identity().agent_id.as_str(),
            "generation": 1,
            "digest": frontier.to_string()
        }))
        .expect("checkpoint JSON"),
    )
    .expect("write checkpoint");
    std::fs::set_permissions(&authbus_checkpoint, std::fs::Permissions::from_mode(0o600))
        .expect("private checkpoint");
    let ingress = crate::authbus_ingress::TextIngress::open(
        agentd.identity(),
        trust_file,
        authbus_checkpoint,
    )
    .await
    .expect("AuthBus owner");
    assert!(agentd.authbus.set(Arc::new(ingress)).is_ok());

    let profile =
        ValidatedAdmissionProfileV1::new(crate::intelligence_product::tests::objective_profile())
            .expect("frozen current profile");
    let key = profile.reuse_key();
    let now_ms = authbus_ingress::now_ms().expect("clock");
    let generation = agentd.current_generation().expect("generation");
    let checkpoint = TestCheckpoint::new();
    let root = temp.path().join("objective-upgrade-store");
    let mut journal = DurableRunStartStore::open(
        root.clone(),
        digest("upgrade-binding"),
        /*max_records_per_segment*/ 4,
        Box::new(checkpoint.clone()),
    )
    .expect("RunStart owner");
    for (run_id, sequence, compiler_contract, profile_revision) in [
        (
            "run.upgrade.old-compiler",
            1,
            digest("previous-compiler-contract"),
            key.profile_revision,
        ),
        (
            "run.upgrade.current",
            2,
            key.compiler_contract_digest,
            key.profile_revision,
        ),
        (
            "run.upgrade.old-profile",
            3,
            key.compiler_contract_digest,
            key.profile_revision + 1,
        ),
    ] {
        let mut durable = record(run_id, sequence, RunStartObjectiveDispositionV1::Compiled);
        durable.admission.profile_id = profile.profile().profile_id.clone();
        durable.admission.profile_revision = profile_revision;
        durable.admission.profile_digest = key.profile_digest;
        durable.admission.observed_at_unix_micros = now_ms * 1_000;
        durable.admission.deadline_unix_micros = (now_ms + 60_000) * 1_000;
        let mut proof_bytes = b"hepta.objective.admission-proof.v1".to_vec();
        for identity in [
            digest("historical-envelope"),
            key.profile_digest,
            digest("historical-context"),
            compiler_contract,
            durable.admission.admitted_source_digest,
        ] {
            proof_bytes.extend_from_slice(identity.as_array());
        }
        durable.admission.objective_admission_proof = Some(
            RunStartAdmissionProofV1::from_canonical_bytes(
                &proof_bytes,
                Digest32::of_bytes(&proof_bytes),
            )
            .expect("historical integrity proof"),
        );
        durable.snapshot.generation = generation;
        durable.snapshot.fence_digest = objective_fence(agentd.identity(), generation);
        let claims = SignedMessageClaims {
            issuer_id: id("adapter.console"),
            key_epoch: Generation::new(1).expect("key epoch"),
            message_id: durable.authentication.message_id.clone(),
            subject_id: id(agentd.identity().agent_id.as_str()),
            scope_digest: objective_scope(agentd.identity()),
            payload_digest: durable.authentication.signed_body_digest,
            sequence,
            expires_at_ms: now_ms + 300_000,
        };
        durable.authentication.issuer_id = claims.issuer_id.clone();
        durable.authentication.scope_digest = claims.scope_digest;
        durable.authentication.expires_at_ms = claims.expires_at_ms;
        durable.authentication.signature = signer.sign(&claims.signing_bytes()).to_bytes();
        journal
            .append_run_start(journal.head_digest(), durable)
            .expect("durable publication");
    }
    drop(journal);
    let journal = DurableRunStartStore::open(
        root,
        digest("upgrade-binding"),
        /*max_records_per_segment*/ 4,
        Box::new(checkpoint),
    )
    .expect("recover mixed history");
    let host = ObjectiveRuntimeHost {
        profile_digest: key.profile_digest,
        profile,
        state: Mutex::new(ObjectiveHostState {
            replay_frontier: replay_frontier(&journal)
                .expect("recover authenticated replay frontier"),
            journal,
        }),
    };
    host.reconcile(&agentd, generation, now_ms)
        .expect("upgrade must not block current recovery");
    assert_eq!(agentd.active_run_count().expect("active runs"), 1);
    host.reconcile(&agentd, generation, now_ms)
        .expect("idempotent current recovery");
    assert_eq!(agentd.active_run_count().expect("active runs"), 1);
    let state = host.state.lock().expect("objective owner");
    for run_id in ["run.upgrade.old-compiler", "run.upgrade.old-profile"] {
        let retained = state
            .journal
            .get(&id(run_id))
            .expect("read history")
            .expect("retained old proof");
        assert!(require_current_admission_proof(&retained.admission, &host.profile).is_err());
        assert!(require_replay_admission(&state, &retained.authentication, &id(run_id)).is_ok());
    }
    let current = state
        .journal
        .get(&id("run.upgrade.current"))
        .expect("read current")
        .expect("current proof");
    require_current_admission_proof(&current.admission, &host.profile)
        .expect("current proof remains live");
    assert!(
        agentd
            .start_current_run_start_record(current)
            .expect("current run identity")
            .idempotent
    );
}
