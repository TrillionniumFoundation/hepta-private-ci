use super::*;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[cfg(unix)]
struct Fixture {
    _temp: tempfile::TempDir,
    owner: RuntimeCodexOwnerV1,
    executor: ProcessRuntimeCodexExecutorV1,
    counter: PathBuf,
    resume_counter: PathBuf,
}

#[cfg(unix)]
fn terminal_json() -> &'static str {
    r#"{"thread_id":"thread-1","turn_id":"turn-1","model":"fake-model","model_provider":"fixture","status":"completed","boundary_status":"succeeded","output":"ok","observed_output_tokens":1,"terminal_observed":true,"stop_reason":null,"owner_authority":{"state":"observed_ready"},"codex_terminal_correlation_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#
}

#[cfg(unix)]
fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "'\"'\"'"))
}

#[cfg(unix)]
fn fixture(script_logic: &str) -> Fixture {
    let temp = tempfile::tempdir().expect("temp");
    let root = temp.path().canonicalize().expect("canonical temp");
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
        .expect("temp permissions");
    let home = root.join("home");
    std::fs::create_dir(&home).expect("home");
    std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))
        .expect("home permissions");
    let counter = root.join("physical-count");
    let resume_counter = root.join("resume-count");
    let worker = root.join("fake-worker.sh");
    let script = format!(
        "#!/bin/sh\nset -eu\nCOUNTER={}\nRESUME={}\n{}\n",
        shell_quote(&counter),
        shell_quote(&resume_counter),
        script_logic.replace("__TERMINAL_JSON__", terminal_json()),
    );
    std::fs::write(&worker, script.as_bytes()).expect("worker");
    std::fs::set_permissions(&worker, std::fs::Permissions::from_mode(0o700))
        .expect("worker permissions");
    let authority = root.join("final-use-authority.json");
    std::fs::write(&authority, b"{\"fixture\":true}\n").expect("authority");
    std::fs::set_permissions(&authority, std::fs::Permissions::from_mode(0o600))
        .expect("authority permissions");
    let worker_digest = Digest32::of_bytes(script.as_bytes());
    let authority_digest = Digest32::of_bytes(b"{\"fixture\":true}\n");
    let journal_root = home.join("runtime-codex");
    let executor = ProcessRuntimeCodexExecutorV1::new(
        worker,
        worker_digest,
        authority,
        authority_digest,
        journal_root,
        4,
        Duration::from_secs(1),
    )
    .expect("executor");
    let owner = RuntimeCodexOwnerV1::new(
        AgentId::parse("00000000-0000-4000-8000-000000000901").expect("agent"),
        1,
        home.join("agentd.sock"),
        home,
    )
    .expect("owner");
    Fixture {
        _temp: temp,
        owner,
        executor,
        counter,
        resume_counter,
    }
}

#[cfg(unix)]
fn input(prompt: &str) -> RuntimeCodexExecutionInputV1 {
    RuntimeCodexExecutionInputV1::new(
        StableId::new("run.fixture").expect("run"),
        2,
        Digest32::of_bytes(b"context"),
        Digest32::of_bytes(b"envelope"),
        prompt.to_string(),
        Some("context query".to_string()),
        "fake-model".to_string(),
        // The deadline is part of semantic identity. A retry must carry the
        // original immutable deadline rather than manufacture a new one.
        u64::MAX,
    )
    .expect("input")
}

#[cfg(unix)]
#[tokio::test]
async fn exact_duplicate_returns_the_frozen_receipt_without_a_second_process() {
    let fixture = fixture(
        r#"
MODE=fresh
for ARG in "$@"; do
  if [ "$ARG" = "--resume" ]; then MODE=resume; fi
done
if [ "$MODE" = "fresh" ]; then
  cat >/dev/null
  printf x >> "$COUNTER"
else
  printf r >> "$RESUME"
fi
printf '%s\n' '__TERMINAL_JSON__'
"#,
    );
    let first = fixture
        .executor
        .execute(
            fixture.owner.clone(),
            input("hello"),
            CancellationToken::new(),
        )
        .await
        .expect("first execution");
    assert!(first.succeeded());
    assert!(!first.reconciled);
    assert!(!first.idempotent);

    let duplicate = fixture
        .executor
        .execute(
            fixture.owner.clone(),
            input("hello"),
            CancellationToken::new(),
        )
        .await
        .expect("duplicate receipt");
    assert!(duplicate.succeeded());
    assert!(duplicate.idempotent);
    assert_eq!(std::fs::read(&fixture.counter).expect("counter"), b"x");
    assert!(!fixture.resume_counter.exists());
}

#[cfg(unix)]
#[tokio::test]
async fn unknown_first_process_is_reconcile_only_and_never_reissued() {
    let fixture = fixture(
        r#"
MODE=fresh
for ARG in "$@"; do
  if [ "$ARG" = "--resume" ]; then MODE=resume; fi
done
if [ "$MODE" = "fresh" ]; then
  cat >/dev/null
  printf x >> "$COUNTER"
  exit 17
fi
printf r >> "$RESUME"
printf '%s\n' '__TERMINAL_JSON__'
"#,
    );
    let first = fixture
        .executor
        .execute(
            fixture.owner.clone(),
            input("hello"),
            CancellationToken::new(),
        )
        .await
        .expect_err("first outcome must be unknown");
    assert!(first.to_string().contains("no valid bounded receipt"));

    let recovered = fixture
        .executor
        .execute(
            fixture.owner.clone(),
            input("hello"),
            CancellationToken::new(),
        )
        .await
        .expect("resume receipt");
    assert!(recovered.succeeded());
    assert!(recovered.reconciled);
    assert_eq!(std::fs::read(&fixture.counter).expect("counter"), b"x");
    assert_eq!(
        std::fs::read(&fixture.resume_counter).expect("resume counter"),
        b"r"
    );
}

#[cfg(unix)]
#[tokio::test]
async fn duplicate_run_identity_with_prompt_drift_is_rejected() {
    let fixture = fixture(
        r#"
cat >/dev/null
printf x >> "$COUNTER"
printf '%s\n' '__TERMINAL_JSON__'
"#,
    );
    fixture
        .executor
        .execute(
            fixture.owner.clone(),
            input("first"),
            CancellationToken::new(),
        )
        .await
        .expect("first execution");
    let error = fixture
        .executor
        .execute(
            fixture.owner,
            input("semantic drift"),
            CancellationToken::new(),
        )
        .await
        .expect_err("drift must conflict");
    assert!(error.to_string().contains("semantic drift"), "{error}");
    assert_eq!(std::fs::read(&fixture.counter).expect("counter"), b"x");
}

#[test]
fn execution_input_redacts_prompt_from_debug_output() {
    let input = RuntimeCodexExecutionInputV1::new(
        StableId::new("run.redacted").expect("run"),
        1,
        Digest32::of_bytes(b"context"),
        Digest32::of_bytes(b"envelope"),
        "super-secret-prompt".to_string(),
        None,
        "model".to_string(),
        u64::MAX,
    )
    .expect("input");
    let debug = format!("{input:?}");
    assert!(!debug.contains("super-secret-prompt"));
    assert!(debug.contains("prompt_bytes"));
}