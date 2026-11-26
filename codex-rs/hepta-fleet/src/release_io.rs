//! Fixed operation witnesses for release I/O failures in this crate's unit tests.
//!
//! Return the original result, including its original I/O error. Normal library
//! builds do not write diagnostics; paths and program bytes are never recorded.

use crate::FleetRegistryError;

#[cfg(all(test, target_os = "macos"))]
#[path = "release_rename_diagnostics.rs"]
mod rename_diagnostics;

#[cfg(all(test, target_os = "macos"))]
pub(crate) use rename_diagnostics::observe_failed_rename;

pub(crate) fn observe_io<T>(
    operation: &'static str,
    result: std::io::Result<T>,
) -> std::io::Result<T> {
    #[cfg(test)]
    if let Err(error) = &result {
        record_error(operation, error);
    }
    #[cfg(not(test))]
    let _ = operation;
    result
}

pub(crate) fn observe_release<T>(
    operation: &'static str,
    result: Result<T, FleetRegistryError>,
) -> Result<T, FleetRegistryError> {
    #[cfg(test)]
    if let Err(FleetRegistryError::Io(error)) = &result {
        record_error(operation, error);
    }
    #[cfg(not(test))]
    let _ = operation;
    result
}

#[cfg(test)]
fn record_error(operation: &'static str, error: &std::io::Error) {
    use std::io::Write;

    // Diagnostics must not replace the original error if stderr is unavailable.
    let _ = writeln!(
        std::io::stderr().lock(),
        "fleet_release_io operation={operation} kind={:?} raw_os_error={:?}",
        error.kind(),
        error.raw_os_error(),
    );
}
