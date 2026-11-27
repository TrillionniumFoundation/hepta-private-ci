//! Three-process durability proof; no model or production authority is involved.
use super::*;

const RECOVERY_CHILD: &str = "cognitive_store::database_init_tests::crash_tests::recovery_child";

#[derive(Debug, PartialEq, serde::Serialize, serde::Deserialize, sqlx::FromRow)]
struct StoredSource {
    source_id: String,
    source_revision: i64,
    owner_agent_id: String,
    scope_kind: String,
    workspace_sha256: Option<String>,
    source_kind: String,
    content: Vec<u8>,
    content_sha256: String,
    observed_at_unix_seconds: i64,
    recorded_at_unix_seconds: i64,
}

async fn snapshot(store: &CognitiveStore) -> Result<Vec<StoredSource>, sqlx::Error> {
    sqlx::query_as(
        "SELECT source_id, source_revision, owner_agent_id, scope_kind, workspace_sha256,
                source_kind, content, content_sha256, observed_at_unix_seconds,
                recorded_at_unix_seconds FROM source_ledger ORDER BY source_id, source_revision",
    )
    .fetch_all(&store.pool)
    .await
}

fn write_receipt(root: &Path, name: &str, bytes: &[u8]) -> io::Result<()> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.join(name))?;
    file.write_all(bytes)?;
    file.sync_all()?;
    File::open(root)?.sync_all()
}

fn run_child(root: &Path, phase: &str) -> io::Result<()> {
    let mut child = Command::new(std::env::current_exe()?)
        .args(["--exact", RECOVERY_CHILD, "--ignored", "--nocapture"])
        .env("HEPTA_PRIVATE_DB_CHILD_ROOT", root)
        .env("HEPTA_PRIVATE_DB_RECOVERY_PHASE", phase)
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 60);
    loop {
        if let Some(status) = child.try_wait()? {
            assert!(status.success(), "{phase} child failed: {status}");
            return Ok(());
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("{phase} child exceeded deadline");
        }
        std::thread::sleep(Duration::from_millis(/*millis*/ 10));
    }
}

#[tokio::test]
#[ignore = "child-only fresh-process recovery and durability validation"]
async fn recovery_child() {
    let root = PathBuf::from(std::env::var_os("HEPTA_PRIVATE_DB_CHILD_ROOT").expect("root"));
    let phase = std::env::var("HEPTA_PRIVATE_DB_RECOVERY_PHASE").expect("phase");
    match phase.as_str() {
        "recover-write" => {
            let expected = read_anchor(&root).expect("decode cut");
            let store = recover(
                &layout(&root).expect("fixture layout"),
                &expected,
                &authority().expect("fixture authority"),
            )
            .await
            .expect("writable exact-cut recovery");
            assert_eq!(
                store.recovery_anchor().await.expect("recovered cut"),
                expected
            );
            assert_eq!(snapshot(&store).await.expect("all source fields").len(), 1);
            store
                .append_source(
                    &CognitiveAccess::agent_private(agent_id(/*suffix*/ 249)),
                    &source(
                        CognitiveScope::AgentPrivate,
                        "after-crash",
                        "new durable fact",
                    ),
                )
                .await
                .expect("new committed mutation");
            let rows = snapshot(&store).await.expect("all source fields");
            assert_eq!(rows.len(), 2);
            let updated = store.recovery_anchor().await.expect("updated cut");
            assert_ne!(updated, expected);
            write_receipt(
                &root,
                "updated-cut.json",
                &serde_json::to_vec(&updated).expect("encode"),
            )
            .expect("durable updated cut receipt");
            write_receipt(
                &root,
                "updated-rows.json",
                &serde_json::to_vec(&rows).expect("encode"),
            )
            .expect("durable updated rows receipt");
            store.close().await;
        }
        "verify-write" => {
            let store = CognitiveStore::open(&layout(&root).expect("fixture layout"))
                .await
                .expect("fresh durable reopen");
            let expected: CognitiveRecoveryAnchor =
                serde_json::from_slice(&fs::read(root.join("updated-cut.json")).expect("cut"))
                    .expect("decode cut");
            let rows: Vec<StoredSource> =
                serde_json::from_slice(&fs::read(root.join("updated-rows.json")).expect("rows"))
                    .expect("decode rows");
            assert_eq!(
                store.recovery_anchor().await.expect("durable cut"),
                expected
            );
            assert_eq!(snapshot(&store).await.expect("all source fields"), rows);
            store.close().await;
            write_receipt(&root, "verified.json", b"{\"verified\":true}\n")
                .expect("durable verification receipt");
        }
        _ => panic!("unknown child phase"),
    }
}

#[test]
fn abrupt_bootstrap_fresh_process_recovery_new_write_survives_third_process() {
    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    bootstrap(&root, "022").expect("cold bootstrap child");
    let original: Vec<_> = [
        "cognitive_1.sqlite3",
        "cognitive_1.sqlite3-wal",
        "cognitive_1.sqlite3-shm",
    ]
    .into_iter()
    .map(|name| {
        let path = layout(&root)
            .expect("fixture layout")
            .cognitive_root()
            .join(name);
        let metadata = fs::symlink_metadata(&path).expect("retained original");
        assert!(metadata.is_file());
        assert_eq!(metadata.mode() & 0o7777, 0o600);
        assert_eq!(metadata.nlink(), 1);
        let bytes = fs::read(&path).expect("original bytes");
        assert!(!bytes.is_empty(), "real pending bundle: {name}");
        (path, metadata.dev(), metadata.ino(), metadata.mode(), bytes)
    })
    .collect();
    run_child(&root, "recover-write").expect("start recovery child");
    run_child(&root, "verify-write").expect("start independent verification child");
    assert_eq!(
        fs::read(root.join("verified.json")).expect("C receipt"),
        b"{\"verified\":true}\n"
    );
    for (path, device, inode, mode, bytes) in original {
        let metadata = fs::symlink_metadata(&path).expect("source remains");
        assert_eq!(
            (metadata.dev(), metadata.ino(), metadata.mode()),
            (device, inode, mode)
        );
        assert_eq!(metadata.nlink(), 1);
        assert_eq!(fs::read(&path).expect("original unchanged"), bytes);
    }
}
