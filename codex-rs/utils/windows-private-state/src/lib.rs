//! Windows mechanisms and bounded create-only private-directory provisioning.
//!
//! Primitive observations do not establish namespace authority. Fresh-directory
//! creation requires live primary-owner and actual bounded ancestry checks; it
//! provides no legacy adoption, journal recovery, sandbox or power-loss
//! qualification. Authoritative stores retain their existing support boundaries.

#[cfg(windows)]
pub mod mechanism;
#[cfg(windows)]
mod namespace_acl;
#[cfg(windows)]
pub mod parent_anchor;

#[cfg(windows)]
pub mod primary_owner;
#[cfg(windows)]
pub mod principal;
#[cfg(windows)]
mod protected_descriptor;
#[cfg(windows)]
pub mod security;
#[cfg(windows)]
pub mod volume;

#[cfg(windows)]
pub mod stage;
