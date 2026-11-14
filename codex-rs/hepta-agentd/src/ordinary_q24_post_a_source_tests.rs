//! The independently identified source child uses the actual product ingress.

#[test]
#[ignore = "only the ordinary parent supplies original inherited descriptors and independent credentials"]
fn original_independent_b_source_child() -> anyhow::Result<()> {
    super::source_keeper::run_original_source(super::b_evaluate::produce)
}
