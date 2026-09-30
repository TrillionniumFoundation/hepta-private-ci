//! Stable Hepta surface consumed by Codex App Server.
//!
//! App Server must not bind individual Hepta owners. This crate is the single
//! dependency-inversion seam: owner implementations remain namespaced here and
//! can evolve without widening the App Server dependency graph.

#![forbid(unsafe_code)]

pub mod evidence {
    pub use codex_hepta_evidence::*;
}

pub mod governance {
    pub use codex_hepta_governance::*;
}

pub mod memory {
    pub use codex_hepta_memory::*;
}

pub mod memory_extension {
    pub use codex_hepta_memory_extension::*;
}

pub mod prompt_extension {
    pub use codex_hepta_prompt_extension::*;
}
