#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_agentd::ProcessRuntimeCodexExecutorV1;
use codex_hepta_agentd::RuntimeCodexExecutionInputV1;
use codex_hepta_agentd::RuntimeCodexExecutorV1;
use codex_hepta_agentd::RuntimeCodexOwnerV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio_util::sync::CancellationToken;

const AUTHORITY_BYTES: &[u8] = b"{\"fixture\":true}\n";

fn terminal_json() -> &'static str {
    r#"{"thread_id":"thread-1","turn_id":"turn-1","model":"fake-model","model_provider":"fixture","status":"completed","boundary_status":"succeeded","output":"ok","observed_output_tokens":1,"terminal_observed":true,"stop_reason":null,"owner_authority":{"state":"observed_ready"},"codex_terminal_correlation_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#
}

fn shell_quote(path: &Path) -> String {
    format!("'{}'", path.to_string_lossy().replace('\'', "'\"'\"'"))
}

struct ProcessFixture {
    _temp: tempfile::TempDir,
    root: PathBuf,
    home: PathBuf,
    worker: PathBuf,
    authority: PathBuf,
    journal: PathBuf,
    counter: PathBuf,
    resume_counter: PathBuf,
    ready: PathBuf,
    worker_digest: Digest32,
    authority_digest: Digest32,
}

impl ProcessFixture {
    fn new(script_logic: &str) -> Self {
        let temp = tempfile::tempdir().expect("tempdir");
        let root = temp.path().canonicalize().expect("canonical tempdir");
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .expect("private tempdir");
        let home = root.join("home");
        std::fs::create_dir(&home).expect("home");
        std::fs::set_permissions(&home, std::fs::Permissions::from_mode(0o700))
            .expect("private home");

        let counter = root.join("physical-count");
        let resume_counter = root.join("resume-count");
        let ready = root.join("fresh-ready");
        let worker = root.join("fake-infer-worker.sh");
        let script = format!(
            "#!/bin/sh\nset -eu\nCOUNTER={}\nRESUME={}\nREADY={}\n{}\n",
            shell_quote(&counter),
            shell_quote(&resume_counter),
            shell_quote(&ready),
            script_logic.replace("__TERMINAL_JSON__", terminal_json()),
        );
        std::fs::write(&worker, script.as_bytes()).expect("worker");
        std::fs::set_permissions(&worker, std::fs::Permissions::from_mode(0o700))
            .expect("worker mode");

        let authority = root.join("final-use-authority.json");
        std::fs::write(&authority, AUTHORITY_BYTES).expect("authority");
        std::fs::set_permissions(&authority, std::fs::Permissions::from_mode(0o600))
            .expect("authority mode");

        Self {
            _temp: temp,
            root: root.clone(),
            home: home.clone(),
            worker,
            authority,
            journal: home.join("runtime-codex"),
            counter,
            resume_counter,
            ready,
            worker_digest: Digest32::of_bytes(script.as_bytes()),
            authority_digest: Digest32::of_bytes(AUTHORITY_BYTES),
        }
    }

    fn executor(&self) -> ProcessRuntimeCodexExecutorV1 {
        ProcessRuntimeCodexExecutorV1::new(
            self.worker.clone(),
            self.worker_digest,
            self.authority.clone(),
            self.authority_digest,
            self.journal.clone(),
            4,
            Duration::from_millis(200),
        )
        .expect("executor")
    }

    fn owner(&self, generation: u64) -> RuntimeCodexOwnerV1 {
        RuntimeCodexOwnerV1::new(
            AgentId::parse("00000000-0000-4000-8000-000000000941").expect("agent"),
            generation,
            self.home.join("agentd.sock"),
            self.home.clone(),
        )
        .expect("owner")
    }

    fn input(&self) -> RuntimeCodexExecutionInputV1 {
        RuntimeCodexExecutionInputV1::new(
            StableId::new("run.process-crash-matrix").expect("run"),
            2,
            Digest32::of_bytes(b"context"),
            Digest32::of_bytes(b"envelope"),
            "perform exactly one physical effect".to_string(),
            Some("bounded context".to_string()),
            "fake-model".to_string(),
            u64::MAX,
        )
        .expect("input")
    }

    fn physical_count(&self) -> usize {
        std::fs::read(&self.counter).map_or(0, |bytes| bytes.len())
    }

    fn resume_count(&self) -> usize {
        std::fs::read(&self.resume_counter).map_or(0, |bytes| bytes.len())
    }
}

fn unknown_then_resumable_fixture() -> ProcessFixture {
    ProcessFixture::new(
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
    )
}

#[tokio::test]
async fn process_restart_recovers_unknown_effect_without_second_fresh_dispatch() {
    let fixture = unknown_then_resumable_fixture();
    let first = fixture
        .executor()
        .execute(
            fixture.owner(1),
            fixture.input(),
            CancellationToken::new(),
        )
        .await
        .expect_err("fresh process must end without a terminal receipt");
    assert!(first.to_string().contains("receipt"), "{first}");
    assert_eq!(fixture.physical_count(), 1);
    assert_eq!(fixture.resume_count(), 0);

    // A new executor instance models a daemon/process restart. Recovery must use
    // the worker's resume path because a dispatch fence already exists.
    let restarted = fixture.executor();
    let report = restarted
        .reconcile_pending(fixture.owner(1), CancellationToken::new())
        .await
        .expect("restart reconciliation");
    assert_eq!(report.reconciled_terminal, 1);
    assert_eq!(report.fenced_unresolved, 0);

    let frozen = restarted
        .execute(
            fixture.owner(1),
            fixture.input(),
            CancellationToken::new(),
        )
        .await
        .expect("frozen terminal receipt");
    assert!(frozen.idempotent);
    assert!(frozen.reconciled);
    assert_eq!(fixture.physical_count(), 1, "fresh effect was repeated");
    assert_eq!(fixture.resume_count(), 1, "recovery did not use resume");
}

#[tokio::test]
async fn cancellation_after_dispatch_is_reconciled_without_blind_redispatch() {
    let fixture = ProcessFixture::new(
        r#"
MODE=fresh
for ARG in "$@"; do
  if [ "$ARG" = "--resume" ]; then MODE=resume; fi
done
if [ "$MODE" = "fresh" ]; then
  cat >/dev/null
  printf x >> "$COUNTER"
  : > "$READY"
  while true; do sleep 1; done
fi
printf r >> "$RESUME"
printf '%s\n' '__TERMINAL_JSON__'
"#,
    );
    let executor = Arc::new(fixture.executor());
    let cancellation = CancellationToken::new();
    let task = {
        let executor = Arc::clone(&executor);
        let owner = fixture.owner(1);
        let input = fixture.input();
        let cancellation = cancellation.clone();
        tokio::spawn(async move { executor.execute(owner, input, cancellation).await })
    };

    for _ in 0..250 {
        if fixture.ready.exists() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(fixture.ready.exists(), "worker never crossed dispatch boundary");
    cancellation.cancel();
    let outcome = task.await.expect("execution task");
    assert!(outcome.is_err(), "cancelled unknown effect became success");
    assert_eq!(fixture.physical_count(), 1);

    drop(executor);
    let restarted = fixture.executor();
    let report = restarted
        .reconcile_pending(fixture.owner(1), CancellationToken::new())
        .await
        .expect("cancelled operation reconciliation");
    assert_eq!(report.reconciled_terminal, 1);
    assert_eq!(fixture.physical_count(), 1, "cancel recovery re-ran effect");
    assert_eq!(fixture.resume_count(), 1);
}

#[tokio::test]
async fn authority_rotation_or_tamper_fails_closed_before_process_creation() {
    let fixture = ProcessFixture::new(
        r#"
cat >/dev/null
printf x >> "$COUNTER"
printf '%s\n' '__TERMINAL_JSON__'
"#,
    );
    let executor = fixture.executor();
    std::fs::write(&fixture.authority, b"{\"fixture\":false}\n").expect("rotate authority");
    std::fs::set_permissions(&fixture.authority, std::fs::Permissions::from_mode(0o600))
        .expect("authority mode");

    let error = executor
        .execute(
            fixture.owner(1),
            fixture.input(),
            CancellationToken::new(),
        )
        .await
        .expect_err("changed authority must fail closed");
    let message = error.to_string();
    assert!(
        message.contains("digest") || message.contains("protected") || message.contains("authority"),
        "{message}"
    );
    assert_eq!(fixture.physical_count(), 0);
    assert_eq!(fixture.resume_count(), 0);
}

#[tokio::test]
async fn generation_rollover_cannot_adopt_or_resume_old_generation_operation() {
    let fixture = unknown_then_resumable_fixture();
    fixture
        .executor()
        .execute(
            fixture.owner(1),
            fixture.input(),
            CancellationToken::new(),
        )
        .await
        .expect_err("generation-one effect remains unknown");
    assert_eq!(fixture.physical_count(), 1);

    let restarted = fixture.executor();
    let rollover_error = restarted
        .reconcile_pending(fixture.owner(2), CancellationToken::new())
        .await
        .expect_err("new generation must not adopt old operation");
    let message = rollover_error.to_string();
    assert!(
        message.contains("generation") || message.contains("owner"),
        "{message}"
    );
    assert_eq!(fixture.physical_count(), 1);
    assert_eq!(fixture.resume_count(), 0);

    let original = restarted
        .reconcile_pending(fixture.owner(1), CancellationToken::new())
        .await
        .expect("original generation remains recoverable");
    assert_eq!(original.reconciled_terminal, 1);
    assert_eq!(fixture.physical_count(), 1);
    assert_eq!(fixture.resume_count(), 1);
}

#[test]
fn fixture_paths_are_inside_one_private_root() {
    let fixture = unknown_then_resumable_fixture();
    assert!(fixture.home.starts_with(&fixture.root));
    assert!(fixture.worker.starts_with(&fixture.root));
    assert!(fixture.authority.starts_with(&fixture.root));
    assert!(fixture.journal.starts_with(&fixture.root));
}
