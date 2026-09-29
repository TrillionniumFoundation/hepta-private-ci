use std::path::PathBuf;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_worker_host::NativeJournalWriterActor;
use codex_hepta_infer_worker_host::NativeWriterLimits;

const JOURNAL_CAPACITY: usize = 16_384;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Operation {
    Status,
    Compact,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
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
    let mut writer_limits = NativeWriterLimits::default();
    while let Some(flag) = args.next() {
        if flag == "--help" {
            print_help();
            return Ok(());
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--writer-ordinary-capacity" => {
                writer_limits.ordinary_queue_capacity = value.parse()?
            }
            "--writer-terminal-capacity" => {
                writer_limits.terminal_queue_capacity = value.parse()?
            }
            "--writer-reply-timeout-ms" => {
                writer_limits.reply_timeout = Duration::from_millis(value.parse()?)
            }
            "--writer-shutdown-timeout-ms" => {
                writer_limits.shutdown_timeout = Duration::from_millis(value.parse()?)
            }
            "--journal" => journal = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }
    let journal = journal.ok_or("--journal is required")?;
    if !journal.is_absolute() {
        return Err("--journal must be absolute".into());
    }

    let actor =
        NativeJournalWriterActor::spawn_with_limits(journal, JOURNAL_CAPACITY, writer_limits)?;
    let control = actor.handle();
    let operation_result: Result<String, Box<dyn std::error::Error + Send + Sync>> = async {
        match operation {
            Operation::Status => Ok(serde_json::to_string_pretty(
                &control.metrics(unix_time_ms()?).await?,
            )?),
            Operation::Compact => Ok(serde_json::to_string_pretty(&control.compact().await?)?),
        }
    }
    .await;
    drop(control);
    let shutdown_result = actor.shutdown().await;
    let output = operation_result?;
    shutdown_result?;
    println!("{output}");
    Ok(())
}

fn print_help() {
    println!(
        "hepta-infer-maintenance <status|compact> --journal ABSOLUTE_PATH [--writer-ordinary-capacity N --writer-terminal-capacity N --writer-reply-timeout-ms N --writer-shutdown-timeout-ms N]\n\n`status` emits bounded operational metrics. `compact` installs one crash-safe content-addressed checkpoint generation and emits the archive/checkpoint digests plus any expired encrypted references that must be deleted by the output vault. This tool has no release or force-retirement operation."
    );
}

fn unix_time_ms() -> Result<u64, Box<dyn std::error::Error + Send + Sync>> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}
