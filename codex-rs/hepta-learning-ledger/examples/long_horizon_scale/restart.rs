//! Fresh-process counterpart of the existing real-file scale measurement.
//!
//! Checkpoints come from the parent, not an independently retained witness.
//! The child has a fresh address space but shares the warm filesystem cache.

use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::LongHorizonLedgerCheckpointV1;
use codex_hepta_learning_ledger::LongHorizonSegmentedLedgerV1;
use codex_hepta_types::Digest32;

use super::CACHE_ENTRIES;
use super::SEGMENT_BYTES;
use super::SEGMENT_RECORDS;
use super::checked;
use super::decision;
use super::file;
use super::id;
use super::linux_memory_kib;
use super::segment;

const MODE: &str = "--recover-checkpoint";
const DEADLINE: Duration = Duration::from_secs(30);

pub fn measure(root: &Path, checkpoint: LongHorizonLedgerCheckpointV1) -> io::Result<()> {
    let mut child = Command::new(std::env::current_exe()?)
        .arg(MODE)
        .arg(root)
        .arg(checkpoint.active_segment.to_string())
        .arg(checkpoint.archived_anchor.sequence.to_string())
        .arg(checkpoint.archived_anchor.chain_digest.to_string())
        .arg(checkpoint.head_anchor.sequence.to_string())
        .arg(checkpoint.head_anchor.chain_digest.to_string())
        .arg(checkpoint.sealed.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()?;
    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return if status.success() {
                    Ok(())
                } else {
                    Err(io::Error::other(format!(
                        "fresh-process recovery failed: {status}"
                    )))
                };
            }
            Ok(None) if start.elapsed() < DEADLINE => {
                thread::sleep(Duration::from_millis(2));
            }
            outcome => {
                // This is a reviewed single-process probe, not an arbitrary
                // candidate sandbox. Always reap it before returning failure.
                let _ = child.kill();
                let _ = child.wait();
                return match outcome {
                    Err(error) => Err(error),
                    _ => Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        "fresh-process recovery exceeded 30 seconds",
                    )),
                };
            }
        }
    }
}

fn text(value: &OsStr) -> io::Result<&str> {
    let value = value
        .to_str()
        .ok_or_else(|| io::Error::other("checkpoint argument is not UTF-8"))?;
    if value.len() > 64 {
        return Err(io::Error::other("checkpoint argument exceeds bound"));
    }
    Ok(value)
}

pub fn run_if_requested(args: &[OsString]) -> io::Result<bool> {
    if args.first().and_then(|arg| arg.to_str()) != Some(MODE) {
        return Ok(false);
    }
    if args.len() != 8 {
        let message = "invalid fresh-process checkpoint arguments";
        return Err(io::Error::other(message));
    }
    let root = PathBuf::from(&args[1]);
    let checkpoint = LongHorizonLedgerCheckpointV1 {
        active_segment: checked(text(&args[2])?.parse())?,
        archived_anchor: LedgerAnchor {
            sequence: checked(text(&args[3])?.parse())?,
            chain_digest: checked(text(&args[4])?.parse())?,
        },
        head_anchor: LedgerAnchor {
            sequence: checked(text(&args[5])?.parse())?,
            chain_digest: checked(text(&args[6])?.parse())?,
        },
        sealed: checked(text(&args[7])?.parse())?,
    };
    if !(100..=1_000_000).contains(&checkpoint.head_anchor.sequence)
        || checkpoint.active_segment > 1_000_000 / SEGMENT_RECORDS
    {
        return Err(io::Error::other("checkpoint exceeds measurement bounds"));
    }
    let rss_before = linux_memory_kib("VmRSS");
    let start = Instant::now();
    let mut ledger = checked(LongHorizonSegmentedLedgerV1::recover(
        file(&root.join("owner.lock"), false)?,
        file(&segment(&root, checkpoint.active_segment), false)?,
        root.join("index"),
        Digest32::of_bytes(b"hepta.long-horizon-scale.v1"),
        LedgerSegmentLimits {
            records: SEGMENT_RECORDS,
            bytes: SEGMENT_BYTES,
        },
        CACHE_ENTRIES,
        checkpoint,
    ))?;
    let recover_ns = start.elapsed().as_nanos();
    if checked(ledger.checkpoint())? != checkpoint {
        return Err(io::Error::other("fresh process changed the checkpoint"));
    }
    let expected = decision(0)?;
    let first = id("record-0")?;
    if checked(ledger.archive_segment_for_record(&first))? != Some(0) {
        return Err(io::Error::other("fresh process lost the archive location"));
    }
    let oldest = checked(ledger.archived_record(File::open(segment(&root, 0))?, &first))?
        .ok_or_else(|| io::Error::other("fresh process lost the oldest record"))?;
    if oldest.event != expected {
        return Err(io::Error::other("fresh process changed archive content"));
    }
    let replay = checked(ledger.append(Digest32::ZERO, expected))?;
    let metrics = checked(ledger.metrics())?;
    if replay.disposition != AppendDisposition::IdempotentReplay
        || checked(ledger.checkpoint())? != checkpoint
        || metrics.retained_payload_records > SEGMENT_RECORDS
        || metrics.historical_cache_entries > CACHE_ENTRIES
    {
        return Err(io::Error::other(
            "fresh process violated retry identity or resident bounds",
        ));
    }
    println!(
        "{{\"schema\":\"hepta.long-horizon-restart.v1\",\"records\":{},\"pid\":{},\"recover_ns\":{recover_ns},\"resident_records\":{},\"historical_cache_entries\":{},\"record_limit\":{SEGMENT_RECORDS},\"cache_limit\":{CACHE_ENTRIES},\"rss_before_recovery_kib\":{rss_before},\"rss_after_recovery_and_retry_kib\":{},\"peak_rss_kib\":{},\"fresh_process\":true,\"filesystem_cache_cold\":false,\"checkpoint_source\":\"parent\",\"power_loss_tested\":false,\"independent_witness_retention\":false}}",
        checkpoint.head_anchor.sequence,
        std::process::id(),
        metrics.retained_payload_records,
        metrics.historical_cache_entries,
        linux_memory_kib("VmRSS"),
        linux_memory_kib("VmHWM"),
    );
    Ok(true)
}
