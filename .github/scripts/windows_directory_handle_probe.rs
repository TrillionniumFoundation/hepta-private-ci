use std::fs::File;
use std::fs::OpenOptions;
use std::fs::{self};
use std::io::Write;
use std::io::{self};
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const BACKUP_SEMANTICS: u32 = 0x0200_0000;

fn json_string(value: &str) -> String {
    let mut encoded = String::from("\"");
    for character in value.chars() {
        match character {
            '\\' => encoded.push_str("\\\\"),
            '"' => encoded.push_str("\\\""),
            '\n' => encoded.push_str("\\n"),
            '\r' => encoded.push_str("\\r"),
            '\t' => encoded.push_str("\\t"),
            c if c < ' ' => encoded.push_str(&format!("\\u{:04x}", c as u32)),
            c => encoded.push(c),
        }
    }
    encoded.push('"');
    encoded
}

fn record<T>(case: &str, operation: &str, result: &io::Result<T>) -> bool {
    match result {
        Ok(_) => {
            println!(
                "{{\"case\":{},\"operation\":{},\"ok\":true}}",
                json_string(case),
                json_string(operation)
            );
            true
        }
        Err(error) => {
            let raw = error
                .raw_os_error()
                .map_or_else(|| "null".to_owned(), |code| code.to_string());
            println!("{{\"case\":{},\"operation\":{},\"ok\":false,\"raw_os_error\":{},\"kind\":{},\"message\":{}}}", json_string(case), json_string(operation), raw, json_string(&format!("{:?}", error.kind())), json_string(&error.to_string()));
            false
        }
    }
}

fn check_directory(case: &str, handle: &io::Result<File>) -> bool {
    let opened = record(case, "open", handle);
    let Ok(handle) = handle else { return false };
    let metadata = handle.metadata().and_then(|metadata| {
        if metadata.is_dir() {
            Ok(())
        } else {
            Err(io::Error::other("handle is not a directory"))
        }
    });
    let real_directory = record(case, "handle_is_directory", &metadata);
    // Every successfully opened directory is synced, including negative controls.
    let synced = record(case, "sync_all", &handle.sync_all());
    opened && real_directory && synced
}

fn write_file(root: &Path, name: &str) -> bool {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(root.join(name));
    let opened = record(name, "create_new", &file);
    let Ok(mut file) = file else { return false };
    let written = record(
        name,
        "write_all",
        &file.write_all(b"runner500 native durability probe\n"),
    );
    // A write failure is recorded but does not suppress the actual sync attempt.
    let synced = record(name, "sync_all", &file.sync_all());
    opened && written && synced
}

fn run() -> bool {
    let Some(runner_temp) = std::env::var_os("RUNNER_TEMP") else {
        record::<()>(
            "setup",
            "RUNNER_TEMP",
            &Err(io::Error::other("RUNNER_TEMP is required")),
        );
        return false;
    };
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    let root = Path::new(&runner_temp).join(format!(
        "runner500-directory-probe-{}-{}",
        std::process::id(),
        elapsed.as_nanos()
    ));
    if !record("setup", "create_directory", &fs::create_dir(&root)) {
        return false;
    }

    let ledger_written = write_file(&root, "ledger.bin");
    let witness_written = write_file(&root, "witness.bin");

    let original = File::open(&root);
    let _original_result = check_directory("original_read_no_flags", &original);
    let read_backup = OpenOptions::new()
        .read(true)
        .custom_flags(BACKUP_SEMANTICS)
        .open(&root);
    let _read_backup_result = check_directory("read_backup_semantics", &read_backup);

    // Both candidate directory handles remain live together through both syncs.
    let ledger_directory = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(BACKUP_SEMANTICS)
        .open(&root);
    let witness_directory = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(BACKUP_SEMANTICS)
        .open(&root);
    let ledger_synced = check_directory("candidate_ledger_directory", &ledger_directory);
    let witness_synced = check_directory("candidate_witness_directory", &witness_directory);
    drop((original, read_backup, ledger_directory, witness_directory));

    let cleaned = record(
        "setup",
        "remove_created_directory",
        &fs::remove_dir_all(&root),
    );
    let passed = ledger_written && witness_written && ledger_synced && witness_synced && cleaned;
    println!("{{\"summary\":true,\"os\":\"windows\",\"native_candidate_open_and_sync_passed\":{passed},\"ledger_file_synced\":{ledger_written},\"witness_file_synced\":{witness_written},\"ledger_directory_synced\":{ledger_synced},\"witness_directory_synced\":{witness_synced},\"cleanup_succeeded\":{cleaned}}}");
    passed
}

fn main() {
    if !run() {
        std::process::exit(1);
    }
}
