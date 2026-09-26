// This fixture must not compile. The raw signed decision primitives are
// intentionally crate-private; external consumers must use a sealed admission or
// the canonical product runner.
use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;
use codex_hepta_intelligence_eval::decide_with_signed_longitudinal_evidence_v3;

fn main() {
    let _ = decide_with_signed_evidence_v2;
    let _ = decide_with_signed_longitudinal_evidence_v3;
}
