use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;

const JOURNAL_CAPACITY: usize = 16_384;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Operation {
    Status,
    Compact,
}

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut args = std::env::args().skip(1);
    let operation = match args.next().as_deref() {
        Some("status") => Operation::Status,
        Some("compact") => Operation::Compact,
        Some("--help") | None => {
            print_help();
            return Ok(());
        }
        Some(value) => return Err(format!("unsupported maintenance operation: {value}").into()),
    };
    let mut journal = None;
    while let Some(flag) = args.next() {
        if flag == "--help" {
            print_help();
            return Ok(());
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--journal" => journal = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }
    let mut control = DurableInferenceControl::open(journal, JOURNAL_CAPACITY)?;
    match operation {
        Operation::Status => {
            println!(
                "{}",
                serde_json::to_string_pretty(&control.native_metrics(unix_time_ms()?))?
            );
        }
        Operation::Compact => {
            let receipt = control.compact_native_journal()?;
            println!("{}", serde_json::to_string_pretty(&receipt)?);
        }
    }
    Ok(())
}

fn print_help() {
    println!(
        "hepta-infer-maintenance <status|compact> --journal ABSOLUTE_PATH\n\n`status` emits bounded operational metrics. `compact` installs one crash-safe content-addressed checkpoint generation and emits the archive/checkpoint digests plus any expired encrypted references that must be deleted by the output vault. This tool has no release or force-retirement operation."
    );
}

fn unix_time_ms() -> Result<u64, Box<dyn std::error::Error + Send + Sync>> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}
