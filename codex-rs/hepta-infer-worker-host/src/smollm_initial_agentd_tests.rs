//! Real selected initial weights on the ordinary Agentd control socket.
//! Controlled owner/selector/issuer keys are test scope, not product enrollment.
use super::*;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::CognitiveContextItem;
use codex_hepta_agentd::cognitive_action_id;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::SourceDraft;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::time::Duration;

/// Seed only the first incarnation; later sessions reuse these exact memory IDs.
pub(super) async fn seed_actions(
    config: &AgentdConfig,
    now: i64,
) -> TestResult<BTreeMap<StableId, String>> {
    let identity = config.identity();
    let store = CognitiveStore::open(&identity.layout).await?;
    let access = CognitiveAccess::agent_private(identity.agent_id.clone());
    let mut actions = BTreeMap::new();
    for answer in ["yes", "no"] {
        let content = format!("lemon controlled answer {answer}");
        let citation = store
            .append_source(
                &access,
                &SourceDraft {
                    scope: CognitiveScope::AgentPrivate,
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("ordinary-initial-{answer}"),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: now,
                },
            )
            .await?;
        let memory = store
            .remember_memory(
                &access,
                &MemoryDraft {
                    stable_key: format!("ordinary-initial-{answer}"),
                    revision: MemoryRevisionDraft {
                        scope: CognitiveScope::AgentPrivate,
                        content: content.clone(),
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: now,
                        valid_to_unix_seconds: None,
                        citations: vec![citation],
                    },
                },
            )
            .await?;
        let item = CognitiveContextItem {
            memory_id: memory.id.memory_id.as_str().to_owned(),
            revision: memory.id.revision,
            content_sha256: Digest32::of_bytes(content.as_bytes()).to_string(),
            content,
        };
        actions.insert(cognitive_action_id(&item)?, answer.to_owned());
    }
    Ok(actions)
}

/// Drop aborts this owned task instead of silently detaching it. Normal and
/// fallible exits explicitly join before releasing the physical model session.
struct OwnedTask<T> {
    handle: Option<tokio::task::JoinHandle<T>>,
}
impl<T> OwnedTask<T> {
    fn new(handle: tokio::task::JoinHandle<T>) -> Self {
        Self {
            handle: Some(handle),
        }
    }
    fn is_finished(&self) -> bool {
        self.handle
            .as_ref()
            .is_none_or(tokio::task::JoinHandle::is_finished)
    }
    async fn finish(&mut self) -> Result<T, String> {
        let handle = self.handle.as_mut().ok_or("task already joined")?;
        let result = match tokio::time::timeout(Duration::from_secs(20), &mut *handle).await {
            Ok(result) => result.map_err(|error| format!("owned task join: {error}")),
            Err(_) => {
                handle.abort();
                let _ = handle.await;
                Err("owned task exceeded its shutdown deadline".to_owned())
            }
        };
        self.handle = None;
        result
    }
    async fn abort_and_join(&mut self) {
        if let Some(handle) = self.handle.take() {
            handle.abort();
            let _ = handle.await;
        }
    }
}
impl<T> Drop for OwnedTask<T> {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            handle.abort();
        }
    }
}

enum SessionCheck<'a> {
    Ordinary,
    Withdraw(&'a mut Fixture),
}

/// A fresh process incarnation, same original registry/CURRENT and model owner.
/// No publication, training, selection renewal of an old capsule, or efficacy.
pub(super) async fn ordinary_session(
    config: AgentdConfig,
    worker: SmolLmNeuralReadConfigV1,
    fixture: &Fixture,
    effects: &Path,
    reads: usize,
) -> TestResult<serde_json::Value> {
    let before = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    let (material, current) = fixture.public_material()?;
    let mut result = session(
        config,
        worker,
        material,
        current,
        effects,
        reads,
        SessionCheck::Ordinary,
    )
    .await?;
    let after = fixture
        .service
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    if before != after || result["current"]["head_digest"] != after.head_digest.to_string() {
        return Err("original CURRENT changed during ordinary session".into());
    }
    result["current_before"] = serde_json::json!({"head_digest":before.head_digest.to_string(),
        "record_count":before.records,"file_digest":before.file_digest.to_string(),
        "signed_head_generation":fixture.head.witness.generation.get()});
    result["current_after"] = serde_json::json!({"head_digest":after.head_digest.to_string(),
        "record_count":after.records,"file_digest":after.file_digest.to_string(),
        "signed_head_generation":fixture.head.witness.generation.get()});
    fs::write(
        effects.join("ordinary-session-result.json"),
        serde_json::to_vec_pretty(&result)?,
    )?;
    Ok(result)
}

pub(super) fn restart_stopped_config(
    identity: &codex_hepta_agentd::AgentdIdentity,
) -> TestResult<AgentdConfig> {
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
    let stopped = registry.load_agent(&identity.agent_id)?.lifecycle;
    if stopped.lifecycle != AgentLifecycle::Stopped {
        return Err("previous ordinary incarnation did not stop before restart".into());
    }
    let starting = registry.compare_and_transition(
        &identity.agent_id,
        stopped.generation,
        AgentLifecycle::Starting,
    )?;
    Ok(AgentdConfig::load(
        identity.fleet_root.clone(),
        identity.agent_id.clone(),
        starting.generation,
        identity.home_root.clone(),
        identity.run_root.clone(),
        identity.home_root.clone(),
        identity.workspace.clone(),
    )?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires actual public V2 weights; verifies same-owner reopen before any training"]
async fn real_public_initial_reopens_same_ordinary_owners() -> TestResult<()> {
    let (input, mut worker, bytes) = input_and_worker("public-reopen-session-0")?;
    let root = input.output.join("r");
    fs::create_dir(&root)?;
    let fixture = Fixture::with_profile(
        root.join("o"),
        &bytes,
        Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2),
    )?;
    let config = fixture.config("b")?;
    let identity = config.identity().clone();
    let actions = seed_actions(&config, i64::try_from(fixture.now)?).await?;
    worker.action_completions = actions.clone();
    let before = ordinary_session(
        config,
        worker,
        &fixture,
        &root.join("first"),
        /*reads*/ 1,
    )
    .await?;
    let config = restart_stopped_config(&identity)?;
    let (second_input, mut worker, second_bytes) = input_and_worker("public-reopen-session-1")?;
    if second_input.parent_sha256 != input.parent_sha256 || second_bytes != bytes {
        return Err("same original material changed during owner reopen".into());
    }
    worker.action_completions = actions;
    let after = ordinary_session(
        config,
        worker,
        &fixture,
        &root.join("second"),
        /*reads*/ 1,
    )
    .await?;
    assert_eq!(before["parent"], after["parent"]);
    assert_eq!(before["current_after"], after["current_before"]);
    assert_eq!(before["home_root"], after["home_root"]);
    fs::write(
        root.join("ordinary-reopen-result.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "schema":"hepta-real-ordinary-same-owner-reopen-v1", "sessions":[before, after],
            "ordinary_sessions":2,"training_rounds":0,"installed_children":0,
            "product_qualification":false,"locks_removed_or_bypassed":false
        }))?,
    )?;
    Ok(())
}

async fn session(
    config: AgentdConfig,
    worker: SmolLmNeuralReadConfigV1,
    material: SelectedPublicInitialSmolLmMaterialV2,
    current: ArtifactOwnerCurrentReaderV1,
    effects: &Path,
    reads: usize,
    mut check: SessionCheck<'_>,
) -> TestResult<serde_json::Value> {
    if !(1..=6).contains(&reads) {
        return Err("ordinary read count must fit original journal".into());
    }
    let codex_executable = codex_utils_cargo_bin::cargo_bin("codex")?.canonicalize()?;
    let identity = config.identity().clone();
    let parameter = material.manifest().content_digest;
    let selection = material.selection_digest();
    let current_receipt = current
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    let (inputs, issuer, authority) = inputs(worker, effects, u8::try_from(reads + 1)?).await?;
    let mut issuer = OwnedTask::new(issuer);
    let prepared =
        match prepare_public_initial_smollm_agentd_v2(config, material, current, inputs).await {
            Ok(prepared) => prepared,
            Err(mut error) => {
                let cleanup = error.shutdown_retained().await;
                issuer.abort_and_join().await;
                archive_authority(&authority, effects)?;
                return Err(format!(
                    "initial preparation failed: {error}; retained cleanup: {cleanup:?}"
                )
                .into());
            }
        };
    let PreparedSmolLmAgentdV1 {
        config,
        session: model_session,
    } = prepared;
    let port = model_session.port.as_ref().cloned();
    let mut running = None;
    // Capture every fallible serving step so task/session cleanup is awaited on
    // ordinary errors. Assertions are intentionally outside this owned section.
    let result: TestResult<serde_json::Value> = async {
        let port = port.as_ref().ok_or("ordinary initial session missing")?;
        codex_utils_home_dir::set_process_codex_home_override(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&identity.home_root)?)?;
        let client = AgentdClient::new(identity.control_socket.clone(), identity.agent_id.clone(), identity.spawn_generation)?;
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
        registry.compare_and_transition(&identity.agent_id, identity.spawn_generation, AgentLifecycle::Running)?;
        running = Some(OwnedTask::new(tokio::spawn(codex_hepta_agentd::run(
            config, codex_arg0::Arg0DispatchPaths {
                codex_self_exe: Some(codex_executable.clone()),
                ..Default::default()
            }))));
        tokio::time::timeout(Duration::from_secs(20), async {
            loop {
                if client.health().await.is_ok_and(|health| health.ready) { break; }
                if running.as_ref().is_none_or(OwnedTask::is_finished) {
                    return Err("ordinary Agentd exited before readiness");
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            Ok::<_, &str>(())
        }).await??;
        let parent = port.with_measurements(|load, _| {
            if load.parameter_file_digest() != parameter { return Err("actual initial parameter differs from selected material".to_owned()); }
            Ok(serde_json::json!({"generation":load.generation(),
                "parameter_sha256":load.parameter_file_digest().to_string(),
                "contract":load.contract_digest().to_string(), "adapter":load.adapter_digest().to_string(),
                "backbone":load.backbone_digest().to_string(), "tokenizer":load.tokenizer_digest().to_string()}))
        })??;
        let mut forwards = BTreeSet::new();
        let mut observations = Vec::new();
        for index in 0..reads {
            let response = client.cognitive_context("lemon".to_owned(), /*limit*/ 2).await?;
            if response.items.len() != 2 { return Err("ordinary cognitive response lost seeded actions".into()); }
            let observed = port.with_measurements(|load, forward| {
                let forward = forward.ok_or("ordinary context did not perform a real forward")?;
                if load.parameter_file_digest() != parameter || forward.ready_digest() != load.ready_digest()
                    || !forwards.insert(forward.control_ids().0.to_owned()) {
                    return Err("ordinary context differs from actual load or repeats a forward".to_owned());
                }
                Ok(serde_json::json!({"read":index,"read_digest":response.read_digest,
                    "actual_parameter":load.parameter_file_digest().to_string(),"actual_ready":load.ready_digest().to_string(),
                    "forward_control":forward.control_ids(),"forward_response":forward.response_digest().to_string(),
                    "actual_logits":forward.logits_digest().to_string()}))
            })??;
            observations.push(observed);
        }
        let withdrawal_refused = match &mut check {
            SessionCheck::Ordinary => false,
            SessionCheck::Withdraw(fixture) => {
                fixture.withdraw()?;
                if client.cognitive_context("lemon".to_owned(), /*limit*/ 2).await.is_ok() {
                    return Err("withdrawn initial selection still served ordinary context".into());
                }
                true
            }
        };
        Ok(serde_json::json!({"schema":"hepta-controlled-ordinary-public-initial-session-v2",
            "parent":parent,"current":{"head_digest":current_receipt.head_digest.to_string(),
                "record_count":current_receipt.records,"file_digest":current_receipt.file_digest.to_string()},
            "selection_digest":selection.to_string(),"observations":observations,"ordinary_context_reads":reads,
            "withdrawal_refused":withdrawal_refused,"controlled_test_issuer":true,"training_rounds":0,
            "beneficial_releases":0,"cold_runtime_installed":false,"public_network_ready":false,
            "product_qualification_issued":false,"home_root":identity.home_root,"spawn_generation":identity.spawn_generation,
            "codex_executable":codex_executable}))
    }.await;
    let stop_result: TestResult<()> = async {
        if let Some(task) = running.as_mut() {
            let registry =
                FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
            let record = registry.load_agent(&identity.agent_id)?;
            let draining = match record.lifecycle.lifecycle {
                AgentLifecycle::Running => registry.compare_and_transition(
                    &identity.agent_id,
                    record.lifecycle.generation,
                    AgentLifecycle::Draining,
                )?,
                AgentLifecycle::Draining => record.lifecycle,
                _ => return Err("ordinary runtime is outside its original drain lifecycle".into()),
            };
            registry.compare_and_transition(
                &identity.agent_id,
                draining.generation,
                AgentLifecycle::Stopped,
            )?;
            let stopped = task.finish().await?;
            if !matches!(stopped, Err(AgentdError::GenerationFenced(_))) {
                return Err(format!(
                    "ordinary runtime did not return the original generation fence: {stopped:?}"
                )
                .into());
            }
            if registry.load_agent(&identity.agent_id)?.lifecycle.lifecycle
                != AgentLifecycle::Stopped
            {
                return Err("original registry did not retain Stopped".into());
            }
        }
        Ok(())
    }
    .await;
    if let Some(task) = running.as_mut() {
        task.abort_and_join().await;
    }
    let model_shutdown = model_session.shutdown().await;
    let issuer_result: TestResult<()> =
        if result.is_ok() && stop_result.is_ok() && model_shutdown.is_ok() {
            match issuer.finish().await {
                Ok(outcome) => outcome.map_err(issuer_error),
                Err(error) => Err(error.into()),
            }
        } else {
            issuer.abort_and_join().await;
            Ok(())
        };
    let archived = archive_authority(&authority, effects);
    if result.is_err()
        || stop_result.is_err()
        || model_shutdown.is_err()
        || issuer_result.is_err()
        || archived.is_err()
    {
        let failure = serde_json::json!({"schema":"hepta-ordinary-initial-session-failure-v2",
            "ordinary":result.as_ref().err().map(ToString::to_string),
            "runtime_stop":stop_result.as_ref().err().map(ToString::to_string),
            "model_shutdown":model_shutdown.as_ref().err().map(ToString::to_string),
            "issuer":issuer_result.as_ref().err().map(ToString::to_string),
            "archive":archived.as_ref().err().map(ToString::to_string),"product_qualification_issued":false});
        fs::write(
            effects.join("ordinary-failure.json"),
            serde_json::to_vec_pretty(&failure)?,
        )?;
        return Err(failure.to_string().into());
    }
    result
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires original pinned real SmolLM materials; ordinary reads are not three training rounds"]
async fn real_selected_initial_serves_ordinary_context_then_refuses_revocation() -> TestResult<()> {
    let (input, mut worker, bytes) = input_and_worker("ordinary-selected-initial")?;
    let mut fixture = Fixture::with_profile(
        // The original AF_UNIX layout must fit without socket aliases.
        input.output.join("o"),
        &bytes,
        Digest32::of_bytes(SMOLLM_PUBLIC_INITIAL_PROFILE_V2),
    )?;
    let config = fixture.config("b")?;
    worker.action_completions = seed_actions(&config, i64::try_from(fixture.now)?).await?;
    let (material, current) = fixture.public_material()?;
    let report = session(
        config,
        worker,
        material,
        current,
        &input.output.join("ordinary-effects"),
        /*reads*/ 3,
        SessionCheck::Withdraw(&mut fixture),
    )
    .await?;
    assert_eq!(report["ordinary_context_reads"], 3);
    assert_eq!(report["withdrawal_refused"], true);
    fs::write(
        input.output.join("ordinary-initial-context-result.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    Ok(())
}
