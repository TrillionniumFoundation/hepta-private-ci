//! Real same-UID socket/pidfd component; this does not stand in for Root.

use std::os::fd::FromRawFd;

use super::*;

#[tokio::test]
async fn original_observation_absolute_end_survives_peer_checks_and_expires() -> anyhow::Result<()>
{
    let (client, _server) = UnixStream::pair()?;
    let pid = std::process::id();
    let stat = bounded_text(&format!("/proc/{pid}/stat"), 8192)?;
    let start = stat
        .rsplit_once(") ")
        .and_then(|(_, fields)| fields.split_whitespace().nth(19))
        .ok_or_else(|| io::Error::other("actual process lifetime absent"))?
        .parse()?;
    let peer = AgentdRootAuthorityPeer {
        pid,
        boot_id: bounded_text("/proc/sys/kernel/random/boot_id", 128)?
            .trim()
            .into(),
        process_start_ticks: start,
    };
    // SAFETY: syscall opens this live test process with no flags; its result
    // is checked before taking the exclusively owned descriptor.
    let descriptor = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if descriptor < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: the checked fresh descriptor has not been owned elsewhere.
    let pidfd = unsafe { OwnedFd::from_raw_fd(descriptor as i32) };
    // SAFETY: this query reads only the current test's actual credential.
    let uid = unsafe { libc::geteuid() };
    let end = Instant::now() + Duration::from_secs(2);
    let transport = RootObservationStream::from_stream_for_uid_until(
        client,
        peer,
        pidfd,
        Duration::from_millis(100),
        end,
        uid,
    )?;
    assert_eq!(transport.end, end);
    tokio::time::sleep_until(end.into()).await;
    let request =
        serde_json::json!({"schema_version": 2, "operation": "runtime.authority.observe.v2"});
    assert!(transport.read::<u64>(&request).await.is_err());
    assert!(transport.read::<u64>(&request).await.is_err());
    Ok(())
}
