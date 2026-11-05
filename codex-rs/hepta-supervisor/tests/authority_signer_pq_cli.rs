//! Actual offline CLI ceremonies. Deterministic fixture keys are test inputs;
//! neither a successful signature nor this fixture certifies production custody.
#![cfg(all(unix, feature = "production-authority"))]
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_memory::H7ArtifactVerifier;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ProductionAuthorityPolicyV1;
use codex_hepta_supervisor::ProductionAuthorityRoleV1;
use codex_hepta_supervisor::ProductionRecoveryOutcome;
use codex_hepta_supervisor::SignRequest;
use codex_hepta_supervisor::SignResponse;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

fn role(name: &str, seed: u8) -> TestResult<ProductionAuthorityRoleV1> {
    let seed = zeroize::Zeroizing::new([seed; 32]);
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    Ok(ProductionAuthorityRoleV1 {
        signer_id: name.to_string(),
        signer_epoch: 7,
        public_key_id: ml_dsa_65_key_id_from_spki(&spki)?,
        public_spki_base64: STANDARD.encode(spki),
    })
}

fn private_file(path: &Path, seed: u8) -> TestResult {
    let mut file = std::fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(&[seed; 32])?;
    file.sync_all()?;
    Ok(())
}

fn run_cli(
    root: &Path,
    request: &SignRequest,
    key: &Path,
    profile: Option<&str>,
    policy: Option<&Path>,
) -> TestResult<(bool, Vec<u8>)> {
    let request_path = root.join("request.json");
    std::fs::write(&request_path, serde_json::to_vec(request)?)?;
    let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-authority-signer")?);
    command
        .arg("--sign")
        .arg("--key-file")
        .arg(key)
        .arg("--request")
        .arg(&request_path)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(profile) = profile {
        command.arg("--profile").arg(profile);
    }
    if let Some(policy) = policy {
        command.arg("--policy").arg(policy);
    }
    let mut child = command.spawn()?;
    let stdout = child.stdout.take().ok_or("missing stdout")?;
    let stderr = child.stderr.take().ok_or("missing stderr")?;
    let stdout_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout.take(65_537).read_to_end(&mut bytes).map(|_| bytes)
    });
    let stderr_reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        stderr.take(65_537).read_to_end(&mut bytes).map(|_| bytes)
    });
    let deadline = Instant::now() + Duration::from_secs(8);
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            child.kill()?;
            child.wait()?;
            let _ = stdout_reader.join();
            let _ = stderr_reader.join();
            return Err("owned signer child exceeded its eight-second test deadline".into());
        }
        std::thread::sleep(Duration::from_millis(5));
    };
    let stdout = stdout_reader
        .join()
        .map_err(|_| "stdout reader panicked")??;
    let stderr = stderr_reader
        .join()
        .map_err(|_| "stderr reader panicked")??;
    assert!(stdout.len() <= 65_536 && stderr.len() <= 65_536);
    if !status.success() {
        assert!(
            stdout.is_empty(),
            "rejected ceremony must emit no signed output"
        );
    }
    Ok((status.success(), stdout))
}

fn envelope_request() -> TestResult<SignRequest> {
    let mut runtime = H7QualificationRuntime::new();
    let event = H7TrajectoryEvent::new(
        "pq-cli",
        /*event_seq*/ 1,
        "reload",
        /*reward_bps*/ 100,
        /*safety_ok*/ true,
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        Sha256Digest::for_bytes(b"pq-cli-fixture"),
    )?;
    runtime.append_trajectory_event(event)?;
    runtime.evaluate_trajectory("pq-cli")?;
    Ok(SignRequest::H7Envelope {
        signer_id: "artifact".to_string(),
        signer_epoch: 7,
        artifact: runtime.propose_artifact("pq-cli-artifact", "pq-cli", /*generation*/ 1)?,
        ope: None,
        transition: H7SignedArtifactTransition::Reload,
        expected_runtime_generation: 0,
        predecessor_artifact_sha256: None,
        issued_at_unix_seconds: 100,
        expires_at_unix_seconds: 500,
    })
}

// Public wire fixture construction is independent of the daemon's private
// journal writer. These bytes test the offline ceremony, not live permission.
fn fixture_digest(intent: &mut codex_hepta_supervisor::SignedSupervisorIntent) -> TestResult {
    let payload = serde_json::to_vec(&(
        intent.schema_version,
        &intent.grant_sha256,
        &intent.agent_id,
        intent.transition,
        &intent.source_release,
        &intent.target_release,
        intent.expected_control_revision,
        intent.expected_lifecycle_generation,
        intent.authority_epoch,
        intent.status,
    ))?;
    let mut bytes = if intent.schema_version == 3 {
        b"hepta-supervisor:signed-intent:ml-dsa65:v3".to_vec()
    } else {
        b"hepta-supervisor:signed-intent:v2".to_vec()
    };
    bytes.extend(payload);
    bytes.extend(serde_json::to_vec(&intent.unknown_effects)?);
    if intent.schema_version == 3 {
        bytes.extend(serde_json::to_vec(&intent.pq_authority)?);
    }
    intent.intent_sha256 = Sha256Digest::for_bytes(&bytes);
    intent.validate()?;
    Ok(())
}

#[test]
fn explicit_pq_cli_signs_three_independent_roles_and_refuses_wrong_secrets() -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let policy = ProductionAuthorityPolicyV1 {
        schema_version: 1,
        algorithm: "ml_dsa65_v2".to_string(),
        grant: role("grant", /*seed*/ 111)?,
        artifact: role("artifact", /*seed*/ 112)?,
        recovery: role("recovery", /*seed*/ 113)?,
    };
    let policy_bytes = serde_json::to_vec(&policy)?;
    let policy_path = root.join("policy.json");
    std::fs::write(&policy_path, &policy_bytes)?;
    let grant_key = root.join("grant.key");
    let artifact_key = root.join("artifact.key");
    let recovery_key = root.join("recovery.key");
    private_file(&grant_key, /*seed*/ 111)?;
    private_file(&artifact_key, /*seed*/ 112)?;
    private_file(&recovery_key, /*seed*/ 113)?;
    let (ok, output) = run_cli(
        &root,
        &envelope_request()?,
        &artifact_key,
        Some("ml_dsa65_v2"),
        Some(&policy_path),
    )?;
    assert!(ok);
    let SignResponse::H7Envelope { envelope } = serde_json::from_slice(&output)? else {
        return Err("wrong artifact response".into());
    };
    let spki = STANDARD.decode(&policy.artifact.public_spki_base64)?;
    H7ArtifactVerifier::from_pinned_spki(
        "artifact",
        /*signer_epoch*/ 7,
        &spki,
        policy.artifact.public_key_id,
    )?
    .verify_envelope_signature(&envelope, /*now_unix_seconds*/ 200)?;
    assert!(envelope.qualification_only);
    assert!(!envelope.production_authority && !envelope.promotion_eligible);
    let request = SignRequest::ProductionGrant {
        signer_id: "grant".to_string(),
        signer_epoch: 7,
        h7_envelope: envelope.clone(),
        agent_id: AGENT.to_string(),
        source_release: "v1".to_string(),
        target_release: "v2".to_string(),
        transition: H7H89ProductionTransition::Upgrade,
        expected_control_revision: 3,
        expected_lifecycle_generation: 5,
        authority_epoch: 47,
        issued_at_unix_seconds: 100,
        expires_at_unix_seconds: 400,
    };
    assert!(
        !run_cli(
            &root,
            &request,
            &recovery_key,
            Some("ml_dsa65_v2"),
            Some(&policy_path)
        )?
        .0
    );
    let (ok, output) = run_cli(
        &root,
        &request,
        &grant_key,
        Some("ml_dsa65_v2"),
        Some(&policy_path),
    )?;
    assert!(ok);
    let SignResponse::ProductionGrant { grant } = serde_json::from_slice(&output)? else {
        return Err("wrong grant response".into());
    };
    let verifier = H7H89ProductionGrantVerifier::from_pq_policy_bytes(&policy_bytes)?;
    let agent = AgentId::parse(AGENT)?;
    verifier.verify(
        &grant, &envelope, &agent, "v1", "v2", /*expected_control_revision*/ 3,
        /*expected_lifecycle_generation*/ 5, /*expected_authority_epoch*/ 47,
        /*now_unix_seconds*/ 200,
    )?;
    let intent = Sha256Digest::for_bytes(b"intent");
    let transaction = Sha256Digest::for_bytes(b"transaction");
    let manifest = Sha256Digest::for_bytes(b"manifest");
    let program = Sha256Digest::for_bytes(b"program");
    let recovery = SignRequest::ProductionRecovery {
        signer_id: "recovery".to_string(),
        signer_epoch: 7,
        agent_id: AGENT.to_string(),
        grant_sha256: grant.grant_sha256.clone(),
        intent_sha256: intent.clone(),
        release_transaction_sha256: transaction.clone(),
        observed_release: "v2".to_string(),
        observed_manifest_sha256: manifest.clone(),
        observed_agentd_sha256: program.clone(),
        observed_matrixd_sha256: None,
        outcome: ProductionRecoveryOutcome::Committed,
        expected_lifecycle_generation: 5,
        authority_epoch: 47,
        issued_at_unix_seconds: 100,
        expires_at_unix_seconds: 400,
    };
    assert!(
        !run_cli(
            &root,
            &recovery,
            &grant_key,
            Some("ml_dsa65_v2"),
            Some(&policy_path)
        )?
        .0
    );
    let (ok, output) = run_cli(
        &root,
        &recovery,
        &recovery_key,
        Some("ml_dsa65_v2"),
        Some(&policy_path),
    )?;
    assert!(ok);
    let SignResponse::ProductionRecovery { decision } = serde_json::from_slice(&output)? else {
        return Err("wrong recovery response".into());
    };
    verifier.verify_recovery(
        &decision,
        &agent,
        &grant.grant_sha256,
        &intent,
        &transaction,
        "v2",
        &manifest,
        &program,
        /*expected_matrixd_sha256*/ None,
        /*expected_lifecycle_generation*/ 5,
        /*expected_authority_epoch*/ 47,
        /*now_unix_seconds*/ 200,
    )?;
    assert_eq!(
        decision.pq_authority.as_ref().unwrap().signer_public_key_id,
        policy.recovery.public_key_id
    );
    // The same independent recovery role signs an explicit Unknown disposition;
    // it never fabricates a completed release transaction.
    let unknown_intent = codex_hepta_supervisor::SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        AGENT,
        H7H89ProductionTransition::Upgrade,
        "v1",
        "v2",
        /*expected_control_revision*/ 3,
        /*expected_lifecycle_generation*/ 5,
        /*authority_epoch*/ 47,
        codex_hepta_supervisor::SignedIntentStatus::RecoveryRequired,
    )?;
    let unknown: SignRequest = serde_json::from_value(serde_json::json!({
        "operation":"abandon_unknown", "signer_id":"recovery", "signer_epoch":7,
        "intent":unknown_intent,
        "source":{"release_id":"v1", "manifest_sha256":manifest, "agentd_program_sha256":program,
            "matrixd_program_sha256":null, "admission_frontier_sha256":Sha256Digest::for_bytes(b"frontier")},
        "release_state_generation":2, "lifecycle_generation":5, "authority_epoch":47,
        "issued_at_unix_seconds":100, "expires_at_unix_seconds":400
    }))?;
    assert!(
        !run_cli(
            &root,
            &unknown,
            &artifact_key,
            Some("ml_dsa65_v2"),
            Some(&policy_path)
        )?
        .0
    );
    let (ok, output) = run_cli(
        &root,
        &unknown,
        &recovery_key,
        Some("ml_dsa65_v2"),
        Some(&policy_path),
    )?;
    assert!(ok);
    let SignResponse::ProductionRecovery { decision } = serde_json::from_slice(&output)? else {
        return Err("wrong Unknown response".into());
    };
    verifier.verify_recovery(
        &decision,
        &agent,
        &grant.grant_sha256,
        &unknown_intent.intent_sha256,
        &codex_hepta_supervisor::absent_release_transaction_digest(),
        "v1",
        &manifest,
        &program,
        /*expected_matrixd_sha256*/ None,
        /*expected_lifecycle_generation*/ 5,
        /*expected_authority_epoch*/ 47,
        /*now_unix_seconds*/ 200,
    )?;
    assert_eq!(decision.outcome, ProductionRecoveryOutcome::AbandonUnknown);
    assert_eq!(
        decision.pq_authority.as_ref().unwrap().signer_public_key_id,
        policy.recovery.public_key_id
    );
    // Confirming an already retained PQ Unknown over legacy provenance does
    // not invent a PQ grant proof or append another history entry.
    let mut unknown_closed = unknown_intent.clone();
    unknown_closed.schema_version = 2;
    unknown_closed.status = codex_hepta_supervisor::SignedIntentStatus::Aborted;
    unknown_closed
        .unknown_effects
        .push(codex_hepta_supervisor::UnknownEffectDisposition {
            target_release: "v2".to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            decision,
        });
    fixture_digest(&mut unknown_closed)?;
    let predecessor = codex_hepta_supervisor::UnknownRecoveryPredecessorV1::from_absent(&agent);
    let frontier = Sha256Digest::for_bytes(b"frontier");
    let source = serde_json::json!({"release_id":"v1","manifest_sha256":manifest,"agentd_program_sha256":program,
        "matrixd_program_sha256":null,"admission_frontier_sha256":frontier});
    let unknown_confirmation: SignRequest = serde_json::from_value(serde_json::json!({
        "operation":"confirm_unknown_publication","signer_id":"recovery","signer_epoch":7,
        "intent":unknown_closed,"source":source,"predecessor":predecessor,
        "observed_transaction_sha256":codex_hepta_supervisor::absent_release_transaction_digest(),
        "release_state_generation":2,"lifecycle_generation":5,"authority_epoch":48,
        "issued_at_unix_seconds":100,"expires_at_unix_seconds":400
    }))?;
    assert!(
        !run_cli(
            &root,
            &unknown_confirmation,
            &recovery_key,
            Some("ed25519_v1_qualification"),
            None
        )?
        .0
    );
    let (ok, output) = run_cli(
        &root,
        &unknown_confirmation,
        &recovery_key,
        Some("ml_dsa65_v2"),
        Some(&policy_path),
    )?;
    assert!(ok);
    let SignResponse::ProductionRecovery { decision } = serde_json::from_slice(&output)? else {
        return Err("wrong confirmation response".into());
    };
    verifier.verify_recovery(
        &decision,
        &agent,
        &grant.grant_sha256,
        &unknown_closed.intent_sha256,
        &codex_hepta_supervisor::absent_release_transaction_digest(),
        "v1",
        &manifest,
        &program,
        None,
        /*expected_lifecycle_generation*/ 5,
        /*expected_authority_epoch*/ 48,
        /*now_unix_seconds*/ 200,
    )?;
    assert_eq!(
        decision.outcome,
        ProductionRecoveryOutcome::ConfirmUnknownPublication
    );

    let mut terminal = unknown_intent;
    terminal.schema_version = 3;
    terminal.status = codex_hepta_supervisor::SignedIntentStatus::Committed;
    terminal.pq_authority = Some(codex_hepta_supervisor::SignedIntentPqAuthority {
        binding: grant.pq_authority.clone().unwrap(),
        policy_json: String::from_utf8(policy_bytes)?,
        grant: grant.clone(),
        h7_envelope: envelope,
        issued_at_unix_seconds: 100,
        expires_at_unix_seconds: 400,
    });
    fixture_digest(&mut terminal)?;
    let observed = serde_json::json!({"release_id":"v2","manifest_sha256":manifest,"agentd_program_sha256":program,
        "matrixd_program_sha256":null,"admission_frontier_sha256":frontier});
    let completion_observation = serde_json::json!({"schema_version":1,"predecessor":predecessor,
        "pending_publication_sha256":Sha256Digest::for_bytes(b"retained original pending"),
        "release_state_sha256":Sha256Digest::for_bytes(b"observed state"),"release_state_generation":2,
        "admission_frontier_sha256":frontier});
    let retry_observation = serde_json::json!({"schema_version":1,"predecessor":predecessor,
        "original_pending_sha256":Sha256Digest::for_bytes(b"retained original pending"),
        "replacement_pending_sha256":Sha256Digest::for_bytes(b"retained replacement pending"),
        "retained_state_sha256":Sha256Digest::for_bytes(b"both actual attempts"),
        "replacement_anchor_sha256":Sha256Digest::for_bytes(b"exact replacement anchor"),
        "release_state_sha256":Sha256Digest::for_bytes(b"observed state"),"release_state_generation":2,
        "admission_frontier_sha256":frontier});
    for (operation, observation, outcome) in [
        (
            "confirm_completion_publication",
            completion_observation,
            ProductionRecoveryOutcome::ConfirmCommittedPublication,
        ),
        (
            "retry_retained_publication",
            retry_observation,
            ProductionRecoveryOutcome::RetryRetainedPublication,
        ),
    ] {
        let request: SignRequest = serde_json::from_value(serde_json::json!({
            "operation":operation,"signer_id":"recovery","signer_epoch":7,"intent":terminal,
            "observed":observed,"observation":observation,"observed_transaction_sha256":transaction,
            "lifecycle_generation":5,"authority_epoch":48,"issued_at_unix_seconds":100,"expires_at_unix_seconds":400
        }))?;
        assert!(
            !run_cli(
                &root,
                &request,
                &grant_key,
                Some("ml_dsa65_v2"),
                Some(&policy_path)
            )?
            .0
        );
        assert!(
            !run_cli(
                &root,
                &request,
                &recovery_key,
                Some("ed25519_v1_qualification"),
                None
            )?
            .0
        );
        let (ok, output) = run_cli(
            &root,
            &request,
            &recovery_key,
            Some("ml_dsa65_v2"),
            Some(&policy_path),
        )?;
        assert!(ok);
        let SignResponse::ProductionRecovery { decision } = serde_json::from_slice(&output)? else {
            return Err("wrong publication response".into());
        };
        verifier.verify_recovery(
            &decision,
            &agent,
            &grant.grant_sha256,
            &terminal.intent_sha256,
            &transaction,
            "v2",
            &manifest,
            &program,
            None,
            /*expected_lifecycle_generation*/ 5,
            /*expected_authority_epoch*/ 48,
            /*now_unix_seconds*/ 200,
        )?;
        assert_eq!(decision.outcome, outcome);
    }
    Ok(())
}

#[test]
fn cli_requires_explicit_profile_and_refuses_unsafe_key_files() -> TestResult {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let key = root.join("key");
    private_file(&key, /*seed*/ 112)?;
    let request = envelope_request()?;
    assert!(
        !run_cli(
            &root, &request, &key, /*profile*/ None, /*policy*/ None
        )?
        .0
    );
    assert!(
        !run_cli(
            &root,
            &request,
            &key,
            Some("ml_dsa65_v2"),
            /*policy*/ None
        )?
        .0
    );
    let (ok, output) = run_cli(
        &root,
        &request,
        &key,
        Some("ed25519_v1_qualification"),
        /*policy*/ None,
    )?;
    assert!(ok);
    let SignResponse::H7Envelope { envelope } = serde_json::from_slice(&output)? else {
        return Err("wrong legacy response".into());
    };
    assert!(envelope.signer_public_key_id.is_none());
    assert_eq!(envelope.schema_version, 1);
    let link = root.join("link");
    std::os::unix::fs::symlink(&key, &link)?;
    assert!(
        !run_cli(
            &root,
            &request,
            &link,
            Some("ed25519_v1_qualification"),
            /*policy*/ None
        )?
        .0
    );
    std::fs::set_permissions(&key, std::fs::Permissions::from_mode(0o644))?;
    assert!(
        !run_cli(
            &root,
            &request,
            &key,
            Some("ed25519_v1_qualification"),
            /*policy*/ None
        )?
        .0
    );
    let fifo = root.join("fifo");
    use std::os::unix::ffi::OsStrExt;
    let cpath = std::ffi::CString::new(fifo.as_os_str().as_bytes())?;
    // SAFETY: cpath is NUL-terminated and valid for the duration of mkfifo.
    assert_eq!(unsafe { libc::mkfifo(cpath.as_ptr(), 0o600) }, 0);
    assert!(
        !run_cli(
            &root,
            &request,
            &fifo,
            Some("ed25519_v1_qualification"),
            /*policy*/ None
        )?
        .0
    );
    Ok(())
}
