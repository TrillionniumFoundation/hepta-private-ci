//! Measurement harness for the real ledger core, not a scalability certificate.
//! Run in release mode in a fresh process for each size/repeat. This reports
//! full replay/snapshot costs honestly; it does not claim checkpoint recovery.
//! Ported from #912 to #774's existing typed-cursor and resident-record API.
use std::fmt::Debug;
use std::hint::black_box;
use std::io;
use std::time::Instant;

use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LearningLedger;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn checked<T, E: Debug>(value: Result<T, E>) -> io::Result<T> {
    value.map_err(|error| io::Error::other(format!("{error:?}")))
}

fn stable_id(value: &str) -> io::Result<StableId> {
    checked(StableId::new(value))
}

fn decision(index: usize) -> io::Result<LedgerEvent> {
    Ok(LedgerEvent::Decision(EpisodeDecision {
        record_id: stable_id(&format!("record-{index}"))?,
        episode_id: stable_id(&format!("episode-{index}"))?,
        objective_digest: Digest32::of_bytes(b"scale-objective"),
        policy_id: checked(StableId::new("scale-policy"))?,
        candidate_ids: vec![
            checked(StableId::new("abstain"))?,
            checked(StableId::new("choose"))?,
        ],
        selected_candidate_id: checked(StableId::new("choose"))?,
        selected_propensity: checked(ProbabilityQ32::from_raw(1_u64 << 31))?,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"scale-support"),
    }))
}

fn linux_memory_kib(field: &str) -> String {
    std::fs::read_to_string("/proc/self/status")
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
    let sizes: Vec<_> = std::env::args().skip(1).collect();
    if sizes.len() != 1 {
        return Err(io::Error::other("usage: ledger_scale <records: 1..=900000>"));
    }
    let count: usize = checked(sizes[0].parse())?;
    if !(1..=900_000).contains(&count) {
        return Err(io::Error::other("records must be in 1..=900000"));
    }
    let mut ledger = LearningLedger::new();
    let start = Instant::now();
    for index in 0..count {
        checked(ledger.append(decision(index)?))?;
    }
    let append_ns = start.elapsed().as_nanos();
    let hot_rss_kib = linux_memory_kib("VmRSS");
    let replay_event = decision(0)?;
    let start = Instant::now();
    for _ in 0..1000 {
        black_box(checked(ledger.append(replay_event.clone()))?);
    }
    let retry_ns = start.elapsed().as_nanos();
    let lookup_id = checked(StableId::new("record-0"))?;
    let start = Instant::now();
    for _ in 0..10_000 {
        let _ = black_box(ledger.record(&lookup_id));
    }
    let lookup_ns = start.elapsed().as_nanos();
    let start = Instant::now();
    let mut cursor = None;
    let mut seen = 0;
    loop {
        let page = ledger.records_after(cursor, 256);
        if page.is_empty() {
            break;
        }
        seen += page.len();
        for record in page {
            cursor = Some(black_box(record.sequence));
        }
    }
    let page_scan_ns = start.elapsed().as_nanos();
    if seen != count {
        return Err(io::Error::other("pagination lost or repeated records"));
    }
    let start = Instant::now();
    let snapshot = ledger.snapshot();
    let snapshot_ns = start.elapsed().as_nanos();
    let snapshot_rss_kib = linux_memory_kib("VmRSS");
    drop(ledger);
    let start = Instant::now();
    let recovered = checked(LearningLedger::from_snapshot(snapshot))?;
    let recovery_ns = start.elapsed().as_nanos();
    if recovered.records().len() != count {
        return Err(io::Error::other("recovery record count mismatch"));
    }
    println!(
        "{{\"schema\":\"hepta.ledger-core-scale.v1\",\"records\":{count},\"append_ns\":{append_ns},\"retry_1000_ns\":{retry_ns},\"lookup_10000_ns\":{lookup_ns},\"page_scan_ns\":{page_scan_ns},\"snapshot_ns\":{snapshot_ns},\"full_recovery_ns\":{recovery_ns},\"hot_rss_kib\":{hot_rss_kib},\"snapshot_rss_kib\":{snapshot_rss_kib},\"peak_rss_kib\":{},\"persistence_measured\":false}}",
        linux_memory_kib("VmHWM")
    );
    Ok(())
}
