// Keep the Rust async query-depth budget on the real codex crate root.
// main.rs is shared with the hepta CLI binary via include!.
#![recursion_limit = "256"]

include!("main.rs");
