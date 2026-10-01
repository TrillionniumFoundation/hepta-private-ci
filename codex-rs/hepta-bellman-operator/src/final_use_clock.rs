//! Temporal floor for a single owner-bound fit across forward host clock jumps.
//!
//! The fit context retains its original resource-budget origin. This clock
//! advances the owner's Unix-time windows from the latest trusted witness floor
//! using differences on that same monotonic elapsed clock. It issues no evidence
//! and does not change witness identity, generation, stop or authority fields.

use std::sync::Mutex;

use super::FinalUseErrorV1;

#[derive(Debug)]
struct ClockAnchorV1 {
    unix_micros: u64,
    elapsed_micros: u64,
    last_elapsed_micros: u64,
}

#[derive(Debug)]
pub(crate) struct FinalUseClockV1 {
    anchor: Mutex<ClockAnchorV1>,
}

impl FinalUseClockV1 {
    pub(crate) fn new(issued_at: u64) -> Self {
        Self {
            anchor: Mutex::new(ClockAnchorV1 {
                unix_micros: issued_at,
                elapsed_micros: 0,
                last_elapsed_micros: 0,
            }),
        }
    }

    /// A previously validated witness is a time floor, rather than a new
    /// observation. Earlier use-witness floors cannot undo the later publication
    /// floor supplied at call entry; witness chronology is checked by the caller.
    pub(crate) fn observe(
        &self,
        host_floor: u64,
        elapsed_micros: u64,
    ) -> Result<u64, FinalUseErrorV1> {
        let mut anchor = self
            .anchor
            .lock()
            .map_err(|_| FinalUseErrorV1::Binding("final-use clock state unavailable"))?;
        if elapsed_micros < anchor.last_elapsed_micros {
            return Err(FinalUseErrorV1::ClockRegression);
        }
        let elapsed = elapsed_micros
            .checked_sub(anchor.elapsed_micros)
            .ok_or(FinalUseErrorV1::ClockRegression)?;
        let advanced = anchor
            .unix_micros
            .checked_add(elapsed)
            .ok_or(FinalUseErrorV1::DeadlineExceeded)?;
        anchor.last_elapsed_micros = elapsed_micros;
        if host_floor > advanced {
            anchor.unix_micros = host_floor;
            anchor.elapsed_micros = elapsed_micros;
            Ok(host_floor)
        } else {
            // Preserve the original elapsed anchor on equal/frozen floors so
            // frequent checks cannot discard monotonic fractional progress.
            Ok(advanced)
        }
    }
}

#[cfg(test)]
#[path = "final_use_clock_tests.rs"]
mod tests;
