//! External-crate proof that the default product-facing surface is controlled.

#[cfg(feature = "legacy-uncontrolled-retrieval")]
compile_error!("default qualification must not enable legacy-uncontrolled-retrieval");

use codex_hepta_memory_retrieval::RecallWorkControlV1;
use codex_hepta_memory_retrieval::recall_generated_with_engram_controlled;
use codex_hepta_memory_retrieval::recall_with_engram_controlled;
use codex_hepta_memory_retrieval::settle_engram_controlled;

#[test]
fn default_external_surface_exposes_controlled_recall_only() {
    let _ = RecallWorkControlV1::bounded;
    let _ = recall_generated_with_engram_controlled;
    let _ = recall_with_engram_controlled;
    let _ = settle_engram_controlled;
}
