use super::*;

use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawSocket;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Networking::WinSock::INVALID_SOCKET;
use windows_sys::Win32::Security::CreateWellKnownSid;
use windows_sys::Win32::Security::WinWorldSid;

#[test]
fn invalid_socket_cannot_supply_owner_authority() {
    assert!(ensure_current_user_peer(INVALID_SOCKET as RawSocket).is_err());
}

#[test]
fn unavailable_process_token_fails_closed() {
    assert!(UserSid::from_process(ptr::null_mut()).is_err());
}

#[test]
fn exited_process_cannot_supply_owner_authority() -> io::Result<()> {
    let mut child = std::process::Command::new("cmd.exe")
        .args(["/C", "exit", "0"])
        .spawn()?;
    let process = child.as_handle().try_clone_to_owned()?;
    assert!(child.wait()?.success());
    let error = ensure_running(&process)
        .expect_err("an exited peer must not authorize a buffered control request");
    assert_eq!(error.kind(), ErrorKind::PermissionDenied);
    Ok(())
}

#[test]
fn current_process_token_has_stable_owner_identity() -> io::Result<()> {
    let first = UserSid::from_process(unsafe { GetCurrentProcess() })?;
    let second = UserSid::from_process(unsafe { GetCurrentProcess() })?;
    first.ensure_owner(&second)
}

#[test]
fn owner_identity_is_bound_to_a_connected_child_process() -> io::Result<()> {
    const CHILD_SOCKET: &str = "HEPTA_UDS_PEER_TEST_CHILD_SOCKET";
    let budget = Duration::from_secs(/*secs*/ 10);
    if let Some(socket_path) = std::env::var_os(CHILD_SOCKET) {
        let mut stream = uds_windows::UnixStream::connect(socket_path)?;
        stream.set_read_timeout(Some(budget))?;
        ensure_current_user_peer(stream.as_raw_socket())?;
        let mut response = [0];
        stream.read_exact(&mut response)?;
        assert_eq!(response, [1]);
        return Ok(());
    }

    let directory = tempfile::tempdir()?;
    let socket_path = directory.path().join("peer.sock");
    let listener = uds_windows::UnixListener::bind(&socket_path)?;
    listener.set_nonblocking(/*nonblocking*/ true)?;
    let mut child = std::process::Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            "windows_peer::tests::owner_identity_is_bound_to_a_connected_child_process",
            "--nocapture",
        ])
        .env(CHILD_SOCKET, socket_path)
        .spawn()?;
    let verification = (|| -> io::Result<()> {
        let deadline = Instant::now() + budget;
        let mut stream = loop {
            match listener.accept() {
                Ok((stream, _address)) => break stream,
                Err(error) if error.kind() == ErrorKind::WouldBlock => {
                    if Instant::now() >= deadline {
                        return Err(io::Error::new(
                            ErrorKind::TimedOut,
                            "child did not connect to the owner-local socket",
                        ));
                    }
                    std::thread::sleep(Duration::from_millis(/*millis*/ 10));
                }
                Err(error) => return Err(error),
            }
        };
        stream.set_write_timeout(Some(budget))?;
        assert_eq!(connected_process_id(stream.as_raw_socket())?, child.id());
        ensure_current_user_peer(stream.as_raw_socket())?;
        stream.write_all(&[1])
    })();
    let status = child.wait()?;
    verification?;
    assert!(status.success(), "child peer verification failed: {status}");
    Ok(())
}

#[test]
fn valid_different_sid_cannot_supply_owner_authority() -> io::Result<()> {
    let owner = UserSid::from_process(unsafe { GetCurrentProcess() })?;
    let mut other = UserSid([0; SECURITY_MAX_SID_SIZE as usize / size_of::<u32>()]);
    let mut size = SECURITY_MAX_SID_SIZE;
    assert_ne!(
        unsafe {
            CreateWellKnownSid(
                WinWorldSid,
                ptr::null_mut(),
                other.0.as_mut_ptr().cast(),
                &mut size,
            )
        },
        0
    );
    let error = other
        .ensure_owner(&owner)
        .expect_err("the Everyone SID must not authorize an owner-local peer");
    assert_eq!(error.kind(), ErrorKind::PermissionDenied);
    Ok(())
}
