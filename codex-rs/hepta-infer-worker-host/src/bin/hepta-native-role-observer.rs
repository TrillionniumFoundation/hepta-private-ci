//! The original custody O executable with one finite parameter-admission purpose.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        use codex_hepta_agent_components::intelligence_eval as eval;
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 3
            && (args[0] == "--canary-observation" || args[0] == "--registered-canary-observation")
        {
            let pin = args[2]
                .to_str()
                .ok_or("canary configuration pin encoding")?
                .parse()?;
            let result = if args[0] == "--registered-canary-observation" {
                codex_hepta_infer_worker_host::initial_cpu_anchor::observe_registered_cpu_self_iteration_canary_v1(std::path::Path::new(&args[1]), pin)?
            } else {
                codex_hepta_infer_worker_host::initial_cpu_anchor::observe_cpu_self_iteration_canary_root(std::path::Path::new(&args[1]), pin)?
            };
            println!("{}", serde_json::to_string(&result)?);
            return Ok(());
        }
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
    Err("usage: hepta-native-role-observer --parameter-admission ROOT_CONFIG | --paired-admit ROOT_TRUST_POLICY | --paired-execute ROOT_CONFIG | --paired-finish ROOT_CONFIG | --canary-observation ROOT_CONFIG SHA256 | --registered-canary-observation ROOT_CONFIG SHA256".into())
}
