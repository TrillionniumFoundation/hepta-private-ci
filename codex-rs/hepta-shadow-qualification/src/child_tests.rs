use std::path::Path;

use tokio::io::AsyncWriteExt;

use super::child::capture_stderr;
use super::child::persist_inbound;
use crate::QualificationError;
use crate::Surface;
use crate::durable::create_private_directory;

#[test]
fn persists_inbound_wire_before_rejecting_invalid_json() -> Result<(), QualificationError> {
    let temp = tempfile::tempdir()?;
    let root = private_child(temp.path(), "protocol")?;
    assert!(persist_inbound(&root, Surface::AppServer, 1, b"not-json\n").is_err());
    assert!(root.join("app_server-inbound-000001.raw.jsonl").is_file());
    assert!(
        root.join("app_server-inbound-000001.receipt.json")
            .is_file()
    );
    Ok(())
}

#[tokio::test]
async fn drains_and_bounds_stderr_while_hashing_the_full_stream() -> Result<(), QualificationError>
{
    let temp = tempfile::tempdir()?;
    let root = private_child(temp.path(), "protocol")?;
    let path = root.join("stderr.log");
    let (mut writer, reader) = tokio::io::duplex(2 * 1024 * 1024);
    let payload = vec![b'x'; 1024 * 1024 + 17];
    let write_task = tokio::spawn(async move {
        writer.write_all(&payload).await?;
        writer.shutdown().await
    });
    let outcome = capture_stderr(reader, path.clone()).await?;
    write_task
        .await
        .map_err(|error| QualificationError::State(error.to_string()))??;
    assert_eq!(outcome.size_bytes, 1024 * 1024 + 17);
    assert!(outcome.truncated);
    assert_eq!(std::fs::metadata(path)?.len(), 1024 * 1024);
    assert_eq!(outcome.sha256.len(), 64);
    Ok(())
}

fn private_child(parent: &Path, name: &str) -> Result<std::path::PathBuf, QualificationError> {
    let child = parent.join(name);
    create_private_directory(&child)?;
    Ok(child)
}
