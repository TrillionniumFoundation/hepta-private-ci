//! Real-file long-horizon measurements with a fixed active tail and cache.
//!
//! Usage: long_horizon_scale <records: 100..=1000000> <new-output-directory>
//! Rows are observations, not thresholds or a scalability certificate. Each
//! milestone measures a fresh-process recovery and a same-process reopen. The
//! filesystem cache remains warm, and the parent supplies the checkpoint. This
//! is not power-loss recovery or independent witness retention. The supplied
//! output directory is created, never replaced.

use std::fmt::Debug;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::hint::black_box;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::LongHorizonSegmentedLedgerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

#[path = "long_horizon_scale/restart.rs"]
mod restart;

const SEGMENT_RECORDS: usize = 64;
const SEGMENT_BYTES: u64 = 128 * 1024;
const CACHE_ENTRIES: usize = 256;

fn checked<T, E: Debug>(value: Result<T, E>) -> io::Result<T> {
    value.map_err(|error| io::Error::other(format!("{error:?}")))
}

fn id(value: &str) -> io::Result<StableId> {
    checked(StableId::new(value))
}

fn decision(index: usize) -> io::Result<LedgerEvent> {
    Ok(LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("record-{index}"))?,
        episode_id: id(&format!("episode-{index}"))?,
        objective_digest: Digest32::of_bytes(b"long-horizon-scale-objective"),
        policy_id: id("scale-policy")?,
        candidate_ids: vec![id("abstain")?, id("choose")?],
        selected_candidate_id: id("choose")?,
        selected_propensity: checked(ProbabilityQ32::from_raw(1_u64 << 31))?,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"scale-support"),
    }))
}

fn file(path: &Path, create: bool) -> io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .open(path)
}

fn segment(root: &Path, index: usize) -> PathBuf {
    root.join(format!("segment-{index:016x}"))
}

fn linux_memory_kib(field: &str) -> String {
    fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|text| {
            text.lines().find_map(|line| {
                let (key, value) = line.split_once(':')?;
                (key == field)
                    .then(|| value.split_whitespace().next()?.parse::<u64>().ok())
                    .flatten()
            })
        })
        .map_or_else(|| "null".to_owned(), |value| value.to_string())
}

fn main() -> io::Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if restart::run_if_requested(&args)? {
        return Ok(());
    }
    if args.len() != 2 {
        return Err(io::Error::other(
            "usage: long_horizon_scale <records: 100..=1000000> <new-output-directory>",
        ));
    }
    let count: usize = checked(
        args[0]
            .to_str()
            .ok_or_else(|| io::Error::other("record count is not UTF-8"))?
            .parse(),
    )?;
    if !(100..=1_000_000).contains(&count) {
        return Err(io::Error::other("records must be in 100..=1000000"));
    }
    let root = PathBuf::from(&args[1]);
    fs::create_dir(&root)?;
    let binding = Digest32::of_bytes(b"hepta.long-horizon-scale.v1");
    let limits = LedgerSegmentLimits {
        records: SEGMENT_RECORDS,
        bytes: SEGMENT_BYTES,
    };
    let owner_path = root.join("owner.lock");
    let index_root = root.join("index");
    let mut ledger = checked(LongHorizonSegmentedLedgerV1::create(
        file(&owner_path, true)?,
        file(&segment(&root, 0), true)?,
        &index_root,
        binding,
        limits,
        CACHE_ENTRIES,
    ))?;
    let mut milestones = vec![100, 1_000, 10_000, 100_000, count];
    milestones.retain(|size| *size <= count);
    milestones.sort_unstable();
    milestones.dedup();
    let mut previous = 0;
    for size in milestones {
        let start = Instant::now();
        for index in previous..size {
            if index != 0 && index % SEGMENT_RECORDS == 0 {
                checked(ledger.rotate(
                    file(&segment(&root, index / SEGMENT_RECORDS), true)?,
                    ledger.head_anchor(),
                ))?;
            }
            let receipt =
                checked(ledger.append(ledger.head_anchor().chain_digest, decision(index)?))?;
            if receipt.disposition != AppendDisposition::Appended {
                return Err(io::Error::other("new record was not appended"));
            }
        }
        let append_ns = start.elapsed().as_nanos();
        let checkpoint = checked(ledger.checkpoint())?;
        if checkpoint.head_anchor.sequence != size as u64 {
            return Err(io::Error::other("history count mismatch"));
        }
        let rss_before_reopen = linux_memory_kib("VmRSS");
        drop(ledger);
        restart::measure(&root, checkpoint)?;
        let start = Instant::now();
        ledger = checked(LongHorizonSegmentedLedgerV1::recover(
            file(&owner_path, false)?,
            file(&segment(&root, checkpoint.active_segment), false)?,
            &index_root,
            binding,
            limits,
            CACHE_ENTRIES,
            checkpoint,
        ))?;
        let warm_reopen_ns = start.elapsed().as_nanos();
        if checked(ledger.checkpoint())? != checkpoint {
            return Err(io::Error::other("reopen changed the acknowledged checkpoint"));
        }
        let retry = decision(0)?;
        let start = Instant::now();
        for _ in 0..1000 {
            let receipt = checked(ledger.append(Digest32::ZERO, retry.clone()))?;
            if receipt.disposition != AppendDisposition::IdempotentReplay {
                return Err(io::Error::other("historical retry appended duplicate history"));
            }
            black_box(receipt);
        }
        let retry_ns = start.elapsed().as_nanos();
        let metrics = checked(ledger.metrics())?;
        if metrics.retained_payload_records > SEGMENT_RECORDS
            || metrics.historical_cache_entries > CACHE_ENTRIES
            || ledger.head_anchor() != checkpoint.head_anchor
        {
            return Err(io::Error::other("resident bounds or retry identity changed"));
        }
        let first = id("record-0")?;
        if checked(ledger.archive_segment_for_record(&first))? != Some(0) {
            return Err(io::Error::other("oldest record lost its archive location"));
        }
        let archived = checked(ledger.archived_record(File::open(segment(&root, 0))?, &first))?
            .ok_or_else(|| io::Error::other("oldest archived record is missing"))?;
        if archived.event != retry {
            return Err(io::Error::other("archive returned different record content"));
        }
        println!(
            "{{\"schema\":\"hepta.long-horizon-scale.v1\",\"records\":{size},\"appended_since_previous\":{},\"append_ns\":{append_ns},\"warm_reopen_ns\":{warm_reopen_ns},\"retry_1000_ns\":{retry_ns},\"active_segment\":{},\"active_segment_bytes\":{},\"resident_records\":{},\"historical_cache_entries\":{},\"record_limit\":{SEGMENT_RECORDS},\"cache_limit\":{CACHE_ENTRIES},\"rss_before_reopen_kib\":{rss_before_reopen},\"rss_after_reopen_and_retry_kib\":{},\"peak_rss_kib\":{},\"persistence_measured\":true,\"power_loss_tested\":false,\"independent_witness_retention\":false}}",
            size - previous,
            metrics.active_segment,
            metrics.active_segment_bytes,
            metrics.retained_payload_records,
            metrics.historical_cache_entries,
            linux_memory_kib("VmRSS"),
            linux_memory_kib("VmHWM"),
        );
        previous = size;
    }
    Ok(())
}
