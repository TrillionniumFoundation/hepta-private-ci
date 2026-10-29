//! One next ordinary Agentd task using the qualified, downloaded child bytes.
//! Read receipts do not create model, CURRENT, resource, or FinalUse authority.
use super::*;
use crate::smollm_cognitive_host::SmolLmCognitiveHostInputsV1;
use crate::smollm_cognitive_host::prepare_smollm_neural_agentd_v1;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::CognitiveNeuralExecutionV1;
use codex_hepta_agentd::CognitiveNeuralSourceV1;
use codex_hepta_agentd::cognitive_action_id;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use std::collections::BTreeSet;

/// Retain ownership across cancellation of the bounded join future.
struct OwnedTask<T>(Option<tokio::task::JoinHandle<T>>);

impl<T> OwnedTask<T> {
    fn is_finished(&self) -> bool {
        self.0
            .as_ref()
            .is_none_or(tokio::task::JoinHandle::is_finished)
    }
    async fn finish(&mut self) -> Result<T, String> {
        let handle = self.0.as_mut().ok_or("ordinary task already joined")?;
        let result = match tokio::time::timeout(Duration::from_secs(20), &mut *handle).await {
            Ok(result) => result.map_err(|error| format!("owned task join: {error}")),
            Err(_) => {
                handle.abort();
                let _ = handle.await;
                Err("owned task exceeded its shutdown deadline".to_owned())
            }
        };
        self.0 = None;
        result
    }
    async fn abort_and_join(&mut self) {
        if let Some(handle) = self.0.take() {
            handle.abort();
            let _ = handle.await;
        }
    }
}
impl<T> Drop for OwnedTask<T> {
    fn drop(&mut self) {
        if let Some(handle) = self.0.take() {
            handle.abort();
        }
    }
}

struct JournalJoin {
    load_ids: (String, String),
    forward_ids: (String, String),
    execution: CognitiveNeuralExecutionV1,
    owner: AgentId,
    model_digest: Digest32,
    load_payload: Digest32,
    forward_payload: Digest32,
    worker_id: String,
    grant: ResourceGrant,
}

fn cold_journal(path: &Path, capacity: usize, join: &JournalJoin) -> TestResult<Value> {
    let control = DurableInferenceControl::open(path, capacity)?;
    let raw = fs::read(path)?;
    let text = std::str::from_utf8(&raw)?;
    let submitted = text
        .lines()
        .filter_map(|line| line.strip_prefix("submit|"))
        .map(|line| line.split('|').next().ok_or("journal request field"))
        .collect::<Result<Vec<_>, _>>()?;
    if submitted != [join.load_ids.0.as_str(), join.forward_ids.0.as_str()] {
        return Err("next task journal must contain exactly its real load and forward".into());
    }
    let mut observations = Vec::new();
    let load_output: Digest32 = join.execution.load_output_digest.as_str().parse()?;
    let forward_output: Digest32 = join.execution.response_digest.as_str().parse()?;
    for (ids, payload, output, tokens) in [
        (&join.load_ids, join.load_payload, load_output, 0_u32),
        (
            &join.forward_ids,
            join.forward_payload,
            forward_output,
            1_u32,
        ),
    ] {
        let record = control
            .get(&ids.0)
            .ok_or("original completed request missing on cold reopen")?;
        let reservation = record
            .reservation
            .as_ref()
            .ok_or("original reservation missing")?;
        let assignment = record
            .assignment
            .as_ref()
            .ok_or("original assignment missing")?;
        let terminal = Digest32::of_parts(&[
            b"hepta.smollm-observation.v1\0",
            ids.0.as_bytes(),
            output.as_array(),
            &[1],
            &tokens.to_be_bytes(),
        ]);
        let assigned = Digest32::of_parts(&[
            b"hepta.smollm-assignment.v1\0",
            payload.as_array(),
            ids.0.as_bytes(),
        ]);
        if record.state != RequestState::Completed
            || record.request.principal_id != join.owner.as_str()
            || record.request.model_digest != join.model_digest.to_string()
            || record.request.payload_digest != payload.to_string()
            || record.request.semantic_digest != join.grant.semantic_digest
            || record.request.maximum_tokens != 1
            || record.request.deadline_ms > join.grant.expires_at_ms
            || reservation.reservation_id != ids.1
            || reservation.quota_units != 1
            || reservation.maximum_tokens != 1
            || reservation.authority_epoch != join.grant.authority_epoch
            || reservation.valid_until_ms != record.request.deadline_ms
            || assignment.worker_id != join.worker_id
            || assignment.worker_generation != join.grant.generation
            || assignment.assignment_digest != assigned.to_string()
            || record.terminal_observation_digest.as_deref() != Some(terminal.to_string().as_str())
            || record.consumed_tokens != tokens
            || record.usage_units != u64::from(tokens)
        {
            return Err("cold original journal differs from actual next-task execution".into());
        }
        observations.push(json!({"request":ids.0,"reservation":ids.1,"state":"Completed",
            "payload":payload.to_string(),"output":output.to_string(),"terminal_observation":terminal.to_string(),
            "consumed_tokens":tokens,"revision":record.revision}));
    }
    drop(control);
    if fs::read(path)? != raw {
        return Err("cold journal replay changed previously acknowledged bytes".into());
    }
    Ok(
        json!({"schema":"hepta-next-task-original-control-readback-v1","path":path,
        "sha256":Digest32::of_bytes(&raw).to_string(),"original_capacity":capacity,
        "completed":observations,"exact_cold_reopen":true}),
    )
}

pub(super) async fn read_child(
    config: AgentdConfig,
    installed: install::Installed,
    input: &NativeInput,
    actions: BTreeMap<StableId, String>,
    root: &Path,
) -> TestResult<Value> {
    let identity = config.identity().clone();
    let parameter: Digest32 = installed.child["file_sha256"]
        .as_str()
        .ok_or("child file hash")?
        .parse()?;
    let adapter: Digest32 = installed.child["adapter"]
        .as_str()
        .ok_or("child adapter")?
        .parse()?;
    let contract: Digest32 = installed.child["contract"]
        .as_str()
        .ok_or("child contract")?
        .parse()?;
    let profile = installed.worker.execution_profile_digest()?;
    let descriptor = read_pin(&json!({"path":installed.descriptor,
        "sha256":installed.descriptor_digest.to_string()}))?;
    let family: Digest32 = descriptor["model_pin"]["family_digest"]
        .as_str()
        .ok_or("descriptor family")?
        .parse()?;
    let current_before = installed
        .current
        .current_registry_view(initial_now_seconds()?)?
        .receipt();
    if installed.child["generation"] != 2
        || installed.worker.action_completions != actions
        || actions.len() != 2
        || installed.worker.python != input.python
        || installed.worker.materials != input.materials
        || current_before != installed.current_receipt
        || descriptor["model_pin"]["payload_digest"] != parameter.to_string()
        || descriptor["model_pin"]["execution_profile_digest"] != profile.to_string()
    {
        return Err("installed child differs from the next ordinary owner's immutable pins".into());
    }
    let codex_executable = codex_utils_cargo_bin::cargo_bin("codex")?.canonicalize()?;
    let (original, issuer, authority) =
        super::super::inputs(installed.worker, root, /*expected_claims*/ 2).await?;
    let journal = original.inference_journal.clone();
    let capacity = original.inference_journal_capacity;
    let grant = original.resource_grant.clone();
    let worker_id = original.worker_id.clone();
    let mut issuer = OwnedTask(Some(issuer));
    let prepared = prepare_smollm_neural_agentd_v1(
        config,
        SmolLmCognitiveHostInputsV1 {
            descriptor: installed.descriptor,
            descriptor_digest: installed.descriptor_digest,
            worker: original.worker,
            worker_id: original.worker_id,
            resource_grant: original.resource_grant,
            inference_journal: original.inference_journal,
            inference_journal_capacity: original.inference_journal_capacity,
            final_use_authorizer_config: original.final_use_authorizer_config,
        },
    )
    .await;
    let PreparedSmolLmAgentdV1 {
        config,
        session: model_session,
    } = match prepared {
        Ok(prepared) => prepared,
        Err(error) => {
            issuer.abort_and_join().await;
            let archived = super::super::archive_authority(&authority, root);
            let failure = json!({"schema":"hepta-ordinary-child-preparation-failure-v1",
                "error":error,"issuer_aborted_and_joined":true,
                "archive_error":archived.err().map(|error|error.to_string()),"ordinary_child_reads":0});
            save(&root.join("ordinary-failure.json"), &failure)?;
            return Err(failure.to_string().into());
        }
    };
    let port = model_session.port.as_ref().cloned();
    let mut running = None;
    let result: TestResult<(Value, JournalJoin)> = async {
        let port = port.as_ref().ok_or("ordinary evaluated child session missing")?;
        codex_utils_home_dir::set_process_codex_home_override(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&identity.home_root)?)?;
        let client = AgentdClient::new(identity.control_socket.clone(), identity.agent_id.clone(), identity.spawn_generation)?;
        let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(&identity.fleet_root)?)?;
        registry.compare_and_transition(&identity.agent_id, identity.spawn_generation, AgentLifecycle::Running)?;
        running = Some(OwnedTask(Some(tokio::spawn(codex_hepta_agentd::run(config,
            codex_arg0::Arg0DispatchPaths { codex_self_exe:Some(codex_executable.clone()), ..Default::default() })))));
        tokio::time::timeout(Duration::from_secs(20), async {
            loop {
                if client.health().await.is_ok_and(|health| health.ready) { break; }
                if running.as_ref().is_none_or(OwnedTask::is_finished) {
                    return Err("ordinary evaluated child exited before readiness");
                }
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
            Ok::<_, &str>(())
        }).await??;
        let context = client.cognitive_context_with_execution_v1("lemon".to_owned(), /*limit*/ 2).await?;
        let response = &context.snapshot;
        let execution = context.neural.as_ref().ok_or("ordinary child omitted neural execution")?;
        let observed_actions = response.items.iter().map(cognitive_action_id).collect::<Result<BTreeSet<_>, _>>()?;
        if response.items.len() != 2 || observed_actions != actions.keys().cloned().collect() {
            return Err("next ordinary task did not read the original two action memories".into());
        }
        let revalidated = client.revalidate_cognitive_context(response).await?;
        if revalidated.read_digest != response.read_digest || revalidated.verified_item_count != 2 {
            return Err("next task lost original cognitive context revalidation".into());
        }
        // Neural ranking may reorder the two admitted memories. Reconstruct
        // the original ordered request from its canonical payload commitment,
        // then join that independently checked payload to the cold journal.
        let ordered_actions = actions.keys().map(ToString::to_string).collect::<Vec<_>>();
        let reversed_actions = ordered_actions.iter().rev().cloned().collect::<Vec<_>>();
        let mut bound_request = None;
        for admitted_actions in [ordered_actions, reversed_actions] {
            let action_bytes = serde_json::to_vec(&admitted_actions)?;
            let payload = Digest32::of_parts(&[
                b"hepta.smollm-read-request.v1\0",
                identity.agent_id.as_str().as_bytes(),
                &identity.spawn_generation.to_be_bytes(),
                parameter.as_array(),
                profile.as_array(),
                Digest32::of_bytes(b"lemon").as_array(),
                &action_bytes,
            ]);
            if execution.forward_payload_digest.as_str() == payload.to_string()
                && bound_request.replace((payload, admitted_actions)).is_some()
            {
                return Err("next task request payload has ambiguous action order".into());
            }
        }
        let (forward_payload, admitted_actions) = bound_request
            .ok_or("next task payload differs from its owner, model, query or admitted actions")?;
        let (load_ids, forward_ids, measured) = port.with_measurements(|load, forward| {
            let forward = forward.ok_or("next task has no actual model forward")?;
            let ids = load.control_load_ids().ok_or("next task load IDs missing")?;
            let worker_input = json!({"schema":"hepta-smollm-inference-input-v1",
                "request_id":forward.control_ids().0,"prompt":"lemon"});
            let input_bytes = serde_json::to_vec(&worker_input).map_err(|error|error.to_string())?;
            if load.generation() != 2 || load.parameter_file_digest() != parameter
                || load.adapter_digest() != adapter || load.contract_digest() != contract
                || forward.ready_digest() != load.ready_digest()
                || forward.input_digest() != Digest32::of_bytes(&input_bytes)
                || execution.source != CognitiveNeuralSourceV1::EvaluatedChild
                || execution.owner_id != identity.agent_id || execution.body_generation != identity.spawn_generation
                || execution.model_generation != 2
                || execution.parameter_file_digest.as_str() != parameter.to_string()
                || execution.adapter_digest.as_str() != adapter.to_string()
                || execution.contract_digest.as_str() != contract.to_string()
                || execution.backbone_digest.as_str() != load.backbone_digest().to_string()
                || execution.ready_digest.as_str() != load.ready_digest().to_string()
                || execution.load_request_digest != Sha256Digest::for_bytes(ids.0.as_bytes())
                || execution.load_reservation_digest != Sha256Digest::for_bytes(ids.1.as_bytes())
                || execution.forward_request_digest != Sha256Digest::for_bytes(forward.control_ids().0.as_bytes())
                || execution.forward_reservation_digest != Sha256Digest::for_bytes(forward.control_ids().1.as_bytes())
                || execution.response_digest.as_str() != forward.response_digest().to_string()
                || execution.input_digest.as_str() != forward.input_digest().to_string()
                || execution.logits_digest.as_str() != forward.logits_digest().to_string()
                || execution.execution_ns != forward.execution_ns()
                || execution.input_tokens != u64::try_from(forward.input_tokens()).map_err(|error|error.to_string())?
                || execution.observed_rss_bytes != forward.observed_rss_bytes()
            {
                return Err("next task wire differs from its actual child load and forward".to_owned());
            }
            Ok(((ids.0.to_owned(),ids.1.to_owned()),
                (forward.control_ids().0.to_owned(),forward.control_ids().1.to_owned()),
                json!({"generation":load.generation(),"parameter_sha256":parameter.to_string(),
                    "adapter":load.adapter_digest().to_string(),"contract":load.contract_digest().to_string(),
                    "backbone":load.backbone_digest().to_string(),"tokenizer":load.tokenizer_digest().to_string(),
                    "ready":load.ready_digest().to_string(),"response":forward.response_digest().to_string(),
                    "actual_worker_input":worker_input,"actual_worker_input_sha256":forward.input_digest().to_string(),
                    "admitted_action_ids":admitted_actions,"forward_payload":forward_payload.to_string()})))
        })??;
        let model_digest = Digest32::of_parts(&[b"hepta.smollm-read-model.v1\0", parameter.as_array(), family.as_array(), profile.as_array()]);
        let load_payload = Digest32::of_parts(&[b"hepta.smollm-load.v1\0", identity.agent_id.as_str().as_bytes(),
            &identity.spawn_generation.to_be_bytes(), parameter.as_array(), profile.as_array()]);
        let join = JournalJoin { load_ids, forward_ids, execution:execution.clone(), owner:identity.agent_id.clone(),
            model_digest, load_payload, forward_payload, worker_id, grant };
        Ok((json!({"schema":"hepta-controlled-next-ordinary-neural-child-v1","child":measured,
            "ordinary_context_reads":1,"neural_execution_v1":execution,"read_digest":response.read_digest,
            "home_root":identity.home_root,"owner_id":identity.agent_id,"spawn_generation":identity.spawn_generation,
            "descriptor_digest":installed.descriptor_digest.to_string(),"controlled_test_issuer":true,
            "public_network_ready":false}), join))
    }.await;
    let mut last_drain = None;
    let mut stopped_generation = None;
    let mut generation_fenced_join = false;
    let stopped = tokio::time::timeout(Duration::from_secs(20), async {
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
                _ => return Err("ordinary child is outside the original drain lifecycle".into()),
            };
            let client = AgentdClient::new(
                identity.control_socket.clone(),
                identity.agent_id.clone(),
                identity.spawn_generation,
            )?;
            let mut poll = tokio::time::interval(Duration::from_millis(20));
            poll.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
            loop {
                poll.tick().await;
                let observed = client.drain().await?;
                let complete = observed.admission_closed
                    && observed.drained
                    && observed.running_turns == 0
                    && !observed.fenced
                    && observed.lifecycle == AgentLifecycle::Draining;
                let invalid = observed.fenced
                    || observed.lifecycle != AgentLifecycle::Draining
                    || !observed.admission_closed;
                last_drain = Some(observed);
                if invalid {
                    return Err("ordinary child drain lost its owner fence".into());
                }
                if complete {
                    break;
                }
            }
            registry.compare_and_transition(
                &identity.agent_id,
                draining.generation,
                AgentLifecycle::Stopped,
            )?;
            let outcome = task.finish().await?;
            if !matches!(outcome, Err(AgentdError::GenerationFenced(_))) {
                return Err(format!(
                    "ordinary child did not return original generation fence: {outcome:?}"
                )
                .into());
            }
            generation_fenced_join = true;
            let terminal = registry.load_agent(&identity.agent_id)?.lifecycle;
            if terminal.lifecycle != AgentLifecycle::Stopped {
                return Err("ordinary child registry did not retain Stopped".into());
            }
            stopped_generation = Some(terminal.generation);
        }
        Ok::<(), Box<dyn std::error::Error>>(())
    })
    .await;
    let stop_result: TestResult<()> = match stopped {
        Ok(result) => result,
        Err(_) => Err("ordinary child drain and stop exceeded original 20s deadline".into()),
    };
    if let Some(task) = running.as_mut() {
        task.abort_and_join().await;
    }
    let model_shutdown = model_session.shutdown().await;
    drop(port);
    let issuer_result: TestResult<()> =
        if result.is_ok() && stop_result.is_ok() && model_shutdown.is_ok() {
            match issuer.finish().await {
                Ok(outcome) => outcome.map_err(super::super::issuer_error),
                Err(error) => Err(error.into()),
            }
        } else {
            issuer.abort_and_join().await;
            Ok(())
        };
    let archived = super::super::archive_authority(&authority, root);
    let tail: TestResult<Value> = (|| {
        let (_, join) = result.as_ref().map_err(ToString::to_string)?;
        let cold = cold_journal(&journal, capacity, join)?;
        let current_after = installed
            .current
            .current_registry_view(initial_now_seconds()?)?
            .receipt();
        if current_after != current_before {
            return Err("ordinary child task changed original CURRENT".into());
        }
        Ok(
            json!({"original_journal":cold,"current_before":current_before.head_digest.to_string(),
            "current_after":current_after.head_digest.to_string(),"current_record_count":current_after.records,
            "current_file_digest":current_after.file_digest.to_string()}),
        )
    })();
    let stop_record = save(
        &root.join("ordinary-runtime-stop.json"),
        &json!({
        "schema":"hepta-ordinary-runtime-stop-v1","stop_budget_seconds":20,
        "last_original_drain_response":last_drain,"stopped_registry_generation":stopped_generation,
        "generation_fenced_task_join":generation_fenced_join,
        "error":stop_result.as_ref().err().map(ToString::to_string),
        "model_terminal_unload_observed":model_shutdown.is_ok()}),
    );
    if result.is_err()
        || stop_result.is_err()
        || model_shutdown.is_err()
        || issuer_result.is_err()
        || archived.is_err()
        || tail.is_err()
        || stop_record.is_err()
    {
        let failure = json!({"schema":"hepta-ordinary-child-session-failure-v1",
            "ordinary":result.as_ref().err().map(ToString::to_string),
            "runtime_stop":stop_result.err().map(|error|error.to_string()),
            "model_shutdown":model_shutdown.err(),"issuer":issuer_result.err().map(|error|error.to_string()),
            "archive":archived.err().map(|error|error.to_string()),"cold_readback":tail.err().map(|error|error.to_string()),
            "stop_record":stop_record.err().map(|error|error.to_string()),"completion_verified":false});
        save(&root.join("ordinary-failure.json"), &failure)?;
        return Err(failure.to_string().into());
    }
    let (mut report, _) = result?;
    report["readback"] = tail?;
    report["model_terminal_unload_observed"] = json!(true);
    report["original_final_use_claims"] = json!(2);
    save(&root.join("ordinary-child-session-result.json"), &report)?;
    Ok(report)
}
