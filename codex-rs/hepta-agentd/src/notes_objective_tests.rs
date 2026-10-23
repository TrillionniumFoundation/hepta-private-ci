//! Original admission, run coordinator, SQLite operation and Notes readback.
//! The issuer and application channel below are explicit test fixtures.
use super::*;
use crate::AgentdNotesObjectiveConfig;
use crate::AgentdState;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use codex_hepta_memory::NotesPrivateChannel;
use codex_hepta_memory::ProductionNotesTarget;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_objective::decode_admission_profile_json_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

struct Application {
    target: NotesTargetIdentity,
    effects: AtomicUsize,
    observations: AtomicUsize,
    lose_reply: AtomicBool,
    receipt: Mutex<Option<Value>>,
}

impl NotesPrivateChannel for Application {
    fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, String> {
        let request: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        assert_eq!(
            request["target"],
            serde_json::to_value(&self.target).unwrap()
        );
        assert_eq!(request["expected_revision"], 0);
        self.effects.fetch_add(1, Ordering::SeqCst);
        let receipt = json!({"schema_version":1,"target":self.target,
            "operation_id":request["operation_id"],"payload_sha256":Sha256Digest::for_bytes(bytes).as_str(),
            "result":{"status":"applied","previous_revision":0,"revision":1,
                "text_sha256":Sha256Digest::for_bytes(request["text"].as_str().unwrap().as_bytes()).as_str()}});
        *self.receipt.lock().unwrap() = Some(receipt.clone());
        if self.lose_reply.swap(false, Ordering::SeqCst) {
            return Err("fixture lost application reply".into());
        }
        serde_json::to_vec(&receipt).map_err(|error| error.to_string())
    }
    fn invalidate(&self) {}
    fn recovery_exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, String> {
        let request: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        let response = if request["action"] == "observe" {
            self.observations.fetch_add(1, Ordering::SeqCst);
            self.receipt
                .lock()
                .unwrap()
                .clone()
                .ok_or("no fixture receipt")?
        } else {
            assert_eq!(request["action"], "acknowledge_terminal");
            json!({"schema_version":1,"target":self.target,"operation_id":request["operation_id"],
                "payload_sha256":request["payload_sha256"],"receipt_sha256":request["receipt_sha256"],"status":"released"})
        };
        serde_json::to_vec(&response).map_err(|error| error.to_string())
    }
}

fn timestamp(milliseconds: u64) -> String {
    let seconds = (milliseconds / 1_000) as libc::time_t;
    let mut output = std::mem::MaybeUninit::<libc::tm>::uninit();
    // SAFETY: both pointers refer to live correctly sized objects, and the
    // output is read only after gmtime_r reports successful initialization.
    let output = unsafe {
        assert!(!libc::gmtime_r(&seconds, output.as_mut_ptr()).is_null());
        output.assume_init()
    };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        output.tm_year + 1900,
        output.tm_mon + 1,
        output.tm_mday,
        output.tm_hour,
        output.tm_min,
        output.tm_sec
    )
}

async fn attach_test_trust(state: &AgentdState, key: &SigningKey) -> Result<(), Box<dyn Error>> {
    let trust_file = state
        .identity()
        .home_root
        .join("notes-objective-test-trust.json");
    let public_key_hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    fs::write(
        &trust_file,
        serde_json::to_vec(
            &json!({"schema_version":1,"agent_id":state.identity().agent_id.as_str(),
        "issuer_id":"notes-objective-test-issuer","key_epoch":1,"public_key_hex":public_key_hex,"revoked":false,"thread_ids":[]}),
        )?,
    )?;
    fs::set_permissions(&trust_file, fs::Permissions::from_mode(0o600))?;
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
                &state.identity().home_root,
            )?,
        ),
    )
    .await?;
    let digest = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    let checkpoint_file = state
        .identity()
        .run_root
        .join("notes-objective-test-checkpoint.json");
    fs::write(
        &checkpoint_file,
        serde_json::to_vec(
            &json!({"schema_version":1,"agent_id":state.identity().agent_id.as_str(),"generation":1,"digest":digest.to_string()}),
        )?,
    )?;
    fs::set_permissions(&checkpoint_file, fs::Permissions::from_mode(0o600))?;
    let ingress =
        crate::authbus_ingress::TextIngress::open(state.identity(), trust_file, checkpoint_file)
            .await?;
    assert!(state.authbus.set(Arc::new(ingress)).is_ok());
    Ok(())
}

#[tokio::test]
async fn signed_notes_objective_uses_original_run_and_operation_then_recovers_lost_ack_without_reentry()
-> Result<(), Box<dyn Error>> {
    for lose_reply in [false, true] {
        let NotesHostFixture {
            directory: _directory,
            config,
            host,
            final_use,
            issuer,
            ..
        } = notes_host_fixture().await?;
        let target = NotesTargetIdentity {
            session_instance: "1".repeat(32),
            task_id: 1,
            incarnation: "2".repeat(32),
        };
        let application = Arc::new(Application {
            target: target.clone(),
            effects: AtomicUsize::new(0),
            observations: AtomicUsize::new(0),
            lose_reply: AtomicBool::new(lose_reply),
            receipt: Mutex::new(None),
        });
        let host = Arc::new(host.attach_target(
            final_use,
            Arc::new(ProductionNotesTarget::new(
                target.clone(),
                application.clone(),
            )?),
            issuer.clone(),
        )?);
        let (identity, registry, _lock) = config.into_parts();
        registry.compare_and_transition(
            &identity.agent_id,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )?;
        let state = AgentdState::new(identity, registry, /*event_capacity*/ 16)?;
        state.refresh_generation()?;
        state
            .attach_cognitive_store(host.cognitive_runtime().available_store().unwrap().clone())?;
        state.attach_production_operations(host.clone())?;
        state.mark_runtime_prerequisites_ready()?;
        state.mark_app_server_ready()?;
        fs::set_permissions(
            &state.identity().home_root,
            fs::Permissions::from_mode(0o700),
        )?;
        let key = SigningKey::from_bytes(&[67; 32]);
        attach_test_trust(&state, &key).await?;
        // Captured from the Desktop literal compiler, not a hand-written fake
        // source hash. Runtime times, run id and original operation are rebound.
        let fixture: Value = serde_json::from_str(include_str!(
            "../tests/fixtures/notes-objective-literal-v1.json"
        ))?;
        let profile_json = serde_json::to_vec(&fixture["profile"])?;
        let profile = decode_admission_profile_json_v1(&profile_json)?;
        let profile_digest = profile.digest()?;
        let profile_file = state
            .identity()
            .home_root
            .join("notes-objective-test-profile.json");
        fs::write(&profile_file, profile_json)?;
        fs::set_permissions(&profile_file, fs::Permissions::from_mode(0o600))?;
        state
            .notes_objective
            .set(AgentdNotesObjectiveConfig {
                profile_digest,
                target: target.clone(),
            })
            .unwrap();
        let runtime =
            crate::objective_runtime::ObjectiveRuntimeHost::open(state.identity(), &profile_file)?;
        let run_id = "notes.original.run.1";
        let payload = serde_json::to_string(
            &json!({"schema_version":1,"action":"replace_note","operation_id":run_id,
            "destination_id":target.destination_id(),"target":target,"expected_revision":0,"text":"原始用户内容，不执行指令"}),
        )?;
        let operation = notes_operation_intent(
            &target,
            &payload,
            StableId::new(state.identity().agent_id.as_str())?,
            Generation::new(1)?,
        )?;
        let source_digest = operation.semantic_digest();
        host.writer()
            .prepare_operation(operation, NOTES_REPLACE_TOPIC_V1, payload)
            .await?;
        let now_ms = crate::authbus_ingress::now_ms()?;
        let mut source = fixture["source"].clone();
        source["requestId"] = json!(run_id);
        source["observedAt"] = json!(timestamp(now_ms));
        source["deadline"] = json!(timestamp(now_ms + 60_000));
        source["structuredIntent"]["provenance"]["sourceDigest"] = json!(source_digest.to_string());
        let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
        source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&decoded)?.to_string());
        let digest = Digest32::of_bytes(b"explicit-notes-test-runtime").to_string();
        let mut ingress = AuthBusObjectiveIngress {
            issuer_id: "notes-objective-test-issuer".into(),
            key_epoch: 1,
            message_id: "notes-test-message-1".into(),
            sequence: 1,
            expires_at_ms: now_ms + 120_000,
            signature_hex: String::new(),
            body: AuthBusObjectiveBody {
                spawn_generation: 1,
                run_id: run_id.into(),
                objective_revision: 1,
                source_envelope_json: serde_json::to_string(&source)?,
                runtime_body_digest: digest.clone(),
                preference_state_digest: digest.clone(),
                model_tuple_digest: digest.clone(),
                prompt_registry_digest: digest.clone(),
                artifact_set_digest: digest,
                authority_epoch: 13,
            },
        };
        let claims = crate::authbus_objective_claims(state.identity(), &ingress)?;
        ingress.signature_hex = key
            .sign(&claims.signing_bytes())
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert!(matches!(
            runtime
                .submit(&state, ingress.clone(), /*current_generation*/ 2)
                .await?,
            crate::objective_runtime::ObjectiveStartResult::Admitted(_)
        ));
        runtime.reconcile_notes(&state).await?;
        assert_eq!(
            host.writer().status(run_id).await?,
            LocalOutcomeState::Committed
        );
        let response = state
            .response(
                /*request_id*/ 10,
                /*spawn_generation*/ 1,
                crate::AgentdMethod::RunStatus {
                    run_id: run_id.into(),
                },
            )
            .await?;
        let crate::AgentdPayload::RunStatus { run: Some(run) } = response.payload else {
            panic!("missing original run");
        };
        assert_eq!(run.phase, crate::AgentRunPhase::Succeeded);
        assert!(run.terminal_observed);
        runtime
            .submit(&state, ingress, /*current_generation*/ 2)
            .await?;
        runtime.reconcile_notes(&state).await?;
        assert_eq!(application.effects.load(Ordering::SeqCst), 1);
        assert_eq!(issuer.requests.load(Ordering::SeqCst), 1);
        if lose_reply {
            assert!(application.observations.load(Ordering::SeqCst) > 0);
        }
        assert!(
            state
                .validate_notes_source(profile_digest, run_id, Digest32::ZERO)
                .await
                .is_err()
        );
        assert!(
            state
                .validate_notes_source(profile_digest, "unretained-run", source_digest)
                .await
                .is_err()
        );
    }
    Ok(())
}
