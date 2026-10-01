use std::error::Error;
use std::io::Write;
use std::path::Path;

use codex_hepta_control_plane::PlannerStoreConfigV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreFailpointV1;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_types::Digest32;

const CRASH_ENVELOPE: &[u8] = b"planner-store-process-synced-record-v1";

fn main() -> Result<(), Box<dyn Error>> {
    let mut arguments = std::env::args_os().skip(1);
    let mode = arguments.next().ok_or("missing fixture mode")?;
    let root = arguments.next().ok_or("missing planner store root")?;
    if arguments.next().is_some() {
        return Err("unexpected fixture argument".into());
    }

    match mode.to_str() {
        Some("hold") => hold(Path::new(&root)),
        Some("crash-after-sync") => crash_after_sync(Path::new(&root)),
        _ => Err("unknown fixture mode".into()),
    }
}

fn hold(root: &Path) -> Result<(), Box<dyn Error>> {
    let _store = PlannerStoreV1::open(root, PlannerStoreConfigV1::default())?;
    println!("READY");
    std::io::stdout().flush()?;
    loop {
        std::thread::park();
    }
}

fn crash_after_sync(root: &Path) -> Result<(), Box<dyn Error>> {
    let mut store = PlannerStoreV1::open(root, PlannerStoreConfigV1::default())?;
    store.set_failpoint(Some(PlannerStoreFailpointV1::AfterLogSyncBeforePublish));
    let result = store.append(
        PlannerStoreRecordKindV1::Decision,
        Digest32::of_bytes(b"planner-store-process-operation-v1"),
        Digest32::of_bytes(b"planner-store-process-payload-v1"),
        CRASH_ENVELOPE,
    );
    if !matches!(
        result,
        Err(PlannerStoreError::Failpoint(
            PlannerStoreFailpointV1::AfterLogSyncBeforePublish
        ))
    ) {
        return Err("fixture did not reach the post-sync failure boundary".into());
    }
    std::process::abort();
}
