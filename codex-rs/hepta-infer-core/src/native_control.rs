//! Hosted and experimental-local runs share the control owner's journal and
//! exclusive writer lock. A reservation is one local in-flight slot, not a
//! token or payment grant. Unknown execution retains that slot; unknown token
//! or usage evidence remains unknown.

include!("native_control/model.rs");
include!("native_control/control_impl.rs");
include!("native_control/journal_impl.rs");
include!("native_control/state.rs");

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "native_control_v2_tests.rs"]
mod v2_tests;
