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

fn role(name: &str, seed: u8) -> ProductionAuthorityRoleV1 {
    let seed = zeroize::Zeroizing::new([seed; 32]);
    let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
    ProductionAuthorityRoleV1 {
        signer_id: name.to_string(),
        signer_epoch: 7,
        public_key_id: ml_dsa_65_key_id_from_spki(&spki).unwrap(),
        public_spki_base64: STANDARD.encode(spki),
    }
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

fn envelope_request() -> SignRequest {
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
    )
    .unwrap();
    runtime.append_trajectory_event(event).unwrap();
    runtime.evaluate_trajectory("pq-cli").unwrap();
    SignRequest::H7Envelope {
        signer_id: "artifact".to_string(),
        signer_epoch: 7,
        artifact: runtime
            .propose_artifact("pq-cli-artifact", "pq-cli", /*generation*/ 1)
            .unwrap(),
        ope: None,
        transition: H7SignedArtifactTransition::Reload,
        expected_runtime_generation: 0,
        predecessor_artifact_sha256: None,
        issued_at_unix_seconds: 100,
        expires_at_unix_seconds: 500,
    }
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

