//! Opt-in real-provider path observation using the retained fixture writer.
//! This is one synthetic context smoke, never an unseen-source benefit result.

use std::collections::BTreeMap;
use std::error::Error;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_automation::AutomationStore;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::EpisodicRecordAdmission;
use codex_hepta_memory::EpisodicSnapshotAdmission;
use codex_hepta_memory::EpisodicSnapshotVerifier;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde::Serialize;
use serde_json::Value;
use tokio_util::sync::CancellationToken;

use super::Fixture;
use super::FixtureSource;
use super::assert_no_issuer_request;
use super::attach_production_operation_host;

#[path = "production_episodic_provider_authority.rs"]
mod authority;

#[path = "production_episodic_provider_diagnostic.rs"]
mod diagnostic;

#[path = "production_episodic_process.rs"]
mod process;

const PROMPT: &str = "Return only the 32 hexadecimal characters of the fixture nonce in the attached memory. Do not call tools.";
const QUERY: &str = "fixture nonce";
const PROVIDER: &str = "mem_context_fixture";
const READY_WAIT: Duration = Duration::from_secs(10);

struct CountedSource {
    original: Arc<FixtureSource>,
    reads: Arc<AtomicUsize>,
}

// Stop only the tasks this fixture created. Durable owner/thread/journal files
// remain in the retained directory, including after an unknown acknowledgement.
struct FixtureTasks {
    cancellation: CancellationToken,
    handles: Vec<tokio::task::AbortHandle>,
}

impl Drop for FixtureTasks {
    fn drop(&mut self) {
        self.cancellation.cancel();
        for handle in &self.handles {
            handle.abort();
        }
    }
}

impl EpisodicSnapshotVerifier for CountedSource {
    fn verify_current(&self, snapshot: &str) -> Result<EpisodicSnapshotAdmission, String> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        self.original.verify_current(snapshot)
    }
}

fn canonical_digest(value: &Value) -> Result<String, Box<dyn Error>> {
    fn ordered(value: &Value) -> Value {
        match value {
            Value::Object(fields) => Value::Object(
                fields
                    .iter()
                    .collect::<BTreeMap<_, _>>()
                    .into_iter()
                    .map(|(key, value)| (key.clone(), ordered(value)))
                    .collect(),
            ),
            Value::Array(values) => Value::Array(values.iter().map(ordered).collect()),
            other => other.clone(),
        }
    }
    Ok(
        Sha256Digest::for_bytes(&serde_json::to_vec(&ordered(value))?)
            .as_str()
            .to_owned(),
    )
}

fn write_receipt(root: &Path, name: &str, value: &impl Serialize) -> Result<(), Box<dyn Error>> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.join(name))?;
    file.write_all(&serde_json::to_vec_pretty(value)?)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "requires an explicitly retained run directory, exact source identity, and the already verified loopback provider route; sends one logical real model request"]
async fn episodic_real_provider_fresh_context_smoke() -> Result<(), Box<dyn Error>> {
    run_fixture(diagnostic::Mode::OriginalSmoke).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "independent MEM13 fixture diagnostic; requires a frozen intervention and loopback capture/generation adapter; may send one logical model request"]
async fn episodic_real_provider_native_intervention() -> Result<(), Box<dyn Error>> {
    run_fixture(diagnostic::Mode::from_environment()?).await
}

async fn run_fixture(mode: diagnostic::Mode) -> Result<(), Box<dyn Error>> {
    run_fixture_with_process(mode, None).await
}

async fn run_fixture_with_process(
    mode: diagnostic::Mode,
    process_mode: Option<process::Mode>,
) -> Result<(), Box<dyn Error>> {
    let base_url = std::env::var("HEPTA_LOCAL_PROVIDER_BASE_URL")?;
    let model = std::env::var("HEPTA_LOCAL_PROVIDER_MODEL")?;
    let source_sha = std::env::var("HEPTA_MEM_NATIVE_SOURCE_SHA")?;
    let request_id = std::env::var("HEPTA_MEM_CONTEXT_REQUEST_ID")?;
    let output = PathBuf::from(
        std::env::var_os("HEPTA_MEM_CONTEXT_RUN_ROOT").ok_or("retained run root required")?,
    );
    let uri: http::Uri = base_url.parse()?;
    if uri.scheme_str() != Some("http")
        || !matches!(uri.host(), Some("127.0.0.1" | "localhost"))
        || uri.port_u16().is_none_or(|port| port == 0)
        || uri
            .authority()
            .is_some_and(|authority| authority.as_str().contains('@'))
        || uri.path() != "/v1"
        || uri.query().is_some()
        || base_url.contains('#')
        || model.trim().is_empty()
        || model.len() > 256
        || model
            .chars()
            .any(|ch| ch.is_control() || matches!(ch, '"' | '\\'))
        || source_sha.len() != 40
        || !source_sha.bytes().all(|ch| ch.is_ascii_hexdigit())
        || request_id.is_empty()
        || request_id.len() > 128
        || !request_id
            .bytes()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, b'-' | b'_'))
        || !output.is_absolute()
    {
        return Err("closed local fixture configuration required".into());
    }
    // A repeated invocation with the same intent directory refuses before a
    // new owner or model request. Unknown dispatches need journal reconciliation.
    std::fs::create_dir(&output)?;
    std::fs::set_permissions(&output, std::fs::Permissions::from_mode(0o700))?;
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, peer) = fixture.inputs()?;
    attach_production_operation_host(&mut config, inputs).await?;
    let host = config
        .production_writer_host()
        .ok_or("retained fixture writer required")?;
    let retained = fixture.directory.keep();
    println!("mem-context-retained-root:{}", retained.display());
    write_receipt(
        &output,
        "INTENT.json",
        &serde_json::json!({
            "schema": if process_mode.is_some() { "hepta.mem15.native-a-exit-intent.v1" } else { "hepta.mem8.real-context-fixture-intent.v1" }, "request_id": request_id,
            "outer_source_sha": source_sha, "owner_root": retained,
            "provider_alias": PROVIDER, "provider_base_url": base_url, "requested_model": model,
            "prompt": PROMPT, "query": QUERY, "model_timeout_seconds": mode.timeout_seconds(),
            "diagnostic_mode": mode, "A_is_deterministic_import_not_model_learning": true,
            "process_mode": process_mode,
            "A_exit_before_C_required": process_mode.is_some(),
            "A_import_harness_process_exits_before_C": false,
            "fixture_only": true, "original_deployment_recovered": false,
            "unseen_source_benefit_evaluated": false, "physical_provider_request_count": null,
            "request_max_retries": 0, "stream_max_retries": 0, "unbounded_connection_retries": false,
        }),
    )?;

    let mut entropy = [0_u8; 16];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut entropy)?;
    let nonce = entropy
        .iter()
        .map(|value| format!("{value:02x}"))
        .collect::<String>();
    let fact = format!("fixture nonce: {nonce}");
    let mut record = serde_json::json!({
        "dependencies": [], "key": "nonce", "namespace": "bridge-fixture",
        "provenance": { "episode_id": "fixture-learning", "source_sha256": Sha256Digest::for_bytes(fact.as_bytes()).as_str(),
            "source_uri": "fixture://memory-context", "source_version": "1" },
        "source_id": "fixture-source", "text": fact, "version": 1, "write_sequence": 1,
    });
    let record_id = canonical_digest(&record)?;
    record["record_id"] = record_id.clone().into();
    let body = serde_json::json!({
        "authority_id": "0000000000004000800000000000e001", "generation": 1,
        "namespace": "bridge-fixture", "records": [record], "schema": "hepta.mem6.snapshot.v1",
    });
    let snapshot = serde_json::to_string(
        &serde_json::json!({ "sha256": canonical_digest(&body)?, "body": body }),
    )?;
    let reads = Arc::new(AtomicUsize::new(0));
    let source = Arc::new(CountedSource {
        reads: reads.clone(),
        original: Arc::new(FixtureSource(
            Mutex::new((
                snapshot.clone(),
                EpisodicSnapshotAdmission {
                    records: BTreeMap::from([(
                        record_id,
                        EpisodicRecordAdmission {
                            source: SourceDraft {
                                scope: CognitiveScope::AgentPrivate,
                                kind: LedgerSourceKind::FileObservation,
                                event_key: "one-private-fixture-observation".into(),
                                content: fact.as_bytes().to_vec(),
                                observed_at_unix_seconds: 1,
                            },
                            verification: MemoryVerification::Verified,
                        },
                    )]),
                    withdrawal: None,
                },
            )),
            Mutex::new(None),
        )),
    });
    // The nonce exists only in the admitted source/memory and local evaluator
    // variables. It is absent from prompts, filenames, config and expected-answer files.
    assert!(!PROMPT.contains(&nonce) && !QUERY.contains(&nonce));
    let mut config = config.with_episodic_snapshot_import("bridge-fixture".into(), source)?;
    let ingress = config
        .take_episodic_snapshot_import()
        .ok_or("source ingress required")?;
    let (identity, registry, _writer_lock) = config.into_parts();
    let state = Arc::new(crate::state::AgentdState::new(
        identity.clone(),
        registry.clone(),
        /*event_capacity*/ 32,
    )?);
    state.attach_cognitive_store(
        host.cognitive_runtime()
            .available_store()
            .ok_or("original store unavailable")?
            .clone(),
    )?;
    state
        .episodic_snapshot_import
        .set(ingress)
        .ok()
        .ok_or("single source ingress required")?;
    let automation = AutomationStore::open(&identity.layout).await?;
    state.attach_automation_store(automation)?;
    registry.compare_and_transition(&identity.agent_id, 1, AgentLifecycle::Running)?;
    state.refresh_generation()?;
    state.mark_runtime_prerequisites_ready()?;
    let options = crate::app_runtime::app_server_runtime_options_for_agent(
        &identity,
        state.clone(),
        host.cognitive_runtime(),
        host.production_mutation(),
        crate::app_runtime::AppServerModelToolProfile::ExplicitContextOnly,
    )?;
    assert!(options.hepta_cognitive_production_mutation.is_none());
    assert!(Arc::ptr_eq(
        options
            .hepta_cognitive_runtime
            .available_store()
            .ok_or("original model store missing")?,
        host.cognitive_runtime()
            .available_store()
            .ok_or("original owner store missing")?
    ));
    assert_eq!(
        options.required_feature_states,
        BTreeMap::from([
            (codex_features::Feature::HeptaCognitiveWrite, false),
            (codex_features::Feature::HeptaMemory, false),
            (codex_features::Feature::MemoryTool, false),
            (codex_features::Feature::TokenBudget, false),
        ])
    );
    std::fs::write(
        identity.home_root.join("config.toml"),
        format!(
            r#"
model = "{model}"
model_provider = "{PROVIDER}"
model_reasoning_effort = "minimal"
approval_policy = "never"
sandbox_mode = "read-only"
[features]
unbounded_connection_retries = false
[model_providers.{PROVIDER}]
name = "Fixture-only existing loopback provider"
base_url = "{base_url}"
wire_api = "responses"
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
"#
        ),
    )?;
    codex_utils_home_dir::set_process_codex_home_override(AbsolutePathBuf::from_absolute_path(
        &identity.home_root,
    )?)?;
    let cancel = CancellationToken::new();
    let codex = codex_utils_cargo_bin::cargo_bin("codex")?;
    let server = crate::AgentdControlServer::bind(
        identity.control_socket.clone(),
        state.clone(),
        cancel.clone(),
    )
    .await?;
    let server_task = tokio::spawn(server.run());
    let mut tasks = FixtureTasks {
        cancellation: cancel.clone(),
        handles: vec![server_task.abort_handle()],
    };
    let mut app = tokio::spawn(crate::app_runtime::run_app_server(
        identity.clone(),
        Arg0DispatchPaths {
            codex_self_exe: Some(codex),
            ..Default::default()
        },
        host.cognitive_runtime(),
        state.clone(),
        Some(host.clone()),
        crate::app_runtime::AppServerSocket::Bind,
        crate::app_runtime::AppServerModelToolProfile::ExplicitContextOnly,
    ));
    tasks.handles.push(app.abort_handle());
    let deadline = tokio::time::Instant::now() + READY_WAIT;
    while !identity.app_server_socket.exists() {
        if app.is_finished() {
            return Err(format!(
                "fixture App Server exited before readiness: {:?}",
                (&mut app).await
            )
            .into());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err("fixture App Server readiness timeout".into());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    state.mark_app_server_ready()?;
    if let Some(mode) = process_mode {
        let outcome = process::run(process::Run {
            mode, identity: &identity, host: &host, output: &output, retained: &retained,
            reads: reads.clone(), model: &model, request_id: &request_id,
            snapshot: &snapshot, fact: &fact, tasks: &mut tasks,
        }).await;
        cancel.cancel();
        tokio::time::timeout(Duration::from_secs(2), server_task).await???;
        app.abort();
        let _ = app.await;
        outcome?;
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_no_issuer_request(peer)?;
        return Ok(());
    }
    let client = crate::AgentdClient::new(
        identity.control_socket.clone(),
        identity.agent_id.clone(),
        /*spawn_generation*/ 1,
    )?;
    if mode != diagnostic::Mode::OriginalSmoke {
        write_receipt(
            &output,
            "A_IMPORT.json",
            &serde_json::json!({
                "snapshot_json": snapshot, "fixture_authorized": true,
                "production_authenticated": false,
            }),
        )?;
    }
    let imported = client.import_episodic_snapshot(snapshot).await?;
    assert_eq!(imported.active_records, 1);
    let withdrawal = if mode == diagnostic::Mode::Tombstone {
        let context = client.cognitive_context(QUERY.into(), /*limit*/ 4).await?;
        let target = context
            .items
            .iter()
            .find(|item| item.content == fact)
            .ok_or("native tombstone target absent from the original owner")?;
        Some(diagnostic::Withdrawal {
            host: host.clone(),
            agent_id: identity.agent_id.clone(),
            memory_id: target.memory_id.clone(),
            revision: target.revision,
        })
    } else {
        None
    };
    let cut = host.writer().recovery_anchor().await?;
    let reads_before_run = reads.load(Ordering::SeqCst);
    let authority_root = retained.join("model-final-use");
    let authority_started = if mode == diagnostic::Mode::OriginalSmoke {
        authority::start(
            &authority_root,
            identity.agent_id.to_string(),
            reads.clone(),
            reads_before_run,
        )
        .await
    } else {
        authority::start_with_withdrawal(
            &authority_root,
            identity.agent_id.to_string(),
            reads.clone(),
            reads_before_run,
            withdrawal,
        )
        .await
    };
    let (authorizer, issuer) = authority_started.map_err(|error| error.to_string())?;
    tasks.handles.push(issuer.abort_handle());
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: identity.control_socket.clone(),
        agent_id: identity.agent_id.clone(),
        generation: 1,
        model: model.clone(),
        timeout: Duration::from_secs(mode.timeout_seconds()),
    })
    .map_err(|error| error.to_string())?
    .with_turn_start_authorizer(Arc::new(authorizer));
    let journal = retained.join("native-context.journal");
    let mut control = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    write_receipt(
        &output,
        "DISPATCH_INPUT.json",
        &serde_json::json!({
            "request_id": request_id, "agent_id": identity.agent_id, "generation": 1,
            "journal": journal, "import": imported, "owner_cut": cut,
            "source_reads_before_run": reads_before_run, "profile": "ExplicitContextOnly",
            "native_client_name": "hepta-infer-worker", "tool_policy": "deny-only empty native ToolRouter",
            "source_admission": "explicit synthetic fixture, not deployment custody",
        }),
    )?;
    let outcome = driver
        .run_with_context_delivery(
            &mut control,
            NativeAdmission {
                request_id: request_id.clone(),
                maximum_in_flight: 1,
            },
            PROMPT.into(),
            QUERY.into(),
            mode.delivery(),
            &CancellationToken::new(),
        )
        .await;
    let original_record = control.native_record(&request_id).cloned();
    let source_reads_after = reads.load(Ordering::SeqCst);
    let owner_cut_after = host
        .writer()
        .recovery_anchor()
        .await
        .map_err(|error| error.to_string());
    let observed = match &outcome {
        Ok(value) => serde_json::json!({ "returned_output": value }),
        Err(error) => {
            serde_json::json!({ "error": error.to_string(), "no_fresh_identity_retry": true })
        }
    };
    write_receipt(
        &output,
        "OBSERVED.json",
        &serde_json::json!({
            "request_id": request_id, "observed": observed, "durable_record": original_record,
            "source_reads_before_run": reads_before_run, "source_reads_after_run": source_reads_after,
            "original_fixture_outbox_dispatches": probes.target.effects.load(Ordering::SeqCst),
            "owner_cut_before": cut, "owner_cut_after": owner_cut_after,
            "physical_provider_payload_observed": false, "physical_provider_request_count": null,
            "retained_owner_root": retained, "private_owner_contents_must_not_be_published": true,
            "scientific_acceptance": "HOLD", "unseen_source_benefit_evaluated": false,
        }),
    )?;
    let authority_result = issuer
        .await
        .map_err(|error| error.to_string())
        .and_then(|result| result.map_err(|error| error.to_string()));
    let authority_observed = match &authority_result {
        Ok(value) => serde_json::json!({ "observation": value }),
        Err(error) => serde_json::json!({ "error": error, "no_second_claim": true }),
    };
    write_receipt(&output, "FIXTURE_AUTHORITY.json", &authority_observed)?;
    cancel.cancel();
    tokio::time::timeout(Duration::from_secs(2), server_task).await???;
    app.abort();
    let _ = app.await;
    authority_result?;
    if mode != diagnostic::Mode::OriginalSmoke {
        let terminal = outcome
            .as_ref()
            .ok()
            .is_some_and(|returned| returned.succeeded() && returned.terminal_observed);
        let matched = outcome
            .as_ref()
            .ok()
            .is_some_and(|returned| returned.output.trim() == nonce);
        let revoked = outcome.as_ref().err().is_some_and(|error| {
            error
                .to_string()
                .contains("canonical episodic head changed outside the bridge")
        });
        write_receipt(
            &output,
            "RESULT.json",
            &serde_json::json!({
                "schema": "hepta.mem13.native-fixture-result.v1", "diagnostic_mode": mode,
                "request_id": request_id, "terminal_observed": terminal,
                "private_memory_fact_matched": matched, "native_revocation_rejected": revoked,
                "source_reads_before": reads_before_run, "source_reads_after": source_reads_after,
                "physical_provider_request_count": null, "requires_adapter_evidence": true,
                "fixture_only": true, "production_authenticated": false,
                "A_is_deterministic_import_not_model_learning": true,
                "A_import_harness_process_exits_before_C": false,
                "scientific_acceptance": "HOLD", "unseen_source_benefit_evaluated": false,
            }),
        )?;
        assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
        assert_no_issuer_request(peer)?;
        match mode {
            diagnostic::Mode::Tombstone => {
                assert!(revoked && !terminal);
                assert_ne!(owner_cut_after?, cut);
                assert_eq!(source_reads_after, reads_before_run + 3);
            }
            diagnostic::Mode::CaptureAttach | diagnostic::Mode::CaptureWithhold => {
                assert!(
                    !terminal,
                    "capture-only endpoint returned a successful generation"
                );
                assert_eq!(owner_cut_after?, cut);
                assert_eq!(source_reads_after, reads_before_run + 4);
            }
            diagnostic::Mode::Attach | diagnostic::Mode::Withhold => {
                assert!(
                    terminal,
                    "native generation is incomplete; retained evidence needs readback, not retry"
                );
                assert_eq!(owner_cut_after?, cut);
                assert_eq!(source_reads_after, reads_before_run + 4);
            }
            diagnostic::Mode::OriginalSmoke => unreachable!(),
        }
        return Ok(());
    }
    let returned = outcome.map_err(|error| error.to_string())?;
    assert!(returned.succeeded() && returned.terminal_observed);
    assert_eq!(returned.model, model);
    assert_eq!(returned.model_provider, PROVIDER);
    assert!(
        returned.output.trim() == nonce,
        "returned text did not match the private memory fact"
    );
    assert_eq!(source_reads_after, reads_before_run + 4);
    let record = original_record.ok_or("durable original record missing")?;
    let dispatch = record.dispatch.as_ref().ok_or("durable dispatch missing")?;
    assert_eq!(record.observation.as_ref(), Some(&returned));
    assert_eq!(record.turn_id.as_deref(), Some(returned.turn_id.as_str()));
    assert_eq!(dispatch.thread_id, returned.thread_id);
    assert!(!returned.thread_id.is_empty() && !returned.turn_id.is_empty());
    let is_digest =
        |digest: &String| digest.len() == 64 && digest.bytes().all(|byte| byte.is_ascii_hexdigit());
    assert!(
        dispatch
            .owner_context_digest
            .as_ref()
            .is_some_and(is_digest)
    );
    assert!(
        dispatch
            .codex_authority_witness_sha256
            .as_ref()
            .is_some_and(is_digest)
    );
    assert!(
        returned
            .codex_terminal_correlation_digest
            .as_ref()
            .is_some_and(is_digest)
    );
    assert_eq!(owner_cut_after?, cut);
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    assert_no_issuer_request(peer)?;
    write_receipt(
        &output,
        "RESULT.json",
        &serde_json::json!({
            "schema": "hepta.mem8.real-context-fixture-result.v1", "status": "path_observed",
            "request_id": request_id, "thread_id": returned.thread_id, "turn_id": returned.turn_id,
            "original_durable_terminal": true, "private_memory_fact_matched": true,
            "source_checks_before_claim": 2, "source_checks_after_claim": 2,
            "owner_context_digest": dispatch.owner_context_digest,
            "codex_authority_witness_sha256": dispatch.codex_authority_witness_sha256,
            "original_fixture_outbox_dispatches": 0, "original_owner_cut_unchanged": true,
            "physical_provider_payload_observed": false, "physical_provider_request_count": null,
            "fixture_only": true, "scientific_acceptance": "HOLD", "unseen_source_benefit_evaluated": false,
        }),
    )?;
    println!("mem-context-fixture-terminal:completed");
    Ok(())
}
