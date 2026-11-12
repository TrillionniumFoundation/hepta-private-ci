//! The fixed Linux monotonic time domain of the original Source input.

use crate::AgentdError;
use crate::CircuitTaskSourceInputV1;

pub(super) const DOMAIN: &str = "linux_clock_monotonic_micros_v1";

fn now() -> Result<u64, AgentdError> {
    let mut time = std::mem::MaybeUninit::<libc::timespec>::uninit();
    // SAFETY: clock_gettime initializes the live timespec on success.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, time.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the successful call initialized the complete timespec above.
    let time = unsafe { time.assume_init() };
    if time.tv_sec < 0 || !(0..1_000_000_000).contains(&time.tv_nsec) {
        return Err(AgentdError::GenerationFenced(
            "invalid monotonic clock".into(),
        ));
    }
    (time.tv_sec as u64)
        .checked_mul(1_000_000)
        .and_then(|seconds| seconds.checked_add(time.tv_nsec as u64 / 1_000))
        .ok_or_else(|| AgentdError::GenerationFenced("monotonic clock overflow".into()))
}

pub(super) fn sample() -> u64 {
    // An unreadable clock expires every bounded original input. It cannot
    // turn a failed observation into a fresh zero-time execution window.
    now().unwrap_or(u64::MAX)
}

pub(super) fn require_source_deadline(
    source: &CircuitTaskSourceInputV1,
) -> Result<(), AgentdError> {
    let observed = now()?;
    if source.monotonic_micros > observed || observed >= source.deadline_micros {
        return Err(AgentdError::GenerationFenced(
            "original Source monotonic window is absent or expired".into(),
        ));
    }
    Ok(())
}
