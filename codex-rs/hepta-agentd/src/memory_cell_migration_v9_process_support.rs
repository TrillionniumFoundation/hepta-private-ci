use std::io::BufRead;
use std::io::Write;
use std::net::TcpListener;
use std::path::Path;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::ChildStdout;
use tokio::process::Command;

use crate::MemoryCellMigrationManifestV9;
use crate::MemoryCellMigrationReceiverV9;
use crate::MemoryCellMigrationStoreV9;
use super::super::process_release_test_support::ReleaseCheckpoint;

pub(super) const DESTINATION: &str = "memory:receiver-v9";
const PREFIX: &str = "HEPTA_MEMORY_V9_MIGRATION:";
const SPEC: &str = "HEPTA_MEMORY_V9_MIGRATION_CHILD_SPEC";
const LIMIT: usize = 262_144;
const DEADLINE: Duration = Duration::from_secs(30);

#[derive(Deserialize, Serialize)]
#[serde(tag = "role", deny_unknown_fields)]
pub(super) enum Spec {
    Receiver { root: PathBuf, manifest: MemoryCellMigrationManifestV9, crash: Option<String> },
    Target { active: PathBuf, image_store: PathBuf, manifest: MemoryCellMigrationManifestV9,
        payload: Sha256Digest, checkpoint: ReleaseCheckpoint, unavailable_source: Vec<PathBuf> },
}

pub(super) fn source_key() -> SigningKey { SigningKey::from_bytes(&[73; 32]) }
pub(super) fn receiver_key() -> SigningKey { SigningKey::from_bytes(&[79; 32]) }

pub(super) struct Process {
    child: Child,
    input: Option<ChildStdin>,
    output: BufReader<ChildStdout>,
    pub ready: Value,
    started: Instant,
    pub spec_bytes: usize,
    pub handshake_bytes: u64,
}

impl Process {
    pub async fn spawn(directory: &Path, name: &str, spec: Spec) -> Self {
        let path = directory.join(format!("{name}.json"));
        let raw = serde_json::to_vec(&spec).expect("child spec");
        assert!(raw.len() < LIMIT);
        let mut file = std::fs::File::create_new(&path).expect("new child spec");
        file.write_all(&raw).expect("spec"); file.sync_all().expect("spec sync");
        let helper = match &spec {
            Spec::Receiver { .. } => "memory_cell_v9_migration_receiver_child",
            Spec::Target { .. } => "memory_cell_v9_migration_target_child",
        };
        let name = format!("memory_cell_network::migration_v9_process_tests::{helper}");
        let started = Instant::now();
        let mut child = Command::new(std::env::current_exe().expect("test binary"))
            .args(["--ignored", "--exact", &name, "--nocapture", "--test-threads=1"])
            .env(SPEC, &path).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit())
            .kill_on_drop(true).spawn().expect("real migration process");
        let input = child.stdin.take().expect("stdin");
        let mut output = BufReader::new(child.stdout.take().expect("stdout"));
        let (ready, handshake_bytes) = read_frame(&mut output).await;
        assert_eq!(ready["pid"].as_u64(), child.id().map(u64::from));
        assert_ne!(ready["pid"].as_u64(), Some(u64::from(std::process::id())));
        Self { child, input: Some(input), output, ready, started, spec_bytes: raw.len(), handshake_bytes }
    }

    pub async fn finish(mut self, crashed: bool) -> Value {
        let mut sent = 0;
        if !crashed {
            self.input.as_mut().expect("stdin").write_all(b"stop\n").await.expect("stop command");
            sent = 5;
        }
        self.input.take();
        let (status, trailer) = tokio::time::timeout(DEADLINE, async {
            let mut trailer = Vec::new();
            let mut output = self.output.take(LIMIT as u64);
            let (read, status) = tokio::join!(output.read_to_end(&mut trailer), self.child.wait());
            read.expect("complete bounded process evidence");
            (status.expect("reap child"), trailer)
        }).await.expect("child exit deadline");
        assert!(trailer.len() < LIMIT);
        assert_eq!(status.code(), Some(if crashed { 73 } else { 0 }));
        json!({"ready":self.ready,"exit_code":status.code(),"lifecycle_ns":self.started.elapsed().as_nanos().to_string(),
            "spec_bytes":self.spec_bytes,"harness_tx_bytes":sent,"harness_rx_bytes":self.handshake_bytes + trailer.len() as u64,
            "stdout_tail":String::from_utf8(trailer).expect("UTF-8 process evidence")})
    }
}

async fn read_frame(output: &mut BufReader<ChildStdout>) -> (Value, u64) {
    tokio::time::timeout(DEADLINE, async {
        let mut received = 0;
        loop {
            let mut line = Vec::new();
            let count = output.read_until(b'\n', &mut line).await.expect("child readiness");
            received += count as u64;
            assert!(count != 0 && received < LIMIT as u64, "child readiness size/EOF");
            let text = std::str::from_utf8(&line).expect("UTF-8");
            if let Some(offset) = text.find(PREFIX) {
                return (serde_json::from_str(text[offset + PREFIX.len()..].trim()).expect("ready JSON"), received);
            }
        }
    }).await.expect("child readiness deadline")
}

pub(super) fn emit(value: Value) {
    let mut output = std::io::stdout().lock();
    writeln!(output, "{PREFIX}{value}").expect("child evidence"); output.flush().expect("flush");
}

pub(super) fn spec() -> Spec {
    let path = PathBuf::from(std::env::var_os(SPEC).expect("parent-only child helper"));
    assert!(path.is_absolute());
    let raw = std::fs::read(path).expect("spec bytes"); assert!(raw.len() < LIMIT);
    serde_json::from_slice(&raw).expect("typed spec")
}

pub(super) fn receiver_child() {
    let Spec::Receiver { root, manifest, crash } = spec() else { panic!("receiver spec") };
    let store = MemoryCellMigrationStoreV9::open(root, manifest).expect("receiver durable recovery");
    let receiver = MemoryCellMigrationReceiverV9::new(store, DESTINATION.into(), source_key().verifying_key(), receiver_key());
    let listener = TcpListener::bind("127.0.0.1:0").expect("real loopback TCP listener");
    listener.set_nonblocking(true).expect("bounded accept loop");
    let stopped = Arc::new(AtomicBool::new(false));
    let stop = Arc::clone(&stopped);
    let input = std::thread::spawn(move || {
        let mut line = String::new();
        std::io::stdin().lock().read_line(&mut line).expect("stop input");
        assert_eq!(line, "stop\n"); stop.store(true, Ordering::SeqCst);
    });
    emit(json!({"pid":std::process::id(),"endpoint":listener.local_addr().expect("bound endpoint")}));
    while !stopped.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((stream, _)) => {
                let result = receiver.serve_observed(stream, &mut |stage| {
                    if crash.as_deref() == Some(stage) {
                        emit(json!({"crash_checkpoint":stage,"traffic":receiver.traffic().expect("receiver traffic")}));
                        std::process::exit(73);
                    }
                });
                if let Err(error) = result { emit(json!({"connection_error":error.chars().take(512).collect::<String>()})); }
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(2)),
            Err(error) => panic!("accept failed: {error}"),
        }
    }
    input.join().expect("stop joined");
    emit(json!({"stopped":true,"traffic":receiver.traffic().expect("receiver traffic")}));
}
