use std::io::ErrorKind;
use std::sync::Arc;

use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

use super::MatrixdControlError;
use super::MatrixdControlServer;
use super::tests::FakeTransport;
use super::tests::state;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[tokio::test]
async fn owner_control_refuses_without_changing_missing_or_existing_paths() -> TestResult {
    let temp = TempDir::new()?;
    let fake = Arc::new(FakeTransport::default());
    let (state, _) = state(&temp, Arc::clone(&fake)).await?;
    let missing_parent = temp.path().join("missing-control");
    let existing_parent = temp.path().join("existing-control");
    std::fs::create_dir(&existing_parent)?;
    let existing_socket = existing_parent.join("control.sock");
    std::fs::write(&existing_socket, b"existing rendezvous must survive")?;
    let sentinel = existing_parent.join("sentinel");
    std::fs::write(&sentinel, b"unrelated owner data")?;
    let before = socket_directory_image(&existing_parent)?;

    for socket in [missing_parent.join("control.sock"), existing_socket] {
        let result =
            MatrixdControlServer::bind(socket, Arc::clone(&state), CancellationToken::new()).await;
        assert!(matches!(
            result,
            Err(MatrixdControlError::Io(ref error))
                if error.kind() == ErrorKind::Unsupported
        ));
        assert!(!missing_parent.try_exists()?);
        assert_eq!(socket_directory_image(&existing_parent)?, before);
    }
    Ok(())
}

fn socket_directory_image(
    path: &std::path::Path,
) -> std::io::Result<Vec<(std::ffi::OsString, bool, Vec<u8>)>> {
    let mut image = std::fs::read_dir(path)?
        .map(|entry| {
            let entry = entry?;
            Ok((
                entry.file_name(),
                entry.metadata()?.permissions().readonly(),
                std::fs::read(entry.path())?,
            ))
        })
        .collect::<std::io::Result<Vec<_>>>()?;
    image.sort();
    Ok(image)
}
