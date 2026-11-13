//! Fixed one-time scheduling exchange on the already authenticated Source
//! stream. It spends frame 1 of the original allowance and proves no task result.

use std::os::fd::RawFd;
use std::time::{Duration, Instant};
use codex_hepta_types::Digest32;
use crate::AgentdError;
use super::{Error, read_request, wire};

pub(crate) fn frame(binding: Digest32, nonce: [u8; 16]) -> Result<Vec<u8>, AgentdError> {
    let mut bytes = read_request(binding, nonce, /*id*/ 1)
        .map_err(|error| AgentdError::Protocol(error.to_string()))?;
    bytes[..8].copy_from_slice(b"HCPRERDY");
    Ok(bytes)
}

pub(super) fn wait_original_source_first_frame(socket: RawFd, end: Instant) -> Result<(), Error> {
    let remaining = end.checked_duration_since(Instant::now())
        .filter(|value| !value.is_zero() && *value <= Duration::from_secs(30))
        .ok_or(Error::Unavailable)?;
    let timeout = i32::try_from(remaining.as_millis().max(1)).map_err(|_| Error::Unavailable)?;
    let mut descriptor = libc::pollfd { fd: socket, events: libc::POLLIN, revents: 0 };
    // SAFETY: the live original channel owns socket for this call. The single
    // initialized pollfd is valid; poll neither reads nor duplicates the fd.
    let ready = unsafe { libc::poll(&mut descriptor, 1, timeout) };
    if ready != 1 || descriptor.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0
        || descriptor.revents & libc::POLLIN == 0
    { return Err(Error::Unavailable); }
    wire::before(end)
}
