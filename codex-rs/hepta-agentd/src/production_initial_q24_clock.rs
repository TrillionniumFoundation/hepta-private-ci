//! The original Source monotonic domain and Circuit wall-clock domain.

use crate::AgentdError;
use crate::CircuitCellTimeV1;
use crate::CircuitTaskSourceInputV1;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(in crate::production_launcher) const DOMAIN: &str = "linux_clock_monotonic_micros_v1";

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

pub(in crate::production_launcher) fn sample() -> CircuitCellTimeV1 {
    let cell_micros = now().unwrap_or(u64::MAX);
    let circuit_millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok())
        .unwrap_or(u64::MAX);
    // Either unreadable clock expires both original owners. Never substitute
    // the monotonic epoch for UNIX time, truncate overflow, or renew a deadline.
    if cell_micros == u64::MAX || circuit_millis == u64::MAX {
        return CircuitCellTimeV1 {
            circuit_millis: u64::MAX,
            cell_micros: u64::MAX,
        };
    }
    CircuitCellTimeV1 {
        circuit_millis,
        cell_micros,
    }
}

pub(in crate::production_launcher) fn require_source_deadline(
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

#[cfg(test)]
#[path = "production_initial_q24_clock_tests.rs"]
mod tests;
