//! Existing-custody preflight, with no signing key or gold release operation.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 && args[0] == "--inspect" {
            return codex_hepta_intelligence_eval::inspect_fixed_product_evaluation(
                std::path::Path::new(&args[1]),
            );
        }
    }
    Err("usage: hepta-fixed-product-evaluation --inspect ROOT_CONFIG".into())
}
