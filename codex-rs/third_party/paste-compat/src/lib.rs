//! Repository-owned compatibility facade for the three public `paste` macros.
//!
//! All expansion is performed by maintained `pastey`; none of the archived
//! `paste` implementation is retained here. Keeping the public dependency name
//! lets Starlark and V8 keep their existing macro paths and native ABI.

pub use pastey::expr;
pub use pastey::item;
pub use pastey::paste;
