//! Private sequencing of fixed original checks and their original operation.
//! This is not an external callback/authority registration interface.
use std::io;
use std::time::Instant;

pub(crate) fn checked_step<T>(
    end: Instant,
    check: impl FnOnce() -> io::Result<()>,
    operation: impl FnOnce() -> io::Result<T>,
) -> io::Result<T> {
    require_before(end)?;
    check()?;
    operation()
}

pub(crate) fn require_before(end: Instant) -> io::Result<()> {
    if Instant::now() >= end {
        return Err(io::Error::other(
            "original Root admin cumulative deadline elapsed",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "authority_host_admin_deadline_tests.rs"]
mod tests;
