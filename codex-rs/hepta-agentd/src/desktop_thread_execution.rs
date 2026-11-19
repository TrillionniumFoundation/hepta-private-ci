//! The same restrictive Core configuration is retained for the new catalog.
//! Its explicit profile identity prevents legacy Notes seed reinterpretation.
pub(crate) use crate::notes_thread_execution::inspect;
pub(crate) use crate::notes_thread_execution::verify_effective;

pub(crate) const PROFILE: &str = "hepta.desktop.core-execution.v1";
pub const ORIGINAL_DESKTOP_THREAD_EXECUTION_CONFIG: &str =
    crate::notes_thread_execution::ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG;
pub const ORIGINAL_DESKTOP_THREAD_ENVIRONMENTS_CONFIG: &str =
    crate::notes_thread_execution::ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG;
