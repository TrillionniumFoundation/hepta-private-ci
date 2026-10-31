//! Linux-only, explicitly unactivated research state-adoption executable.
#![forbid(unsafe_code)]
mod contract;
#[cfg(test)]
mod contract_tests;
mod engine;
mod native;
mod settlement;
mod store;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let run = || -> Result<serde_json::Value, String> {
        if !cfg!(target_os = "linux") {
            return Err("only the declared Linux research profile is supported".into());
        }
        let args: Vec<String> = std::env::args().skip(1).collect();
        if ![4, 8].contains(&args.len()) || args[0] != "--store" || args[2] != "--data-root" {
            return Err(
                "expected --store PATH --data-root PATH [--pause-at POINT --pause-marker PATH]"
                    .into(),
            );
        }
        let fault = if args.len() == 8 {
            if args[4] != "--pause-at"
                || args[6] != "--pause-marker"
                || ![
                    "locked",
                    "prepared",
                    "dispatched",
                    "native_committed",
                    "effect_entered",
                    "effect_completed",
                    "record_synced",
                    "published",
                ]
                .contains(&args[5].as_str())
            {
                return Err("unknown explicit fault probe".into());
            }
            store::Fault {
                point: args[5].clone(),
                marker: PathBuf::from(&args[7]),
            }
        } else {
            store::Fault::default()
        };
        let mut input = Vec::new();
        std::io::stdin()
            .take(65_537)
            .read_to_end(&mut input)
            .map_err(|e| e.to_string())?;
        if input.len() > 65_536 {
            return Err("request exceeds 64 KiB".into());
        }
        let request: contract::Request =
            serde_json::from_slice(&input).map_err(|e| e.to_string())?;
        let store = store::Store::open(Path::new(&args[1]))?;
        engine::execute(store, Path::new(&args[3]), request, &fault)
    };
    match run() {
        Ok(value) => {
            println!("{value}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            println!(
                "{}",
                serde_json::json!({"schema":contract::PROFILE,"status":"error","error":error,"authority":"DENY_ALL","production_activation":false})
            );
            ExitCode::FAILURE
        }
    }
}
