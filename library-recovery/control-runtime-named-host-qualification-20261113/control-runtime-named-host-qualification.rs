use std::fmt::Write as _;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_control_plane::PlannerStoreOptionsV1;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_types::Digest32;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let receipt_path = std::env::var("HEPTA_CONTROL_RUNTIME_RECEIPT_PATH")?;
    let source_sha = std::env::var("HEPTA_CONTROL_RUNTIME_SOURCE_SHA")?;
    let source_tree = std::env::var("HEPTA_CONTROL_RUNTIME_SOURCE_TREE")?;
    let lane = std::env::var("HEPTA_CONTROL_RUNTIME_QUALIFICATION_LANE")?;
    let host = std::env::var("HEPTA_CONTROL_RUNTIME_HOST_ID")?;
    let rustc = std::env::var("HEPTA_CONTROL_RUNTIME_RUSTC")?;
    let filesystem = std::env::var("HEPTA_CONTROL_RUNTIME_FS_PROFILE")?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let root = std::env::temp_dir().join(format!(
        "hepta-control-runtime-qualification-{}-{nonce}",
        std::process::id()
    ));
    std::fs::create_dir(&root)?;
    let store_path = root.join("planner.store");
    let backup_path = root.join("planner.backup");

    let started = Instant::now();
    let head = {
        let mut store = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())?;
        store.append(
            PlannerStoreRecordKindV1::SnapshotEnvelope,
            Digest32::of_bytes(b"named-host-snapshot"),
            b"complete named-host snapshot envelope",
        )?;
        store.append_decision_envelope(
            Digest32::of_bytes(b"named-host-decision"),
            b"complete named-host decision envelope",
        )?;
        store.record_external_checkpoint(
            Digest32::of_bytes(b"named-host-checkpoint"),
            Digest32::of_bytes(b"named-host-anchor"),
            Digest32::of_bytes(b"named-host-signer"),
            Digest32::of_bytes(b"named-host-signature"),
        )?;
        store.backup_to(&backup_path)?;
        store.head_digest()
    };
    let reopened = PlannerStoreV1::open(&store_path, PlannerStoreOptionsV1::default())?;
    if reopened.records().len() != 3 || reopened.head_digest() != head {
        return Err("named-host reopen did not preserve the exact planner head".into());
    }
    let elapsed_micros = started.elapsed().as_micros();
    let store_bytes = std::fs::metadata(&store_path)?.len();
    let backup_bytes = std::fs::metadata(&backup_path)?.len();

    let mut json = String::new();
    write!(
        json,
        "{{\n  \"schema\": \"hepta.control-runtime-named-host.v1\",\n  \"source_sha\": \"{}\",\n  \"source_tree\": \"{}\",\n  \"lane\": \"{}\",\n  \"host\": \"{}\",\n  \"rustc\": \"{}\",\n  \"filesystem\": \"{}\",\n  \"records\": 3,\n  \"store_bytes\": {},\n  \"backup_bytes\": {},\n  \"open_append_backup_reopen_micros\": {},\n  \"head_digest\": \"{}\",\n  \"authority_delta\": \"none\",\n  \"activation\": false,\n  \"release\": false\n}}\n",
        escape(&source_sha),
        escape(&source_tree),
        escape(&lane),
        escape(&host),
        escape(&rustc),
        escape(&filesystem),
        store_bytes,
        backup_bytes,
        elapsed_micros,
        head,
    )?;
    std::fs::write(receipt_path, json)?;
    drop(reopened);
    std::fs::remove_dir_all(root)?;
    Ok(())
}

fn escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}
