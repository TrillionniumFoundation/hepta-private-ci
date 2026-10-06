//! Validate the Windows peer-PID ioctl's fixed ULONG output. A zero reported
//! length is a known provider anomaly, not a general WSAIoctl output contract.
use std::io;

pub(super) fn query_peer_pid(
    mut query: impl FnMut(&mut u32, &mut u32) -> io::Result<()>,
) -> io::Result<u32> {
    let mut pid = 0_u32;
    let mut returned = 0_u32;
    query(&mut pid, &mut returned)?;
    validate_output(pid, returned)?;
    if returned == 0 {
        // Microsoft afunix.h specifies a ULONG PID. For the independently
        // observed zero-length anomaly, require the net output value to replace every complementary bit
        // and reproduce the same nonzero PID. This is consistency evidence,
        // not an authoritative API contract or PID-lifetime proof. It rejects
        // partial/no writes; it does not replace subsequent token/SID checks.
        // https://github.com/microsoft/WSL/issues/4676
        let mut confirmation = !pid;
        let mut confirmation_returned = 0_u32;
        query(&mut confirmation, &mut confirmation_returned)?;
        validate_output(confirmation, confirmation_returned)?;
        if confirmation != pid {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "Windows AF_UNIX peer process ID was not consistently written",
            ));
        }
    }
    Ok(pid)
}

/// Classify only the captured immediate return/error pair, never a later last-error value.
pub(super) fn validate_ioctl_status(result: i32, socket_error: Option<i32>) -> io::Result<()> {
    match (result, socket_error) {
        (0, None) => Ok(()),
        (-1, Some(error)) => Err(io::Error::from_raw_os_error(error)),
        _ => Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Windows AF_UNIX peer query returned an unexpected API status",
        )),
    }
}

fn validate_output(pid: u32, returned: u32) -> io::Result<()> {
    if pid == 0 || (returned != 0 && returned != std::mem::size_of::<u32>() as u32) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "Windows AF_UNIX peer did not return a valid process ID",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "windows_peer_pid_tests.rs"]
mod tests;
