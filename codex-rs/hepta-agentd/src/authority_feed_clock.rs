//! Agentd compatibility name for the canonical signed-feed admission clock.
//!
//! The implementation and its failure-closed window semantics live in
//! `hepta-contracts::FinalUseFeedClock`, so compatibility and production
//! compositions cannot drift into different clock types.

pub(super) use codex_hepta_contracts::FinalUseFeedClock;
