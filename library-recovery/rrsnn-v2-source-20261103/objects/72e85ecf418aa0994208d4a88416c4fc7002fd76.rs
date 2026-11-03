//! CLI for bounded JSON transport and artifact verification, never inference.
use rrsnn_offline_replay_bridge::{Context, Envelope, Fixture, MAX_BYTES};
use serde::de::DeserializeOwned;
use std::{env, fs, path::Path};

fn read<T: DeserializeOwned>(path: &str) -> Result<T, String> {
    let metadata = fs::metadata(path).map_err(|e| e.to_string())?;
    if !metadata.is_file() || metadata.len() > (4 * MAX_BYTES) as u64 {
        return Err("not a regular bounded artifact".into());
    }
    serde_json::from_slice(&fs::read(path).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}

fn write(path: &str, value: &impl serde::Serialize) -> Result<(), String> {
    if let Some(parent) = Path::new(path).parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let data = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    fs::write(path, data).map_err(|e| e.to_string())
}

fn run() -> Result<(), String> {
    let args: Vec<_> = env::args().skip(1).collect();
    match args.as_slice() {
        [command, input] if command == "check" => {
            let fixture: Fixture = read(input)?;
            fixture.validate()?;
            println!("{{\"structuralChecksPassed\":true,\"components\":{},\"continuationEvents\":{},\"rustPhysicsExecuted\":false}}",
                     fixture.checkpoint_at_split.evidence.len(), fixture.expected_continuation_events.len());
            Ok(())
        }
        [command, input, output] if command == "roundtrip" => {
            let fixture: Fixture = read(input)?;
            fixture.validate()?;
            write(output, &fixture)
        }
        [command, input, context, output] if command == "pack" => {
            let fixture: Fixture = read(input)?;
            fixture.validate()?;
            let context: Context = read(context)?;
            if context.numpy_version != fixture.numpy_version { return Err("NumPy version binding mismatch".into()); }
            let envelope = Envelope::pack(fixture.checkpoint_at_split, context, fixture.continuation)?;
            write(output, &envelope)
        }
        [command, input, output] if command == "unpack" => {
            let envelope: Envelope = read(input)?;
            write(output, &envelope.unpack()?)
        }
        _ => Err("Usage: check FIXTURE | roundtrip FIXTURE OUTPUT | pack FIXTURE CONTEXT OUTPUT | unpack ENVELOPE OUTPUT".into()),
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("rejected: {error}");
        std::process::exit(2);
    }
}
