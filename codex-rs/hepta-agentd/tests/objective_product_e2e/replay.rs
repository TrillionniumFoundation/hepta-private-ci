//! Delayed acknowledgement must replay publication, not readmit stale source.
use super::*;

fn utc_timestamp(now: SystemTime) -> Result<String> {
    let seconds = libc::time_t::try_from(now.duration_since(UNIX_EPOCH)?.as_secs())?;
    let mut broken_down = std::mem::MaybeUninit::<libc::tm>::uninit();
    // Both pointers refer to live, correctly aligned local objects. gmtime_r
    // initializes the output on success; the null branch never reads it.
    let result = unsafe { libc::gmtime_r(&seconds, broken_down.as_mut_ptr()) };
    ensure!(!result.is_null(), "UTC conversion failed");
    // The non-null return above proves the C routine initialized the structure.
    let time = unsafe { broken_down.assume_init() };
    Ok(format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        time.tm_year + 1900,
        time.tm_mon + 1,
        time.tm_mday,
        time.tm_hour,
        time.tm_min,
        time.tm_sec
    ))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn delayed_exact_ack_replay_survives_source_age_but_not_revocation() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let agent = fleet.register(
        "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c35",
        "objective-delayed-ack",
    )?;
    let model = responses::start_mock_server().await;
    MockResponsesConfig::new(&model.uri())
        .with_model(MODEL)
        .disable_feature(codex_features::Feature::Plugins)
        .write(agent.layout.home_root())?;
    std::fs::set_permissions(
        agent.layout.home_root(),
        std::fs::Permissions::from_mode(0o700),
    )?;
    let key = SigningKey::from_bytes(&[118; 32]);
    let files = configure_objective_files(&agent, &key).await?;
    let mut profile = objective_profile();
    profile["maximumSourceAgeMicros"] = json!(5_000_000_u64);
    write_private_json(&files.profile_file, &profile)?;
    fleet.start_with_objective_files(
        &agent,
        &files.trust_file,
        &files.authbus_checkpoint_file,
        &files.profile_file,
        &files.objective_checkpoint_file,
    )?;
    let (control, _) = fleet.wait_ready(&agent, 1).await?;

    // Capture source time only after readiness; startup never consumes this
    // admission window. AuthBus lifetime and objective deadline remain live.
    let now = SystemTime::now();
    let mut source: Value = serde_json::from_str(&source_envelope_json()?)?;
    source["observedAt"] = json!(utc_timestamp(now)?);
    source["deadline"] = json!(utc_timestamp(now + Duration::from_secs(120))?);
    let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(&source)?)?;
    source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&decoded)?.to_string());
    let source = serde_json::to_string(&source)?;
    let request = signed_objective_with_source(
        &agent.agent_id,
        &key,
        1,
        1,
        "run.objective.delayed-ack",
        source.clone(),
    )?;
    let first = admitted(control.objective_start(request.clone()).await?)?;
    ensure!(!first.idempotent);
    tokio::time::sleep(Duration::from_secs(6)).await;

    // A new operation with these stale source bytes still must fail admission.
    let fresh_operation = signed_objective_with_source(
        &agent.agent_id,
        &key,
        1,
        2,
        "run.objective.stale-new",
        source,
    )?;
    ensure!(
        control.objective_start(fresh_operation).await.is_err(),
        "new stale source admitted"
    );
    let replay = admitted(control.objective_start(request.clone()).await?)?;
    let mut expected = first;
    expected.idempotent = true;
    ensure!(
        replay == expected,
        "delayed acknowledgement changed the original publication"
    );
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 1)?;

    let mut trust: Value = serde_json::from_slice(&std::fs::read(&files.trust_file)?)?;
    trust["revoked"] = json!(true);
    write_private_json(&files.trust_file, &trust)?;
    ensure!(
        control.objective_start(request).await.is_err(),
        "revoked exact retry accepted"
    );
    assert_checkpoint(&files.objective_checkpoint_file, &agent.agent_id, 1)?;
    Ok(())
}
