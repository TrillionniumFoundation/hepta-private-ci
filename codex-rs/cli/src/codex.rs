// `main.rs` is included by both binary entrypoints. Keep the crate-wide
// recursion limit at the entrypoint rather than inside that included file.
#![recursion_limit = "256"]

include!("main.rs");
