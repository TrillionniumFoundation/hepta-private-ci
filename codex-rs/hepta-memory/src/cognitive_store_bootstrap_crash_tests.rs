use super::*;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::process::Command;
use std::process::Output;
use std::process::Stdio;
use std::time::Instant;

const CHILD_ROOT: &str = "HEPTA_COGNITIVE_BOOTSTRAP_CRASH_ROOT";
const CHILD_PHASE: &str = "HEPTA_COGNITIVE_BOOTSTRAP_CRASH_PHASE";
const EVIDENCE_ROOT: &str = "HEPTA_MEMORY_CRASH_EVIDENCE_ROOT";
const CRASH_EXIT: i32 = 73;

#[derive(Clone, Copy)]
enum Generation {
    Initial,
    Recovered,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct Handoff {
    source_path: PathBuf,
    cut: CognitiveRecoveryAnchor,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct RecoveredWrite {
    database_path: PathBuf,
    observed_before_write: CognitiveRecoveryAnchor,
    persisted_after_write: CognitiveRecoveryAnchor,
}

#[tokio::test]
async fn initial_generation_abrupt_exit_recovers_exact_cut() {
    exercise_crash(
        Generation::Initial,
        "cognitive_store::recovery::tests::bootstrap_crash::initial_generation_abrupt_exit_recovers_exact_cut",
    )
    .await;
}

#[tokio::test]
async fn recovered_generation_abrupt_exit_recovers_exact_cut() {
    exercise_crash(
        Generation::Recovered,
        "cognitive_store::recovery::tests::bootstrap_crash::recovered_generation_abrupt_exit_recovers_exact_cut",
    )
    .await;
}

async fn exercise_crash(generation: Generation, test_name: &str) {
    let owner = agent_id(198);
    if let Some(root) = std::env::var_os(CHILD_ROOT) {
        let root = PathBuf::from(root);
        let phase = std::env::var(CHILD_PHASE).expect("child phase");
        let umask = if cfg!(target_os = "linux") {
            std::fs::read_to_string("/proc/self/status")
                .ok()
                .and_then(|status| {
                    status
                        .lines()
                        .find(|line| line.starts_with("Umask:"))
                        .map(str::to_owned)
                })
        } else {
            None
        };
        retain_synced(
            &root.join(format!("command-{phase}/process.json")),
            &serde_json::json!({"pid": std::process::id(), "phase": &phase,
                "linux_proc_umask_line": umask}),
        );
        let layout = codex_hepta_paths::HeptaFleetRoot::parse(root.join("fleet"))
            .expect("child fleet")
            .layout()
            .agent(&owner);
        let access = CognitiveAccess::agent_private(owner.clone());
        let authority = recovery_authority(&owner);
        match phase.as_str() {
            "write" => {
                let mut store = CognitiveStore::open(&layout).await.expect("new owner");
                if matches!(generation, Generation::Recovered) {
                    let initial_path = store.path().to_path_buf();
                    let initial_cut = store.recovery_anchor().await.expect("initial cut");
                    store.close().await;
                    store = CognitiveStore::open_with_recovery(
                        &layout,
                        CognitiveRecoveryRequirement::ExactCurrentCut(&initial_cut),
                        &authority,
                        &RecoveryVerifier,
                    )
                    .await
                    .expect("first recovered generation");
                    assert_ne!(store.path(), initial_path.as_path());
                }
                let before_write = store.recovery_anchor().await.expect("before write");
                store
                    .append_source(
                        &access,
                        &source(
                            CognitiveScope::AgentPrivate,
                            "before-abrupt-exit",
                            "committed source before abrupt process exit",
                        ),
                    )
                    .await
                    .expect("commit before crash");
                let cut = store.recovery_anchor().await.expect("actual current cut");
                assert_ne!(cut, before_write);
                retain_synced(
                    &root.join("handoff.json"),
                    &Handoff {
                        source_path: store.path().to_path_buf(),
                        cut,
                    },
                );
                // Keep the pool and store fence live: this runs no Rust Drop.
                std::process::exit(CRASH_EXIT);
            }
            "recover" => {
                let handoff: Handoff =
                    serde_json::from_slice(&std::fs::read(root.join("handoff.json")).unwrap())
                        .expect("independent retained cut");
                let recovered = CognitiveStore::open_with_recovery(
                    &layout,
                    CognitiveRecoveryRequirement::ExactCurrentCut(&handoff.cut),
                    &authority,
                    &RecoveryVerifier,
                )
                .await
                .expect("fresh-process writable recovery with the retained WAL");
                let observed_before_write = recovered.recovery_anchor().await.unwrap();
                assert_eq!(observed_before_write, handoff.cut);
                let database_path = recovered.path().to_path_buf();
                assert_ne!(database_path, handoff.source_path);
                recovered
                    .append_source(
                        &access,
                        &source(
                            CognitiveScope::AgentPrivate,
                            "after-crash-recovery",
                            "new durable write in the recovered generation",
                        ),
                    )
                    .await
                    .expect("new generation is writable");
                let written_cut = recovered.recovery_anchor().await.unwrap();
                assert_ne!(written_cut, observed_before_write);
                recovered.close().await;
                let reopened = CognitiveStore::open(&layout)
                    .await
                    .expect("persisted reopen");
                assert_eq!(reopened.path(), database_path.as_path());
                let persisted_after_write = reopened.recovery_anchor().await.unwrap();
                assert_eq!(persisted_after_write, written_cut);
                reopened.close().await;
                retain_synced(
                    &root.join("recovered-write.json"),
                    &RecoveredWrite {
                        database_path,
                        observed_before_write,
                        persisted_after_write,
                    },
                );
            }
            phase => panic!("unexpected child phase: {phase}"),
        }
        return;
    }

    let evidence_root = std::env::var_os(EVIDENCE_ROOT);
    let temp = match evidence_root.as_ref() {
        Some(root) => {
            std::fs::create_dir_all(root).expect("evidence root");
            let prefix = match generation {
                Generation::Initial => "initial-generation-",
                Generation::Recovered => "recovered-generation-",
            };
            tempfile::Builder::new()
                .prefix(prefix)
                .tempdir_in(std::fs::canonicalize(root).expect("canonical evidence root"))
                .expect("unique retained evidence directory")
        }
        None => TempDir::new().expect("parent temp directory"),
    };
    let _layout = layout(&temp, &owner);
    let root = temp.path().to_path_buf();
    // Opt-in qualification evidence survives both success and assertion failure.
    let _cleanup = if evidence_root.is_some() {
        let _ = temp.keep();
        None
    } else {
        Some(temp)
    };
    let writer = child(&root, test_name, "write");
    assert_eq!(writer.status.code(), Some(CRASH_EXIT), "{writer:?}");
    let handoff: Handoff =
        serde_json::from_slice(&std::fs::read(root.join("handoff.json")).unwrap())
            .expect("actual writer handoff");
    let before = source_bundle(&handoff.source_path);
    retain_synced(&root.join("source-before.json"), &bundle_manifest(&before));
    for image in before.values() {
        assert!(matches!(&image.payload, EntryPayload::Bytes(_)));
    }
    for suffix in ["", "-wal", "-shm"] {
        let mut name = handoff.source_path.file_name().unwrap().to_os_string();
        name.push(suffix);
        assert!(
            before.contains_key(&name),
            "missing crash bundle member: {name:?}"
        );
        if suffix == "-wal" {
            assert!(before[&name].metadata.length > 32, "WAL has no frames");
        }
    }

    let recovery = child(&root, test_name, "recover");
    let after = source_bundle(&handoff.source_path);
    retain_synced(&root.join("source-after.json"), &bundle_manifest(&after));
    assert_eq!(after, before);
    assert_eq!(recovery.status.code(), Some(0), "{recovery:?}");
    for image in before.values() {
        assert_eq!(image.metadata.mode & 0o7777, 0o600);
    }
    let result: RecoveredWrite =
        serde_json::from_slice(&std::fs::read(root.join("recovered-write.json")).unwrap())
            .expect("actual recovered write receipt");
    assert_eq!(result.observed_before_write, handoff.cut);
    assert_ne!(result.persisted_after_write, result.observed_before_write);
    assert_ne!(result.database_path, handoff.source_path);
    assert!(result.database_path.is_file());
}

fn child(root: &Path, test_name: &str, phase: &str) -> Output {
    let executable = std::env::current_exe().expect("test binary");
    let evidence = root.join(format!("command-{phase}"));
    std::fs::create_dir(&evidence).expect("new command evidence directory");
    retain_synced(
        &evidence.join("request.json"),
        &serde_json::json!({
            "executable": executable,
            "args": ["--exact", test_name, "--nocapture"],
            "cwd": std::env::current_dir().unwrap(),
            "child_root": root, "phase": phase, "parent_pid": std::process::id(),
        }),
    );
    let started = Instant::now();
    let process = Command::new(&executable)
        .args(["--exact", test_name, "--nocapture"])
        .env(CHILD_ROOT, root)
        .env(CHILD_PHASE, phase)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("fresh child process");
    let pid = process.id();
    let output = process.wait_with_output().expect("completed child");
    retain_bytes_synced(&evidence.join("stdout.log"), &output.stdout);
    retain_bytes_synced(&evidence.join("stderr.log"), &output.stderr);
    retain_synced(
        &evidence.join("receipt.json"),
        &serde_json::json!({"pid": pid, "exit_code": output.status.code(),
            "status": output.status.to_string(), "wall_seconds": started.elapsed().as_secs_f64()}),
    );
    output
}

fn retain_synced<T: serde::Serialize>(path: &Path, value: &T) {
    let mut bytes = serde_json::to_vec(value).expect("serialize actual evidence");
    bytes.push(b'\n');
    retain_bytes_synced(path, &bytes);
}

fn retain_bytes_synced(path: &Path, bytes: &[u8]) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .expect("new external witness file");
    file.write_all(bytes)
        .expect("write original evidence bytes");
    file.sync_all().expect("sync external witness");
    File::open(path.parent().unwrap())
        .unwrap()
        .sync_all()
        .expect("sync external witness directory");
}

fn bundle_manifest(bundle: &BTreeMap<OsString, EntryImage>) -> serde_json::Value {
    let entries: BTreeMap<String, serde_json::Value> = bundle
        .iter()
        .map(|(name, image)| {
            let EntryPayload::Bytes(bytes) = &image.payload else {
                panic!("source bundle contains a symlink");
            };
            (
                name.to_string_lossy().into_owned(),
                serde_json::json!({
                    "bytes": bytes.len(), "sha256": Sha256Digest::for_bytes(bytes),
                    "mode": image.metadata.mode & 0o7777,
                    "device": image.metadata.device, "inode": image.metadata.inode,
                    "links": image.metadata.links,
                    "mtime_seconds": image.metadata.modified_seconds,
                    "mtime_nanoseconds": image.metadata.modified_nanoseconds,
                    "ctime_seconds": image.metadata.changed_seconds,
                    "ctime_nanoseconds": image.metadata.changed_nanoseconds,
                }),
            )
        })
        .collect();
    serde_json::to_value(entries).expect("source bundle manifest")
}

fn source_bundle(database: &Path) -> BTreeMap<OsString, EntryImage> {
    let names: Vec<OsString> = ["", "-wal", "-shm", "-journal"]
        .into_iter()
        .map(|suffix| {
            let mut name = database.file_name().unwrap().to_os_string();
            name.push(suffix);
            name
        })
        .collect();
    capture_recovery_tree(database.parent().unwrap())
        .entries
        .into_iter()
        .filter(|(name, _)| names.contains(name))
        .collect()
}
