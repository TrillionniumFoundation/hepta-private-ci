//! Real inherited sockets/pidfds; no compiler, signer or effect owner is faked.
use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::os::fd::FromRawFd;
use std::os::unix::fs::PermissionsExt;

fn listener_and_identity()
-> Result<(tempfile::TempDir, OwnedFd, OwnedFd, AgentdNotesUiPeer), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("notes-ui.sock");
    let listener = std::os::unix::net::UnixListener::bind(&path)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    let pid = std::process::id();
    // SAFETY: pidfd_open takes a scalar PID and zero flags; success returns one
    // newly owned fd, converted exactly once below.
    let number = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if number < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: number is the new owned pidfd returned above.
    let pidfd = unsafe { OwnedFd::from_raw_fd(number as libc::c_int) };
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    let process_start_ticks = stat
        .rsplit_once(") ")
        .unwrap()
        .1
        .split_whitespace()
        .nth(19)
        .unwrap()
        .parse()?;
    let peer = AgentdNotesUiPeer {
        uid: std::fs::metadata(&path)?.uid(),
        pid,
        process_start_ticks,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
    };
    Ok((directory, listener.into(), pidfd, peer))
}

#[tokio::test]
async fn notes_ui_actual_session_gets_a_bounded_cached_view_and_only_queues_one_command()
-> Result<(), Box<dyn Error>> {
    let (directory, listener, pidfd, peer) = listener_and_identity()?;
    let endpoint = NotesUiEndpoint::from_inherited(listener, pidfd, peer)?;
    let queue = NotesUiQueue::new();
    let exchange = async {
        let mut stream =
            tokio::net::UnixStream::connect(directory.path().join("notes-ui.sock")).await?;
        stream.write_all(b"{\"type\":\"availability\"}\n").await?;
        let mut response = Vec::new();
        stream.read_to_end(&mut response).await?;
        Ok::<_, Box<dyn Error>>(serde_json::from_slice::<ObjectiveObservation>(&response)?)
    };
    let view = tokio::select! {
        result = endpoint.receive(&queue) => panic!("receiver unexpectedly finished: {result:?}"),
        result = tokio::time::timeout(Duration::from_millis(150), exchange) => result??,
    };
    assert_eq!(
        (view.stage, view.request_retained, view.publication_retained),
        (ObjectiveStage::Unavailable, false, false)
    );
    assert_eq!(
        queue
            .take(std::time::Instant::now())
            .unwrap()
            .unwrap()
            .command,
        ObjectiveCommand::Availability {}
    );
    assert!(queue.take(std::time::Instant::now()).unwrap().is_none());
    Ok(())
}

#[tokio::test]
async fn notes_ui_rejects_wrong_pidfd_and_non_listener_before_accepting_bytes()
-> Result<(), Box<dyn Error>> {
    let (_directory, listener, pidfd, mut peer) = listener_and_identity()?;
    peer.pid += 1;
    assert!(NotesUiEndpoint::from_inherited(listener, pidfd, peer).is_err());
    let (_directory, _listener, pidfd, peer) = listener_and_identity()?;
    let (stream, _other) = std::os::unix::net::UnixStream::pair()?;
    assert!(NotesUiEndpoint::from_inherited(stream.into(), pidfd, peer).is_err());
    Ok(())
}
