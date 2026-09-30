#![forbid(unsafe_code)]

use std::fs;
use std::fs::File;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error;
use codex_hepta_infer_core::durable_control::native::NativeMaintenanceFailpoint;
use codex_hepta_infer_core::durable_control::native::NativeMaintenanceStage;

struct KillBoundary {
    target: NativeMaintenanceStage,
    marker: PathBuf,
}

impl NativeMaintenanceFailpoint for KillBoundary {
    fn hit(&mut self, stage: NativeMaintenanceStage) -> Result<(), Error> {
        if stage == self.target {
            fs::write(&self.marker, format!("{stage:?}\n"))?;
            File::open(&self.marker)?.sync_all()?;
            if let Some(parent) = self.marker.parent() {
                File::open(parent)?.sync_all()?;
            }
            loop {
                thread::sleep(Duration::from_secs(60));
            }
        }
        Ok(())
    }
}

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut args = std::env::args().skip(1);
    let journal = PathBuf::from(args.next().ok_or("missing journal")?);
    let marker = PathBuf::from(args.next().ok_or("missing marker")?);
    let stage = parse_stage(&args.next().ok_or("missing stage")?)?;
    if args.next().is_some() || !journal.is_absolute() || !marker.is_absolute() {
        return Err(
            "journal and marker must be absolute and no extra arguments are allowed".into(),
        );
    }
    let mut control = DurableInferenceControl::open(journal, 8)?;
    control.compact_native_journal_with_failpoint(
        2_000_000,
        &mut KillBoundary {
            target: stage,
            marker,
        },
    )?;
    Err("fault child reached the end without being killed".into())
}

fn parse_stage(value: &str) -> Result<NativeMaintenanceStage, &'static str> {
    match value {
        "before-archive-write" => Ok(NativeMaintenanceStage::BeforeArchiveWrite),
        "after-archive-sync" => Ok(NativeMaintenanceStage::AfterArchiveSync),
        "before-checkpoint-write" => Ok(NativeMaintenanceStage::BeforeCheckpointWrite),
        "after-checkpoint-sync" => Ok(NativeMaintenanceStage::AfterCheckpointSync),
        "before-generation-write" => Ok(NativeMaintenanceStage::BeforeGenerationWrite),
        "after-generation-sync" => Ok(NativeMaintenanceStage::AfterGenerationSync),
        "after-generation-rename" => Ok(NativeMaintenanceStage::AfterGenerationRename),
        "after-parent-sync" => Ok(NativeMaintenanceStage::AfterParentSync),
        _ => Err("unknown maintenance stage"),
    }
}
