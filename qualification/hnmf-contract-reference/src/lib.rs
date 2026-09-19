#![forbid(unsafe_code)]

//! Qualification shim for the canonical cognitive contract owner.
//!
//! Contract structure is intentionally NOT redefined in this package. The
//! single canonical Rust source is `codex-rs/hepta-cognitive-types`; this
//! qualification crate exists only to make the ownership boundary executable
//! and to fail if somebody tries to turn the reference package into a second
//! authority or contract spine.

pub const CANONICAL_CRATE_PATH: &str = "../../codex-rs/hepta-cognitive-types";
pub const CANONICAL_CONTRACT_MODULES: [&str; 3] = [
    "src/hnmf.rs",
    "src/hnmf_learning.rs",
    "src/wire.rs",
];

pub const CURRENT_RUN_MUTATION_ALLOWED: bool = false;
pub const ONLINE_TOPOLOGY_ACTIVATION_ALLOWED: bool = false;
pub const PRODUCTION_AUTHORITY: bool = false;
pub const EXTERNAL_EFFECTS_ALLOWED: bool = false;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn qualification_contract_reference_is_non_authoritative() {
        assert_eq!(
            [
                CURRENT_RUN_MUTATION_ALLOWED,
                ONLINE_TOPOLOGY_ACTIVATION_ALLOWED,
                PRODUCTION_AUTHORITY,
                EXTERNAL_EFFECTS_ALLOWED,
            ],
            [false; 4]
        );
        assert_eq!(CANONICAL_CONTRACT_MODULES.len(), 3);
        assert!(CANONICAL_CRATE_PATH.ends_with("hepta-cognitive-types"));
    }
}
