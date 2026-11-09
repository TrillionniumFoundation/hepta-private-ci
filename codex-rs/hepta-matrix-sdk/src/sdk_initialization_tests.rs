use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::MatrixSdkError;
use super::initialization_with_deadline;
use super::load_session;

#[tokio::test]
async fn initialization_preserves_completed_value_and_phase_error() {
    assert_eq!(initialization_with_deadline(async { Ok(17) }).await, Ok(17));
    assert_eq!(
        initialization_with_deadline(async { Err::<(), _>(MatrixSdkError::ClientBuild) }).await,
        Err(MatrixSdkError::ClientBuild),
    );
}

#[tokio::test]
async fn initialization_deadline_drops_pending_future_and_identifies_timeout() {
    struct DropMarker(Arc<AtomicBool>);
    impl Drop for DropMarker {
        fn drop(&mut self) {
            self.0.store(true, Ordering::SeqCst);
        }
    }

    let dropped = Arc::new(AtomicBool::new(false));
    let marker = DropMarker(Arc::clone(&dropped));
    let result = initialization_with_deadline(async move {
        let _marker = marker;
        std::future::pending::<Result<(), MatrixSdkError>>().await
    })
    .await;
    assert_eq!(result, Err(MatrixSdkError::InitializationTimeout));
    assert!(dropped.load(Ordering::SeqCst));
}

#[test]
fn malformed_session_read_is_distinct_from_store_initialization()
-> Result<(), Box<dyn std::error::Error>> {
    let temp = tempfile::tempdir()?;
    let session = temp.path().join("session.json");
    assert!(load_session(&session)?.is_none());
    std::fs::write(&session, "not a session")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&session, std::fs::Permissions::from_mode(0o600))?;
    }
    assert!(matches!(load_session(&session), Err(MatrixSdkError::SessionRead)));
    Ok(())
}
