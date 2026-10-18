//! Existing-custody preflight and the separately deployed unprivileged G entry.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 && args[0] == "--public-development-measure" {
            return codex_hepta_intelligence_eval::run_fixed_public_development_measurement(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 2 && args[0] == "--paired-preregister" {
            return codex_hepta_intelligence_eval::run_fixed_paired_generator(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 4 && args[0] == "--inspect-rejected-cycle" {
            let historical =
                codex_hepta_intelligence_eval::inspect_completed_calibration_rejection(
                    std::path::Path::new(&args[1]),
                    args[2].to_str().ok_or("config digest")?.parse()?,
                    args[3].to_str().ok_or("completion digest")?.parse()?,
                )?;
            println!("{}", serde_json::to_string(&historical)?);
            return Ok(());
        }
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
    Err("usage: hepta-fixed-product-evaluation --inspect ROOT_CONFIG | --paired-preregister ROOT_G_CONFIG | --public-development-measure ROOT_PUBLIC_CONFIG | --run-calibration-cycle ROOT_CONFIG | --resume-calibration-evaluation ROOT_RESUME_CONFIG | --inspect-rejected-cycle ROOT_CONFIG CONFIG_DIGEST COMPLETION_DIGEST".into())
}
