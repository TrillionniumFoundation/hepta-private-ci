use std::time::Instant;

/// Monotonic clock used for total and per-stage V3 budget accounting.
pub trait CompositionClockV3 {
    fn now_micros(&mut self) -> u64;
}

#[derive(Debug)]
pub struct SystemCompositionClockV3 {
    started: Instant,
}

impl Default for SystemCompositionClockV3 {
    fn default() -> Self {
        Self {
            started: Instant::now(),
        }
    }
}

impl CompositionClockV3 for SystemCompositionClockV3 {
    fn now_micros(&mut self) -> u64 {
        u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX)
    }
}

/// Cancellation fence checked before and after every V3 owner boundary. A
/// production adapter with blocking I/O must additionally implement owner-side
/// interruption because the synchronous facade cannot preempt adapter code.
pub trait CompositionCancellationV3 {
    fn is_cancelled(&self) -> bool;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelledV3;

impl CompositionCancellationV3 for NeverCancelledV3 {
    fn is_cancelled(&self) -> bool {
        false
    }
}
