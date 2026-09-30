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
        }
    }
    Err("usage: hepta-fixed-holdout-custody --prepare ROOT_CONFIG | --inspect ROOT_CONFIG".into())
}
