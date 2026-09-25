//! Compatibility exports. Lease and witness lifecycle rules are owned by the
//! memory extension, not the App Server execution spine. No authority changes.

pub use codex_hepta_memory_extension::HEPTA_LOCAL_LIFECYCLE_OWNER_EXTERNAL_EFFECTS;
pub use codex_hepta_memory_extension::HEPTA_LOCAL_LIFECYCLE_OWNER_KG_WRITE_AUTHORITY;
pub use codex_hepta_memory_extension::HEPTA_LOCAL_LIFECYCLE_OWNER_PRODUCTION_CALLER;
pub use codex_hepta_memory_extension::HEPTA_LOCAL_LIFECYCLE_OWNER_RUNTIME_REGISTERED;
pub use codex_hepta_memory_extension::HeptaLocalDevelopmentLifecycleOwner;
pub use codex_hepta_memory_extension::HeptaLocalDevelopmentLifecycleOwnerError;
