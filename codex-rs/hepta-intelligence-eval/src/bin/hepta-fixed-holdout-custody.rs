//! Source-pinned Root gold custody. No arbitrary signing or gold-release API.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 {
            let config = std::path::Path::new(&args[1]);
            if args[0] == "--prepare" {
                return codex_hepta_intelligence_eval::prepare_fixed_source_holdout(config);
            }
            if args[0] == "--inspect" {
                return codex_hepta_intelligence_eval::inspect_fixed_source_holdout(config);
            }
            if args[0] == "--prepare-climate" {
                return codex_hepta_intelligence_eval::prepare_climate_source_holdout(config);
            }
            if args[0] == "--inspect-climate" {
                return codex_hepta_intelligence_eval::inspect_climate_source_holdout(config);
            }
            if args[0] == "--prepare-public-development" {
                return codex_hepta_intelligence_eval::prepare_public_development_custody(config);
            }
            if args[0] == "--inspect-public-development" {
                return codex_hepta_intelligence_eval::inspect_public_development_custody(config);
            }
            if args[0] == "--paired-execute" {
                return codex_hepta_intelligence_eval::run_fixed_paired_custody(config);
            }
            if args[0] == "--paired-finish" {
                return codex_hepta_intelligence_eval::finish_fixed_paired_custody(config);
            }
            if args[0] == "--paired-admit" {
                return codex_hepta_intelligence_eval::admit_fixed_paired_custody(config);
            }
        }
    }
    Err("usage: hepta-fixed-holdout-custody --prepare ROOT_CONFIG | --inspect ROOT_CONFIG | --prepare-climate ROOT_CONFIG | --inspect-climate ROOT_CONFIG | --prepare-public-development ROOT_CONFIG | --inspect-public-development ROOT_CONFIG | --paired-execute ROOT_CONFIG | --paired-finish ROOT_CONFIG | --paired-admit ROOT_TRUST_POLICY".into())
}
