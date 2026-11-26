//! Executable runtime.codex crash, concurrency and restart qualification.
//!
//! The closed-world 22-cut model and the high-contention stress model are kept
//! in support modules so this one named integration target is a closed-world
//! receipt item.

#[path = "support/runtime_codex_crash_model.rs"]
mod closed_world;

#[path = "support/runtime_codex_fence_stress.rs"]
mod high_contention;
