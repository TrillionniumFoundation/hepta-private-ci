//! Hardened capability-scoped federated memory read boundary.
//!
//! V2 is read-only and fail-closed. Every admitted response is bound to a
//! verified capability receipt, an enrolled peer key, an exact query binding,
//! current revocation state and a bounded deadline. Returned receipts never
//! grant authority.

mod authority;
mod cache;
mod execution;
mod model;
mod response;
mod transport;

pub use authority::*;
pub use cache::*;
pub use execution::*;
pub use model::*;
pub use response::*;
pub use transport::*;

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
