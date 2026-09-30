//! External-crate proof that the product-facing surface exposes controlled APIs.

use codex_hepta_memory_retrieval::RecallWorkControlV1;
use codex_hepta_memory_retrieval::recall_generated_with_engram_controlled;
use codex_hepta_memory_retrieval::recall_with_engram_controlled;
use codex_hepta_memory_retrieval::settle_engram_controlled;

#[test]
fn external_surface_exposes_controlled_recall() {
    let _ = RecallWorkControlV1::bounded;
    let _ = recall_generated_with_engram_controlled;
    let _ = recall_with_engram_controlled;
    let _ = settle_engram_controlled;
}

#[cfg(feature = "legacy-uncontrolled-retrieval")]
#[test]
fn explicit_migration_feature_exposes_legacy_helpers() {
    let _ = codex_hepta_memory_retrieval::recall;
    let _ = codex_hepta_memory_retrieval::recall_generated;
    let _ = codex_hepta_memory_retrieval::recall_generated_with_engram;
    let _ = codex_hepta_memory_retrieval::recall_with_engram;
    let _ = codex_hepta_memory_retrieval::settle_engram;
}
