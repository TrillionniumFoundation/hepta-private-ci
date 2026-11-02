//! Research-only abrupt-exit hooks at actual native durability and READ boundaries.
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;

pub fn hit(
    stage: &str,
    snapshot: &Path,
    mode: &str,
    model_executions: u64,
    successful_opens: u64,
) -> Result<(), String> {
    if mode != "qualification"
        || std::env::var("HEPTA_JOINT_CRASH_AT").ok().as_deref() != Some(stage)
    {
        return Ok(());
    }
    let marker = crate::store::sibling(snapshot, ".fault.json");
    let bytes = serde_json::to_vec(&serde_json::json!({
        "stage": stage,
        "model_executions": model_executions,
        "successful_opens": successful_opens,
        "source_digest": env!("HEPTA_TASK_NATIVE_SOURCE_DIGEST"),
        "process_exit_code": 86
    }))
    .map_err(|e| e.to_string())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(marker)
        .map_err(|e| e.to_string())?;
    file.write_all(&bytes).map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    File::open(snapshot.parent().ok_or("snapshot parent required")?)
        .and_then(|directory| directory.sync_all())
        .map_err(|e| e.to_string())?;
    std::process::exit(86);
}
