use std::io::ErrorKind;
use std::os::unix::fs::MetadataExt;

use super::*;

#[tokio::test]
async fn async_peer_process_binds_actual_uid_and_pid() -> IoResult<()> {
    let directory = tempfile::tempdir()?;
    let socket = directory.path().join("peer.sock");
    let mut listener = UnixListener::bind(&socket).await?;
    let stream = UnixStream::connect(&socket).await?;
    let _accepted = listener.accept().await?;
    let uid = std::fs::metadata("/proc/self")?.uid();
    let pid = std::process::id();
    stream.ensure_peer_process(uid, pid)?;
    for (wrong_uid, wrong_pid) in [(uid + 1, pid), (uid, pid + 1)] {
        let error = stream
            .ensure_peer_process(wrong_uid, wrong_pid)
            .expect_err("wrong kernel tuple");
        assert_eq!(error.kind(), ErrorKind::PermissionDenied);
    }
    Ok(())
}
