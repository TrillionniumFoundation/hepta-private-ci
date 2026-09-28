//! Revision- and authority-epoch-fenced runtime control state plus a bounded,
//! snapshot-coherent global planning kernel.
//!
//! The historical crate root is retained verbatim in `lib_core.rs`.  This root
//! adds the authenticated context adapter without rewriting unrelated public
//! surfaces.

#![forbid(unsafe_code)]

#[path = "lib_core.rs"]
mod legacy_root;
pub use legacy_root::*;

mod authenticated_context;
pub use authenticated_context::{
    AuthenticatedContextRecordV1, AuthenticatedObservedContextV1,
    plan_authenticated_observed_context,
};
