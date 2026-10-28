// The shared main.rs is included by both CLI entrypoints.
// Keep the Rust 1.96 query-depth budget on this crate root.
#![recursion_limit = "256"]

include!("main.rs");
