//! Authority-free Rust control presentation and authenticated request client.
//!
//! Runtime owners retain admission, effect authorization and terminal facts.
//! This crate owns only bounded local projections and recovery identities.
//! Blocking transports are intended for a supervised native worker, never the UI thread.

pub mod canonical;
pub mod client;
pub mod contract;
pub mod error;
#[cfg(feature = "http")]
pub mod http_transport;
pub mod ledger;
pub mod maintenance;
pub mod native_projection;
pub mod projection;
pub mod recovery;
pub mod transport;

pub use client::RuntimeClient;
pub use error::{ControlError, ErrorCode, Result};
#[cfg(feature = "http")]
pub use http_transport::{HttpTransport, MemoryCredentials};
pub use projection::{ModuleProjection, RuntimeProjection, Snapshot, project_runtime};
pub use recovery::{FileRecoveryStore, RecoveryScope, RecoveryStore};
pub use transport::ControlTransport;

#[cfg(test)]
#[path = "client_http_product_tests.rs"]
mod client_http_product_tests;
