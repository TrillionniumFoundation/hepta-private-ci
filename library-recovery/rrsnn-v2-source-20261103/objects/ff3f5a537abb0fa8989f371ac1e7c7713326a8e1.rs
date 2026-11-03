use std::env;
use std::fs;
use std::io::Read;
use std::process::ExitCode;

use rrsnn_hepta_type_adapter::FeatureRequest;
use rrsnn_hepta_type_adapter::MAX_INPUT_BYTES;
use rrsnn_hepta_type_adapter::prepare_shadow_input;

fn run() -> Result<(), String> {
    let arguments: Vec<String> = env::args().collect();
    let [_, input, output] = arguments.as_slice() else {
        return Err("usage: rrsnn-hepta-type-adapter REQUEST.json OUTPUT.json".into());
    };
    if input == output {
        return Err("input and output must be separate files".into());
    }
    let mut raw = Vec::new();
    fs::File::open(input)
        .map_err(|e| e.to_string())?
        .take((MAX_INPUT_BYTES + 1) as u64)
        .read_to_end(&mut raw)
        .map_err(|e| e.to_string())?;
    if raw.len() > MAX_INPUT_BYTES {
        return Err("input exceeded the offline byte cap".into());
    }
    let request: FeatureRequest = serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    let value = prepare_shadow_input(&request)?;
    fs::write(
        output,
        serde_json::to_vec_pretty(&value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    println!("validated upstream types and wrote an offline shadow input; owner_executed=false");
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("rejected: {error}");
            ExitCode::from(2)
        }
    }
}
