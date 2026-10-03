//! The original custody O executable with one finite parameter-admission purpose.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        use codex_hepta_agent_components::intelligence_eval as eval;
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 {
            let path = std::path::Path::new(&args[1]);
            if args[0] == "--parameter-admission" {
                return eval::run_fixed_parameter_observer_v1(path);
            }
            if args[0] == "--paired-admit" {
                return eval::admit_fixed_paired_custody(path);
            }
            if args[0] == "--paired-execute" {
                return eval::run_fixed_paired_custody(path);
            }
            if args[0] == "--paired-finish" {
                return eval::finish_fixed_paired_custody(path);
            }
        }
    }
    Err("usage: hepta-native-role-observer --parameter-admission ROOT_CONFIG | --paired-admit ROOT_TRUST_POLICY | --paired-execute ROOT_CONFIG | --paired-finish ROOT_CONFIG".into())
}
