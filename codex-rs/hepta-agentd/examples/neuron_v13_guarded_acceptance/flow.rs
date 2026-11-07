//! Actual signed publication, ordinary runtime reopen and same-model next task.

use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_arg0::Arg0DispatchPaths;
use codex_hepta_agentd::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_neuron::*;
use codex_hepta_types::Digest32;
use serde_json::Value;
use tokio::time::sleep;
use tokio::time::timeout;

use super::super::lifecycle::Host;
use super::super::lifecycle::ShutdownExpectation;
use super::super::lifecycle::host_config;
use super::super::lifecycle::ordinary_session;
use super::Inputs;
use super::acknowledge;
use super::assembly::Assets;
use super::authority::Authority;
use super::directory;
use super::owner_bytes;
use super::save;
use super::task;

pub(super) async fn execute(
    inputs: &Inputs,
    host: Host,
    arg0_paths: &Arg0DispatchPaths,
) -> Result<Value> {
    let Inputs {
        descriptor,
        expected,
        output,
        root_authority: root_path,
        second_task,
        task_sha,
    } = inputs;
    let (expected, task_sha) = (*expected, *task_sha);
    let Host { registry, config } = host;
    let task_file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(second_task)?;
    ensure!(
        second_task.is_absolute()
            && task_file.metadata()?.is_file()
            && task_file.metadata()?.len() <= 8192,
        "second task must be a bounded actual regular file"
    );
    let mut task_bytes = String::new();
    task_file.take(8193).read_to_string(&mut task_bytes)?;
    ensure!(
        task_bytes.len() <= 8192,
        "second task grew beyond its bound"
    );
    ensure!(
        Digest32::of_bytes(task_bytes.as_bytes()) == task_sha,
        "second task SHA differs"
    );
    let next_task: V13TaskInputV1 = serde_json::from_str(&task_bytes)?;
    next_task.encode()?;
    let assets = Assets::load(descriptor, expected)?;
    ensure!(
        assets.input.task.encode()? != next_task.encode()?,
        "next task must be independent of the first input"
    );
    let identity = config.identity().clone();
    let mut admission =
        assets.configuration(&identity, &assets.input.task, /*generation*/ 1)?;
    directory(root_path)?;
    let root = RootAuthorityDirectory::open(root_path)?;
    let authority = Authority::new(
        root,
        output,
        &admission.generation.manifest,
        Digest32::from_array(assets.input.closure.data_identity),
    )?;
    let options = || AgentdGenerationUpdateRuntimeOptionsV1 {
        queue_capacity: 4,
        control_endpoint: false,
    };
    let first_path = output.join("first-owner");
    directory(&first_path)?;
    let prepared = prepare_agentd_v13_generation_initial_v1(
        authority.root.clone(),
        authority.authorities()?,
        authority
            .artifacts
            .selection(authority.clock.now_unix_ms()?)?,
        assets.inputs(
            &identity,
            admission.clone(),
            &first_path,
            V13GenerationOwnerModeV1::InitializeEmpty,
        )?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "qualification-initial-publication".into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = authority.sign(prepared.final_use_binding())?;
    let AgentdGenerationInitialRuntimeV1 {
        config,
        handle,
        publication,
    } = prepared.publish(&signed)?.into_runtime(config, options())?;
    ensure!(
        authority.final_use.capacity()?.used_nonces == 1,
        "initial publication did not claim exactly one nonce"
    );
    save(
        &output.join("INITIAL-PUBLICATION.json"),
        &serde_json::json!({
            "intent_digest": publication.intent_digest().to_string(), "signed_grant": publication.signed_grant(),
            "witness": publication.witness(), "target": publication.target(),
        }),
    )?;
    let first = ordinary_session(
        config,
        arg0_paths,
        &registry,
        ShutdownExpectation::UnacknowledgedOutput,
        || async {
            let result = task(
                &handle,
                &assets,
                &admission.generation,
                &assets.input.task,
                "qualification-first-inference",
            )
            .await?;
            save(&output.join("FIRST-UNACKNOWLEDGED.json"), &result)?;
            Ok(result)
        },
    )
    .await?;
    save(
        &output.join("FIRST-SHUTDOWN.json"),
        &serde_json::json!({ "observed_error": first.shutdown_error }),
    )?;
    drop(handle);
    let retained = owner_bytes(&first_path)?;
    let current = Arc::new(NeuronGenerationCurrentOwnerV1::open(
        authority.root.clone(),
        &admission.generation.initial.scope,
    )?);
    registry.compare_and_transition(
        &identity.agent_id,
        /*expected_generation*/ 4,
        AgentLifecycle::Starting,
    )?;
    let config = host_config(&identity, /*spawn*/ 5)?;
    let reopened_identity = config.identity().clone();
    admission.expected_identity_digest =
        neuron_generation_process_identity_digest_v1(&reopened_identity)?;
    let ready = timeout(Duration::from_secs(5), async {
        loop {
            match recover_agentd_v13_generation_initial_v1(
                current.clone(),
                authority.authorities()?,
                authority
                    .artifacts
                    .selection(authority.clock.now_unix_ms()?)?,
                assets.inputs(
                    &reopened_identity,
                    admission.clone(),
                    &first_path,
                    V13GenerationOwnerModeV1::Reopen,
                )?,
                AgentdGenerationUpdateRecoveryV1 {
                    operation_id: "qualification-initial-publication".into(),
                    intent_digest,
                },
            ) {
                Ok(value) => return Ok::<_, anyhow::Error>(value),
                Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                    sleep(Duration::from_millis(1)).await
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await??;
    let AgentdGenerationInitialRuntimeV1 { config, handle, .. } =
        ready.into_runtime(config, options())?;
    ensure!(
        owner_bytes(&first_path)? == retained,
        "exact recovery wrote duplicate cost or control state"
    );
    let recovered = ordinary_session(
        config,
        arg0_paths,
        &registry,
        ShutdownExpectation::Drained,
        || async {
            ensure!(
                handle.observe_generation().await? == first.value.observation,
                "recovery changed original owner observation"
            );
            ensure!(
                handle.step(first.value.request.clone()).await? == first.value.receipt,
                "exact retry changed original result"
            );
            ensure!(
                owner_bytes(&first_path)? == retained,
                "exact retry redispatched or rewrote owner history"
            );
            acknowledge(&handle, &first.value, &output.join("FIRST-DELIVERED.jsonl")).await
        },
    )
    .await?;
    drop(handle);
    ensure!(
        authority.final_use.capacity()?.used_nonces == 1,
        "recovery consumed another nonce"
    );
    let old = owner_bytes(&first_path)?;
    save(&output.join("FIRST-CHECKPOINT.json"), &recovered.value.1)?;

    registry.compare_and_transition(
        &identity.agent_id,
        /*expected_generation*/ 8,
        AgentLifecycle::Starting,
    )?;
    let config = host_config(&identity, /*spawn*/ 9)?;
    let next_identity = config.identity().clone();
    admission.expected_identity_digest =
        neuron_generation_process_identity_digest_v1(&next_identity)?;
    let predecessor = timeout(Duration::from_secs(5), async {
        loop {
            match assets
                .inputs(
                    &next_identity,
                    admission.clone(),
                    &first_path,
                    V13GenerationOwnerModeV1::Reopen,
                )?
                .reopen_predecessor()
            {
                Ok(value) => return Ok::<_, anyhow::Error>(value),
                Err(AgentdError::Invalid(message)) if message == "WriterUnavailable" => {
                    sleep(Duration::from_millis(1)).await
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await??;
    let next_assets = Assets::load(descriptor, expected)?;
    let next = next_assets.configuration(&next_identity, &next_task, /*generation*/ 2)?;
    ensure!(
        next.generation.manifest == admission.generation.manifest,
        "same-model task changed the actual model/runtime binding"
    );
    let next_path = output.join("second-owner");
    directory(&next_path)?;
    let prepared = prepare_agentd_v13_generation_cold_same_model_task_v1(
        current.clone(),
        authority.authorities()?,
        predecessor,
        authority
            .artifacts
            .selection(authority.clock.now_unix_ms()?)?,
        next_assets.inputs(
            &next_identity,
            next.clone(),
            &next_path,
            V13GenerationOwnerModeV1::InitializeEmpty,
        )?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "qualification-next-task-publication".into(),
        },
    )?;
    ensure!(
        prepared.final_use_binding().destination_id
            == "agentd.cell-generation.next-task-same-model",
        "handoff FinalUse purpose differs"
    );
    let signed = authority.sign(prepared.final_use_binding())?;
    let AgentdGenerationUpdateRuntimeV1 {
        config,
        handle,
        publication,
    } = prepared.publish(&signed)?.into_runtime(config, options())?;
    ensure!(
        authority.final_use.capacity()?.used_nonces == 2,
        "next task did not claim its own nonce"
    );
    let old_binding =
        CellGenerationOwnerBindingV1::new(&admission.generation, admission.max_records)?;
    ensure!(
        current.check_current(&old_binding) == Err(CellGenerationErrorV2::InvalidBinding),
        "old generation remains current"
    );
    ensure!(
        owner_bytes(&first_path)? == old,
        "handoff rewrote predecessor history"
    );
    save(
        &output.join("NEXT-PUBLICATION.json"),
        &serde_json::json!({
            "intent_digest": publication.intent_digest().to_string(), "signed_grant": publication.signed_grant(),
            "witness": publication.witness(), "target": publication.target(), "completion": publication.completion(),
        }),
    )?;
    let second = ordinary_session(
        config,
        arg0_paths,
        &registry,
        ShutdownExpectation::Drained,
        || async {
            let result = task(
                &handle,
                &next_assets,
                &next.generation,
                &next_task,
                "qualification-second-inference",
            )
            .await?;
            save(&output.join("SECOND-UNACKNOWLEDGED.json"), &result)?;
            let committed = owner_bytes(&next_path)?;
            ensure!(
                handle.step(result.request.clone()).await? == result.receipt
                    && owner_bytes(&next_path)? == committed,
                "next-task retry mutated the original operation"
            );
            acknowledge(&handle, &result, &output.join("SECOND-DELIVERED.jsonl")).await
        },
    )
    .await?;
    drop(handle);
    save(&output.join("SECOND-CHECKPOINT.json"), &second.value.1)?;
    ensure!(
        owner_bytes(&first_path)? == old,
        "successor execution rewrote predecessor"
    );
    Ok(serde_json::json!({
        "schema": "hepta.v13.guarded-qualification-result.v1", "authority": "DENY_ALL",
        "descriptor_sha256": expected.to_string(), "second_task_sha256": task_sha.to_string(),
        "actual_profile": V13GenerationProcessWorkerV1::PROFILE,
        "initial_publication": intent_digest.to_string(), "next_publication": publication.intent_digest().to_string(),
        "first_delivery_sha256": recovered.value.0.to_string(), "second_delivery_sha256": second.value.0.to_string(),
        "first_checkpoint": recovered.value.1, "second_checkpoint": second.value.1,
        "final_use_claims": authority.final_use.capacity()?.used_nonces,
        "fixture_issuer_keys_are_public": true, "delivery_scope": "local_fsynced_receiver_file",
        "recovery_scope": "ordinary_runtime_instance_reopen_in_same_runner_process",
        "fresh_process_or_host_restart_qualified": false,
        "unknown_publication_fault_campaign_executed": false,
        "production_privilege_separation_qualified": false,
        "cross_owner_atomic_transaction": false, "cryptographic_computation_proof_verified": false,
        "external_delivery_qualified": false, "production_adoption": false,
        "quality_qualification": false, "work_cost_eligibility": false, "included_in_junit": false,
    }))
}
