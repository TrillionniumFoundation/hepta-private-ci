//! Linux total budgets use the original suspend-aware clock, including every
//! final I/O result. Neither a scheduler pause nor suspend grants extra time.
use std::io;
use std::time::Duration;

#[derive(Clone, Copy)]
pub(crate) struct Deadline {
    started_ns: u64,
    end_ns: u64,
}
impl Deadline {
    pub(crate) fn after(budget: Duration) -> io::Result<Self> {
        let started_ns = now()?;
        let budget_ns = u64::try_from(budget.as_nanos()).map_err(|_| expired())?;
        if budget_ns == 0 {
            return Err(expired());
        }
        let end_ns = started_ns.checked_add(budget_ns).ok_or_else(expired)?;
        Ok(Self { started_ns, end_ns })
    }
    pub(crate) fn remaining(self) -> io::Result<Duration> {
        self.remaining_at(now()?)
    }
    /// Preserve the original absolute deadline while applying a shorter stage
    /// budget. Passing through another bootstrap phase never refreshes time.
    pub(crate) fn capped(self, budget: Duration) -> io::Result<Self> {
        self.remaining()?;
        let stage = Self::after(budget)?;
        let end = Self {
            started_ns: self.started_ns,
            end_ns: self.end_ns.min(stage.end_ns),
        };
        end.remaining()?;
        Ok(end)
    }
    fn remaining_at(self, observed_ns: u64) -> io::Result<Duration> {
        if observed_ns < self.started_ns {
            return Err(expired());
        }
        self.end_ns
            .checked_sub(observed_ns)
            .filter(|left| *left != 0)
            .map(Duration::from_nanos)
            .ok_or_else(expired)
    }
}
fn now() -> io::Result<u64> {
    crate::root_observation_cache::boottime_ns()
        .map_err(|_| io::Error::other("original Calculator boottime clock unavailable"))
}
fn expired() -> io::Error {
    io::Error::new(io::ErrorKind::TimedOut, "Calculator total deadline elapsed")
}

#[cfg(test)]
#[path = "calculator_deadline_tests.rs"]
mod tests;
