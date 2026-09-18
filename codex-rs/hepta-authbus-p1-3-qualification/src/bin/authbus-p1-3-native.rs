use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_authbus_p1_3_qualification::ExecutionProvenance;
use codex_hepta_authbus_p1_3_qualification::execute_native_negative_qualification;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = env::args().collect::<Vec<_>>();
    if args.len() != 5 {
        return Err("usage: authbus-p1-3-native <source-sha> <source-tree> <runner-id> <receipt-path>".into());
    }
    let source_sha = args[1].clone();
    let source_tree = args[2].clone();
    let runner_id = StableId::new(&args[3])?;
    let output = std::path::PathBuf::from(&args[4]);
    let executable = env::current_exe()?;
    let executable_digest = Digest32::of_bytes(&fs::read(&executable)?);
    let mut command_bytes = b"authbus-p1-3-native.v1\0".to_vec();
    for value in &args[1..4] {
        command_bytes
            .extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
        command_bytes.extend_from_slice(value.as_bytes());
    }
    let command_digest = Digest32::of_bytes(&command_bytes);
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let provenance = ExecutionProvenance {
        source_sha,
        source_tree,
        executable_digest,
        command_digest,
        runner_id,
        started_at_ms: now,
        completed_at_ms: now,
        exit_code: 0,
    };
    let receipt = execute_native_negative_qualification(provenance)?;
    let mut stream = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output)?;
    writeln!(
        stream,
        "{{\"schema_version\":1,\"source_sha\":\"{}\",\"source_tree\":\"{}\",\"executable_digest\":\"{}\",\"command_digest\":\"{}\",\"runner_id\":\"{}\",\"case_count\":{},\"qualification_digest\":\"{}\",\"authority\":false}}",
        receipt.source_sha,
        receipt.source_tree,
        receipt.executable_digest,
        receipt.command_digest,
        receipt.runner_id,
        receipt.case_count,
        receipt.qualification_digest,
    )?;
    stream.sync_all()?;
    Ok(())
}
