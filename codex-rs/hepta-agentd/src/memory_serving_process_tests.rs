//! Real subprocess and authority-boundary tests with an explicitly fake reader.
//! The separate ignored test uses a pinned pretrained checkpoint in hosted CI.
use super::*;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::collections::BTreeSet;

const READER: &str = r#"
import hashlib, json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes()
j = json.loads(raw)
payload = (Path(sys.argv[2]) / 'adapter.safetensors').read_bytes()
assert hashlib.sha256(payload).hexdigest() == j['payload_digest']
answer = 'fixture prediction, not a pretrained answer'
out = dict(schema='hepta.memory-serving.observation.v1', job_digest=hashlib.sha256(raw).hexdigest(),
    payload_digest=j['payload_digest'], selection_digest=j['selection_digest'],
    qualification_digest=j['qualification_digest'], scope_digest=j['scope_digest'],
    base_digest=j['base_digest'], base_unchanged=True, answer=answer,
    answer_digest=hashlib.sha256(answer.encode()).hexdigest(), input_tokens=12, output_tokens=8,
    prompt_digest=hashlib.sha256(b'fixture prompt').hexdigest())
(Path(sys.argv[2]) / 'observation.json').write_text(json.dumps(out))
"#;

fn digest(name: &str) -> String {
    Digest32::of_bytes(name.as_bytes()).to_string()
}
fn job(process: &MemoryServingProcessV1) -> MemoryServingJobV1 {
    MemoryServingJobV1 {
        schema: "hepta.memory-serving.job.v1",
        request_id: "request.1".into(),
        subject_id: "agent.1".into(),
        destination_id: "node.1".into(),
        route_generation: 7,
        base_digest: digest("base"),
        encoder_digest: digest("encoder"),
        payload_digest: digest("adapter"),
        scope_digest: digest("scope"),
        selection_digest: digest("selected"),
        qualification_digest: digest("qualified"),
        source_support_digest: digest("source"),
        training_job_digest: digest("training-job"),
        trainer_digest: digest("trainer"),
        runtime_digest: process.runtime_digest().to_string(),
        interpreter_digest: process.interpreter_digest().to_string(),
        question: "What was learned?".into(),
        question_time: "2026-10-09T00:00:00Z".into(),
        deadline_unix_millis: now_ms().expect("clock") + 30_000,
    }
}
struct Fixture {
    root: tempfile::TempDir,
    process: MemoryServingProcessV1,
    authority: FinalUseAuthority,
    signed: SignedFinalUseGrant,
    job: MemoryServingJobV1,
}
fn fixture(script: &str) -> Fixture {
    // PATH discovery is confined to test setup, never the product consumer.
    let python = Command::new("python3")
        .args([
            "-c",
            "import os,sys;print(os.path.realpath(sys.executable))",
        ])
        .output()
        .expect("Python test prerequisite");
    assert!(python.status.success());
    let python = PathBuf::from(
        String::from_utf8(python.stdout)
            .expect("Python path")
            .trim(),
    );
    let root = tempfile::tempdir().expect("fixture directory");
    for name in [
        "native.py",
        "pretrained.py",
        "requirements.txt",
        "sessions.py",
        "tensor_contract.py",
    ] {
        fs::write(root.path().join(name), b"# fixture only\n").expect("fixture source");
    }
    let program = root.path().join("serving_worker.py");
    fs::write(&program, script).expect("fixture reader");
    let scratch = root.path().join("scratch");
    fs::create_dir(&scratch).expect("scratch root");
    let process = MemoryServingProcessV1::new(MemoryServingProcessConfigV1 {
        interpreter_digest: Digest32::of_bytes(&fs::read(&python).expect("interpreter")),
        python_executable: python,
        code_digest: MemoryServingProcessV1::code_digest(&program).expect("code identity"),
        program,
        model_directory: root.path().to_owned(),
        scratch_root: scratch,
    })
    .expect("admitted fixture installation");
    let job = job(&process);
    let key = SigningKey::from_bytes(&[93; 32]);
    let authority_dir = root.path().join("authority");
    fs::create_dir(&authority_dir).expect("authority directory");
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&authority_dir, fs::Permissions::from_mode(0o700))
        .expect("authority privacy");
    let authority = FinalUseAuthority::open_state_dir(
        &authority_dir,
        "fixture-issuer".into(),
        key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("fixture authority");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "fixture-issuer".into(),
        authority_epoch: 1,
        grant_id: "use.1".into(),
        nonce: [12; 32],
        binding: job.binding().expect("binding"),
        not_before_unix_ms: now_ms().expect("clock") - 1,
        expires_at_unix_ms: job.deadline_unix_millis,
    };
    let signature = key
        .sign(&grant.signing_bytes().expect("grant bytes"))
        .to_bytes()
        .to_vec();
    Fixture {
        root,
        process,
        authority,
        signed: SignedFinalUseGrant { grant, signature },
        job,
    }
}

#[test]
fn actual_subprocess_requires_single_use_and_matching_observation() {
    let f = fixture(READER);
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    let result = f
        .process
        .execute(f.job, b"adapter".to_vec(), token, CancellationToken::new())
        .expect("bounded execution");
    assert_eq!(
        result.answer(),
        "fixture prediction, not a pretrained answer"
    );
    assert_eq!(result.usage(), (12, 8));
    assert!(
        f.authority
            .claim(&f.signed, &f.signed.grant.binding)
            .is_err()
    );
    assert_eq!(
        fs::read_dir(f.root.path().join("scratch"))
            .expect("scratch")
            .count(),
        0
    );
}

#[test]
fn revocation_between_claim_and_spawn_prevents_effect() {
    let f = fixture(READER);
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    f.authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([f.signed.grant.grant_id.clone()]),
        })
        .expect("current revoke");
    assert!(
        f.process
            .execute(f.job, b"adapter".to_vec(), token, CancellationToken::new())
            .is_err()
    );
    assert_eq!(
        fs::read_dir(f.root.path().join("scratch"))
            .expect("scratch")
            .count(),
        0
    );
}

#[test]
fn wrong_node_generation_or_selection_cannot_reuse_grant() {
    for field in ["node", "generation", "selection", "question"] {
        let mut f = fixture(READER);
        let token = f
            .authority
            .claim(&f.signed, &f.signed.grant.binding)
            .expect("fixture token");
        match field {
            "node" => f.job.destination_id = "node.2".into(),
            "generation" => f.job.route_generation += 1,
            "selection" => f.job.selection_digest = digest("other-selection"),
            "question" => f.job.question = "A different request".into(),
            _ => unreachable!(),
        }
        assert!(
            f.process
                .execute(f.job, b"adapter".to_vec(), token, CancellationToken::new())
                .is_err()
        );
    }
}

#[test]
fn cancellation_reaps_child_and_missing_completion_cannot_be_success() {
    let f = fixture("import time\ntime.sleep(30)\n");
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    let cancel = CancellationToken::new();
    let other = cancel.clone();
    let killer = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(50));
        other.cancel();
    });
    assert!(
        f.process
            .execute(f.job, b"adapter".to_vec(), token, cancel)
            .is_err()
    );
    killer.join().expect("canceller");
    assert_eq!(
        fs::read_dir(f.root.path().join("scratch"))
            .expect("scratch")
            .count(),
        0
    );
    let f = fixture("pass\n");
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    assert!(
        f.process
            .execute(f.job, b"adapter".to_vec(), token, CancellationToken::new())
            .is_err()
    );
}

#[test]
fn changed_dependency_or_payload_rejects_before_execution() {
    let f = fixture(READER);
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    fs::write(f.root.path().join("tensor_contract.py"), b"# changed\n").expect("fixture drift");
    assert!(
        f.process
            .execute(f.job, b"adapter".to_vec(), token, CancellationToken::new())
            .is_err()
    );
    let f = fixture(READER);
    let token = f
        .authority
        .claim(&f.signed, &f.signed.grant.binding)
        .expect("fixture token");
    assert!(
        f.process
            .execute(
                f.job,
                b"different adapter".to_vec(),
                token,
                CancellationToken::new()
            )
            .is_err()
    );
}

#[cfg(target_os = "linux")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn runtime_retirement_waits_for_the_actual_child_and_rejects_old_generation() {
    use codex_hepta_types::Generation;
    use crate::AgentdError;
    use crate::RuntimeTasks;

    let f = fixture("import os,sys,time\nfrom pathlib import Path\n(Path(sys.argv[2])/'child-started').write_text(str(os.getpid()))\ntime.sleep(30)\n");
    let token = f.authority.claim(&f.signed, &f.signed.grant.binding).expect("fixture token");
    let cancellation = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(cancellation, Duration::from_secs(2)).expect("runtime host");
    let process = f.process.clone();
    let generation = Generation::new(1).expect("generation");
    let job = f.job;
    tasks.spawn_optional_service_generation(
        "memory.serving.fixture", generation, None,
        move |stop| async move {
            let child_stop = stop.child_token();
            let value = tokio::task::spawn_blocking(move || process.execute(job, b"adapter".to_vec(), token, child_stop))
                .await.map_err(|error| AgentdError::Protocol(error.to_string()))?;
            if stop.is_cancelled() { Ok(()) }
            else { value.map(|_| ()).map_err(AgentdError::Protocol) }
        }, || Ok(()), || Ok(()),
    ).expect("admitted test service");
    let started = Instant::now();
    let pid = loop {
        let marker = fs::read_dir(f.root.path().join("scratch")).expect("scratch")
            .filter_map(Result::ok).map(|entry| entry.path().join("child-started"))
            .find(|path| path.is_file());
        if let Some(marker) = marker { break fs::read_to_string(marker).expect("child PID"); }
        assert!(started.elapsed() < Duration::from_secs(5), "child did not start");
        tokio::time::sleep(Duration::from_millis(10)).await;
    };
    assert!(Path::new("/proc").join(pid.trim()).exists());
    tasks.retire_optional_generation("memory.serving.fixture", generation).await.expect("ack after reap");
    assert!(!Path::new("/proc").join(pid.trim()).exists(), "retirement left a live child");
    assert_eq!(fs::read_dir(f.root.path().join("scratch")).expect("scratch").count(), 0);
    assert_eq!(tasks.active_count(), 0);
    assert!(tasks.spawn_optional_service_generation(
        "memory.serving.fixture", generation, Some(generation),
        |_| async { Ok(()) }, || Ok(()), || Ok(()),
    ).is_err());
}
