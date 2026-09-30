//! Compatibility surface for the durable Matrix dispatch observer.
//!
//! Send truth is owned by `MatrixDurableStore`. This module deliberately
//! contains no in-memory ledger and must never become a second sender.

pub use codex_hepta_matrix_store::MAX_UNRESOLVED_MATRIX_DISPATCHES;
pub use codex_hepta_matrix_store::MatrixDispatchAuthority;
pub use codex_hepta_matrix_store::MatrixDispatchRecord;
pub use codex_hepta_matrix_store::MatrixDispatchState;
