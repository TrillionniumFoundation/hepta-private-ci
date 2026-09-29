//! Hosted runs share the control owner's journal and exclusive writer lock.
//! A reservation is one local in-flight slot, not a token or payment grant.
//! Unknown execution retains that slot; unknown token usage remains `None`.
//!
//! The implementation is split by concern so checkpoint/reconciliation code can
//! be reviewed independently while compiling as this single module.

include!("native_control_v2_types.rs");
include!("native_control_v2_control_a.rs");
include!("native_control_v2_control_b.rs");
include!("native_control_v2_control_c.rs");
include!("native_control_v2_host.rs");
include!("native_control_v2_recovery.rs");
include!("native_control_v2_journal.rs");
include!("native_control_v2_helpers.rs");

#[cfg(test)]
#[path = "native_control_v2_tests.rs"]
mod v2_tests;

#[cfg(test)]
#[path = "native_control_v2_economic_tests.rs"]
mod economic_tests;
