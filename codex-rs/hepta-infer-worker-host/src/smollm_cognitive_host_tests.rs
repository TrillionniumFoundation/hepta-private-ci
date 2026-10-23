use super::*;
use std::io::Seek;
use std::io::SeekFrom;

#[test]
fn parameter_capture_keeps_the_original_descriptor_and_cursor()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("selected.safetensors");
    let bytes = b"original selected parameter bytes";
    std::fs::write(&path, bytes)?;
    let mut file = File::open(&path)?;
    file.seek(SeekFrom::End(0))?;
    std::fs::rename(&path, directory.path().join("retained.safetensors"))?;
    std::fs::write(&path, b"replacement pathname contents")?;
    assert_eq!(read_parameter_fd(&file, Digest32::of_bytes(bytes))?, bytes);
    assert_eq!(file.stream_position()?, bytes.len() as u64);
    assert!(
        read_parameter_fd(&file, Digest32::of_bytes(b"replacement pathname contents")).is_err()
    );
    Ok(())
}

#[test]
fn parameter_capture_refuses_empty_oversize_or_changed_selected_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    let file = tempfile::tempfile()?;
    let expected = Digest32::of_bytes(b"selected bytes");
    assert!(read_parameter_fd(&file, expected).is_err());
    file.set_len(MAX_PARAMETER_BYTES + 1)?;
    assert!(read_parameter_fd(&file, expected).is_err());
    file.set_len(14)?;
    assert!(read_parameter_fd(&file, expected).is_err());
    assert!(read_parameter_fd(&file, Digest32::ZERO).is_err());
    Ok(())
}

#[test]
fn inference_owner_paths_refuse_body_and_filesystem_aliases()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let body = root.join("body");
    std::fs::create_dir(&body)?;
    assert!(validate_inference_owner_path(&root.join("journal"), &[&body]).is_ok());
    assert!(validate_inference_owner_path(&body.join("journal"), &[&body]).is_err());
    assert!(validate_inference_owner_path(&root.join("body/../journal"), &[&body]).is_err());
    std::fs::write(root.join("target"), b"owner")?;
    std::os::unix::fs::symlink(root.join("target"), root.join("alias"))?;
    assert!(validate_inference_owner_path(&root.join("alias"), &[&body]).is_err());
    std::fs::hard_link(root.join("target"), root.join("hard-link"))?;
    assert!(validate_inference_owner_path(&root.join("hard-link"), &[&body]).is_err());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropping_preparation_future_cancels_inflight_blocking_owner() {
    let token = CancellationToken::new();
    let owner_token = token.clone();
    let (started_tx, started_rx) = tokio::sync::oneshot::channel();
    let (ended_tx, ended_rx) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        let _pending = CancelPreparation(Some(owner_token.clone()));
        tokio::task::spawn_blocking(move || {
            started_tx.send(()).unwrap();
            // A cancellation regression must fail this test without leaving
            // an infinite blocking task for runtime destruction to wait on.
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
            while !owner_token.is_cancelled() && std::time::Instant::now() < deadline {
                std::thread::sleep(std::time::Duration::from_millis(1));
            }
            let _ = ended_tx.send(owner_token.is_cancelled());
        })
        .await
        .unwrap();
    });
    started_rx.await.unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert!(
        tokio::time::timeout(std::time::Duration::from_secs(5), ended_rx)
            .await
            .unwrap()
            .unwrap()
    );
    assert!(token.is_cancelled());
}
