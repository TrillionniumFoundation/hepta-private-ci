//! Source-testable reference-only microbatch qualification.
//! Outputs observed host measurements, never a production or model claim.

#![forbid(unsafe_code)]

use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::sync::Arc;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_worker_host::neuron_microbatch::NeuronBatchHeadV1;
use codex_hepta_infer_worker_host::neuron_microbatch::NeuronFrozenFeatureV1;
use codex_hepta_infer_worker_host::neuron_microbatch::NeuronHostResourceSampleV1;
use codex_hepta_infer_worker_host::neuron_microbatch::NeuronMicrobatchPlanV1;
use codex_hepta_infer_worker_host::neuron_microbatch::NeuronMicrobatchWorkerV1;
use codex_hepta_infer_worker_host::neuron_microbatch::NeuronSnapshotIdentityV1;
use codex_hepta_infer_worker_host::neuron_microbatch::ReferenceNeuronBatchBackendV1;
use codex_hepta_neuron::NeuronMetricsGroupCommitWriterV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::json;

fn parse_cells() -> Result<usize, String> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if arguments.len() != 2 || arguments[0] != "--cells" {
        return Err("usage: hepta-neuron-microbatch-qualification --cells 64|256|1024|4096".into());
    }
    let cells = arguments[1].parse::<usize>().map_err(|_| "invalid cells")?;
    if ![64, 256, 1024, 4096].contains(&cells) {
        return Err("unsupported size".into());
    }
    Ok(cells)
}

fn id(raw: String) -> Result<StableId, Box<dyn std::error::Error>> {
    Ok(StableId::new(raw)?)
}

fn cpu_schedstat_ns() -> Option<u64> {
    // Current thread-group task sampling; a disappeared or unreadable thread
    // invalidates the sample rather than inventing a zero.
    let mut sum = 0_u64;
    for entry in std::fs::read_dir("/proc/self/task").ok()? {
        let path = entry.ok()?.path().join("schedstat");
        let raw = std::fs::read_to_string(path).ok()?;
        let nanos = raw.split_whitespace().next()?.parse::<u64>().ok()?;
        sum = sum.checked_add(nanos)?;
    }
    Some(sum)
}

fn resident_bytes() -> Option<u64> {
    let raw = std::fs::read_to_string("/proc/self/status").ok()?;
    let line = raw.lines().find(|line| line.starts_with("VmRSS:"))?;
    let kb = line.split_whitespace().nth(1)?.parse::<u64>().ok()?;
    kb.checked_mul(1024)
}

fn now_ms() -> Result<u64, Box<dyn std::error::Error>> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let cells = parse_cells().map_err(std::io::Error::other)?;
    let scope = Digest32::of_bytes(b"qualification.reference.scope");
    let generation = Generation::new(1)?;
    let snapshot = Arc::new(NeuronFrozenFeatureV1::freeze(
        NeuronSnapshotIdentityV1 {
            subject_id: id("qualification.reference.subject".into())?,
            scope_digest: scope,
            ndu_snapshot_digest: Digest32::of_bytes(b"qualification.reference.ndu"),
            generation,
            authority_epoch: 1,
            encoder_digest: Digest32::of_bytes(b"qualification.fake.encoder"),
            tokenizer_digest: Digest32::of_bytes(b"qualification.fake.tokenizer"),
            normalizer_digest: Digest32::of_bytes(b"qualification.fake.normalizer"),
            source_digest: Digest32::of_bytes(b"qualification.fake.source"),
        },
        vec![1 << 23, 1 << 22, -(1 << 21), 0],
    )?);
    let filename = std::env::temp_dir().join(format!(
        "hepta-neuron-qualification-{}-{}.metrics",
        std::process::id(),
        now_ms()?
    ));
    let metadata_path = filename.clone();
    let report = (|| -> Result<serde_json::Value, Box<dyn std::error::Error>> {
        let file = OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&metadata_path)?;
        let metrics = NeuronMetricsGroupCommitWriterV1::open(file, scope, generation)?;
        let mut worker = NeuronMicrobatchWorkerV1::new(
            id("worker.reference.qualification".into())?,
            generation,
            scope,
            metrics,
        )?;
        let mut backend = ReferenceNeuronBatchBackendV1::default();
        let started = Instant::now();
        let cpu_before = cpu_schedstat_ns();
        let rss_before = resident_bytes();
        let mut rss_peak = rss_before;
        let mut observed_batch_us = Vec::new();
        let mut accepted_rows = 0_usize;
        let mut commits = 0_u64;
        for (batch_no, offset) in (0..cells).step_by(256).enumerate() {
            let count = (cells - offset).min(256);
            let heads = (0..count)
                .map(|row| {
                    let cell = offset + row;
                    Ok(NeuronBatchHeadV1 {
                        request_id: id(format!("qualification.request.{cell}"))?,
                        reservation_id: id(format!("qualification.reservation.{cell}"))?,
                        head_digest: Digest32::of_bytes(format!("head.{cell}").as_bytes()),
                        expected_width: 4,
                    })
                })
                .collect::<Result<Vec<_>, Box<dyn std::error::Error>>>()?;
            let plan = NeuronMicrobatchPlanV1::freeze(
                id("worker.reference.qualification".into())?,
                Arc::clone(&snapshot),
                now_ms()?.checked_add(120_000).ok_or("clock overflow")?,
                heads,
            )?;
            let t = Instant::now();
            let receipt = worker.run_reference(
                now_ms()?,
                &plan,
                &mut backend,
                NeuronHostResourceSampleV1::default(),
            )?;
            observed_batch_us.push(u64::try_from(t.elapsed().as_micros())?);
            if receipt.results.len() != count
                || receipt.metric_sequence != (batch_no as u64 + 1)
                || receipt.authority.grants_any()
            {
                return Err("non-authorizing batch or durable metric mismatch".into());
            }
            accepted_rows += receipt.results.len();
            commits = receipt.metric_sequence;
            if let Some(rss) = resident_bytes() {
                rss_peak = Some(rss_peak.unwrap_or(0).max(rss));
            }
        }
        let elapsed_micros = u64::try_from(started.elapsed().as_micros())?;
        let cpu_after = cpu_schedstat_ns();
        let rss_after = resident_bytes();
        let disk_bytes = std::fs::metadata(&metadata_path)?.len();
        drop(worker);

        // Simulate an interrupted append and verify that a fresh owner accepts
        // only the intact, previously fsynced chain.
        let mut file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&metadata_path)?;
        file.seek(SeekFrom::End(0))?;
        file.write_all(&[0_u8, 0_u8])?;
        file.sync_data()?;
        drop(file);
        let recovered = NeuronMetricsGroupCommitWriterV1::open(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(&metadata_path)?,
            scope,
            generation,
        )?;
        let recovered_count = recovered.recorded_sequence();
        let tail_recovered = recovered.recovered_partial_tail();
        if !tail_recovered || recovered_count != commits {
            return Err("durable metrics recovery qualification failed".into());
        }
        drop(recovered);

        observed_batch_us.sort_unstable();
        let percentile = |percent: usize| -> u64 {
            observed_batch_us[(observed_batch_us.len() * percent)
                .div_ceil(100)
                .saturating_sub(1)]
        };
        let reference_rate = if elapsed_micros == 0 {
            None
        } else {
            Some((accepted_rows as f64) * 1_000_000.0 / (elapsed_micros as f64))
        };
        Ok(json!({
            "schema": "hepta.neuron.microbatch-reference-qualification.v1",
            "productionClaim": false,
            "backendKind": "deterministic_reference_not_pretrained",
            "authority": "DENY_ALL",
            "cells": cells,
            "batchSizeLimit": 256,
            "executedBatchCalls": backend.batch_invocations,
            "acceptedCells": accepted_rows,
            "durableMetricRecords": commits,
            "durableMetricsBytesBeforeCrash": disk_bytes,
            "crashTailRecovered": tail_recovered,
            "recoveredCompleteRecords": recovered_count,
            "elapsedMicros": elapsed_micros,
            "referenceCellsPerSecond": reference_rate,
            "batchWallP95Micros": percentile(95),
            "batchWallP99Micros": percentile(99),
            "hostCpuSource": "linux_proc_task_schedstat_cumulative_ns",
            "hostCpuDeltaNanos": cpu_before.zip(cpu_after)
                .and_then(|(before, after)| after.checked_sub(before)),
            "rssBeforeBytes": rss_before,
            "rssAfterBytes": rss_after,
            "rssPeakSampledBytes": rss_peak,
            "lockContentionMicros": null,
            "modelAccuracy": null,
            "targetHostProductAcceptance": false
        }))
    })();
    let _ = std::fs::remove_file(&filename);
    println!("{}", serde_json::to_string_pretty(&report?)?);
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("reference qualification failed: {error}");
        std::process::exit(1);
    }
}
