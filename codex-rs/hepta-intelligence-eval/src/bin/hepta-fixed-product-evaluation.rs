//! Existing-custody preflight, with no signing key or gold release operation.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 && args[0] == "--run-calibration-cycle" {
            return codex_hepta_intelligence_eval::run_fixed_calibration_cycle(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 2 && args[0] == "--inspect" {
            return codex_hepta_intelligence_eval::inspect_fixed_product_evaluation(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 2 && args[0] == "--resume-calibration-evaluation" {
            return codex_hepta_intelligence_eval::resume_fixed_calibration_evaluation(
                std::path::Path::new(&args[1]),
            );
        }
    }
    Err("usage: hepta-fixed-product-evaluation --inspect ROOT_CONFIG | --run-calibration-cycle ROOT_CONFIG | --resume-calibration-evaluation ROOT_RESUME_CONFIG".into())
}
