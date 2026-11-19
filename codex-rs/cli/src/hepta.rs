#![recursion_limit = "256"]

// Include the shared CLI implementation directly. Including main.rs here would
// nest codex's crate-level recursion_limit inside an include! expansion.
include!("main_impl.rs");

#[cfg(test)]
mod entrypoint_root_regression_tests {
    #[test]
    fn hepta_and_codex_are_separate_crate_roots_with_direct_shared_implementation() {
        let hepta_root = include_str!("hepta.rs");
        let codex_root = include_str!("main.rs");
        assert!(hepta_root.starts_with("#![recursion_limit = \"256\"]"));
        assert!(codex_root.starts_with("#![recursion_limit = \"256\"]"));
        assert!(hepta_root.contains("include!(\"main_impl.rs\");"));
        assert!(codex_root.contains("include!(\"main_impl.rs\");"));
    }
}
