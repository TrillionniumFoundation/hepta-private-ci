//! Real selected initial load and same-authority cold recovery.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the original pinned model configuration with canonical selected gen1 zero material"]
async fn real_selected_initial_load_fresh_current_and_old_trait_refusal() -> TestResult<()> {
    let (input, worker, bytes) = input_and_worker("selected-initial-positive")?;
    let fixture = Fixture::new(input.output.join("positive-owner"), &bytes)?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    let selection = material.selection_digest();
    let parameter = material.manifest().content_digest;
    let profile = worker.execution_profile_digest()?;
    let family: Digest32 =
        worker.source_identities()?["model-family-smollm2-135m-v1.json"].parse()?;
    let (inputs, issuer, authority) = inputs(
        worker,
        &input.output.join("positive-effects"),
        /*expected_claims*/ 2,
    )
    .await?;
    let journal = inputs.inference_journal.clone();
    let authority_config = inputs.final_use_authorizer_config.clone();
    let resource = inputs.resource_grant.clone();
    let mut owner = prepare_selected_initial_smollm_v1(
        fixture.config("positive-body")?,
        material,
        current,
        inputs,
    )
    .await?;
    let evidence = owner.with_current_initial_load(|proof| {
        assert_eq!(proof.selection_digest(), selection);
        assert_eq!(proof.measured().parameter_file_digest(), parameter);
        assert_eq!(proof.measured().generation(), 1);
        Ok(serde_json::json!({
            "schema": "hepta-selected-initial-actual-load-observation-v1",
            "actual_ready_sha256": proof.measured().ready_digest().to_string(),
            "actual_parameter_sha256": proof.measured().parameter_file_digest().to_string(),
            "actual_generation": proof.measured().generation(),
            "actual_backbone": proof.measured().backbone_digest().to_string(),
            "actual_tokenizer": proof.measured().tokenizer_digest().to_string(),
            "actual_contract": proof.measured().contract_digest().to_string(),
            "original_control_load_ids": proof.measured().control_load_ids(),
            "selected_digest": proof.selection_digest().to_string(),
            "authority": "DENY_ALL",
            "installed": false,
            "ordinary_task_used": false,
            "direct_raw_upstream_file_sha_observed": false,
        }))
    })?;
    fs::write(
        input.output.join("actual-selected-initial-load.json"),
        serde_json::to_vec_pretty(&evidence)?,
    )?;
    let before = fs::read(&journal)?;
    let request = NeuralCognitiveRequestV1 {
        owner_id: owner.identity().agent_id.clone(),
        body_generation: 1,
        pin: codex_hepta_agentd::NeuralCognitivePinV1 {
            payload_digest: parameter,
            objective_digest: digest("test-not-efficacy"),
            dataset_digest: digest("test-not-evaluation"),
            generation: Generation::new(/*value*/ 1)?,
            family_digest: family,
            execution_profile_digest: profile,
        },
        query: "initial must not enter evaluated mode".to_owned(),
        query_digest: digest("initial must not enter evaluated mode"),
        action_ids: vec![id("native-answer-no")],
    };
    let port = owner.session.port.as_ref().unwrap();
    assert!(
        port.execute(
            &request,
            &bytes,
            &codex_hepta_agentd::NeuralCognitiveExecutionV1::bounded_read()
        )
        .unwrap_err()
        .contains("initial-only")
    );
    assert_eq!(fs::read(&journal)?, before);
    let ready: Digest32 = evidence["actual_ready_sha256"].as_str().unwrap().parse()?;
    assert!(!ready.is_zero());
    let held = Arc::clone(owner.session.port.as_ref().unwrap());
    let expected = Arc::clone(&held);
    let (reached_tx, reached_rx) = tokio::sync::oneshot::channel();
    let (release_tx, release_rx) = std::sync::mpsc::channel();
    let observer = tokio::task::spawn_blocking(move || {
        held.with_measurements(|_, _| {
            reached_tx.send(()).unwrap();
            release_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
        })
    });
    reached_rx.await?;
    assert!(owner.shutdown().await.is_err());
    assert!(Arc::ptr_eq(owner.session.port.as_ref().unwrap(), &expected));
    assert!(owner.with_current_initial_load(|_| Ok(())).is_err());
    release_tx.send(())?;
    observer.await??;
    owner.shutdown().await?;
    assert!(owner.with_current_initial_load(|_| Ok(())).is_err());
    drop(owner);
    drop(expected);
    let first_load = evidence["original_control_load_ids"][0].as_str().unwrap();
    let first_record = DurableInferenceControl::open(&journal, /*capacity*/ 8)?
        .get(first_load)
        .cloned()
        .ok_or("missing original settled load")?;
    let (_, worker, _) = input_and_worker("selected-initial-cold")?;
    let (material, current) = fixture.selected(/*revoked_at*/ None)?;
    assert_eq!(material.selection_digest(), selection);
    let inputs = SmolLmInitialHostInputsV1 {
        worker,
        worker_id: "selected-initial-native-worker".to_owned(),
        resource_grant: resource,
        inference_journal: journal.clone(),
        inference_journal_capacity: 8,
        final_use_authorizer_config: authority_config,
    };
    let mut cold =
        prepare_selected_initial_smollm_v1(fixture.config("cold-body")?, material, current, inputs)
            .await?;
    let (cold_ready, cold_load) = cold.with_current_initial_load(|proof| {
        assert_eq!(proof.selection_digest(), selection);
        assert_eq!(proof.measured().parameter_file_digest(), parameter);
        Ok((
            proof.measured().ready_digest(),
            proof.measured().control_load_ids().unwrap().0.to_owned(),
        ))
    })?;
    assert!(!cold_ready.is_zero());
    assert_ne!(cold_load, first_load);
    cold.shutdown().await?;
    drop(cold);
    let reopened = DurableInferenceControl::open(&journal, /*capacity*/ 8)?;
    assert_eq!(reopened.get(first_load), Some(&first_record));
    assert!(reopened.get(&cold_load).is_some());
    issuer.await?.map_err(issuer_error)?;
    archive_authority(&authority, &input.output)?;
    Ok(())
}
