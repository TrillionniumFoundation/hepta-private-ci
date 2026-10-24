//! Low-level Windows file mechanisms, without private-owner qualification.
//!
//! Held handles and no-reparse opens do not establish owner SID/DACL policy,
//! sandbox isolation, or power-loss durability. No private-owner constructor is
//! exposed here; authoritative stores retain their existing support boundaries.

#[cfg(windows)]
pub mod mechanism;
#[cfg(windows)]
mod namespace_acl;

#[cfg(windows)]
pub mod primary_owner;
#[cfg(windows)]
pub mod principal;
#[cfg(windows)]
pub mod security;
#[cfg(windows)]
pub mod volume;

#[cfg(windows)]
pub mod stage;
