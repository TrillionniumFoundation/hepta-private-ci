//! Fixed independent evaluator; never accepts arbitrary metrics or sign payloads.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 && args[0] == "--request" {
            return codex_hepta_intelligence_eval::run_fixed_calibration_evaluator(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 6
            && args[0] == "--initialize-key"
            && args[2] == "--uid"
            && args[4] == "--gid"
        {
            return codex_hepta_intelligence_eval::initialize_fixed_evaluator_key(
                std::path::Path::new(&args[1]),
                args[3].to_str().ok_or("uid")?.parse()?,
                args[5].to_str().ok_or("gid")?.parse()?,
            );
        }
        Err("usage: hepta-fixed-calibration-evaluator --request ROOT_CONFIG | --initialize-key PRIVATE_KEY --uid UID --gid GID".into())
    }
    #[cfg(not(target_os = "linux"))]
    Err("fixed evaluation requires Linux".into())
}
