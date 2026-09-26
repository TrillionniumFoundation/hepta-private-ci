//! Opt-in target-host curve for the actual signed product writer. Timing is
//! observational, never an acceptance threshold; recovery and exact replay are
//! asserted at every history size. Signature creation is outside append timing.
//! Dataset-freeze observations reuse this SAME fully persisted signed history;
//! one independently observed outcome makes its current dataset well-defined.
use super::*;
use std::time::Instant;

fn percentile_ns(samples: &mut [u128], percentile: usize) -> u128 {
    samples.sort_unstable();
    samples[(samples.len() - 1) * percentile / 100]
}

fn process_rss_kib() -> Option<u64> {
    fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse()
                .ok()
        })
}

fn process_cpu_ticks() -> Option<u64> {
    let stat = fs::read_to_string("/proc/self/stat").ok()?;
    let (_, fields) = stat.rsplit_once(')')?;
    let fields = fields.split_whitespace().collect::<Vec<_>>();
    let user = fields.get(11)?.parse::<u64>().ok()?;
    let system = fields.get(12)?.parse::<u64>().ok()?;
    user.checked_add(system)
}

fn optional_number(value: Option<u64>) -> String {
    value.map_or_else(|| "null".to_string(), |number| number.to_string())
}

#[test]
#[ignore = "target-host signed writer growth curve; execute explicitly with --ignored"]
fn signed_product_history_curve_append_lookup_reopen_and_exact_retry() {
    let fixture = Fixture::new();
    let directory = fixture.directory();
    let ledger = DurableLedger::create(fixture.file("ledger"), binding(), 8192).unwrap();
    let witness = LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap();
    let mut writer =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    let first = decision();
    let signed = sign(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&first).unwrap(),
    );
    let original = writer
        .append_decision(Digest32::ZERO, first.clone(), &signed, 50)
        .unwrap();
    let observed = outcome("growth-outcome", "growth-value", None, 100);
    let observer_evidence = sign(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    let mut predecessor = writer
        .append_outcome(original.chain_digest, observed, &observer_evidence, 50)
        .unwrap()
        .chain_digest;
    let mut committed = 2;
    for records in [64_usize, 256, 1024, 4096] {
        let cpu_before = process_cpu_ticks();
        let mut append_samples = Vec::with_capacity(records - committed);
        let mut last = first.clone();
        for index in committed..records {
            last = decision();
            last.record_id = id(&format!("curve-record-{index}"));
            last.episode_id = id(&format!("curve-episode-{index}"));
            let evidence = sign(
                writer.verifier(),
                "generator",
                LearningEvidenceRoleV1::Generator,
                &decision_signing_payload_v2(&last).unwrap(),
            );
            let started = Instant::now();
            let receipt = writer
                .append_decision(predecessor, last.clone(), &evidence, 50)
                .unwrap();
            append_samples.push(started.elapsed().as_nanos());
            predecessor = receipt.chain_digest;
        }
        let window_cpu_ticks = cpu_before
            .zip(process_cpu_ticks())
            .and_then(|(before, after)| after.checked_sub(before));
        let mut lookup_samples = Vec::with_capacity(100);
        for index in 0..100 {
            let record = if index % 2 == 0 { &first } else { &last };
            let started = Instant::now();
            writer
                .verify_active_decision_binding(&record.record_id, &record.episode_id)
                .unwrap();
            lookup_samples.push(started.elapsed().as_nanos());
        }
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("growth-dataset"),
            objective_digest: digest("objective"),
            inclusion_policy_digest: digest("inclusion-policy"),
        };
        let payload = writer.dataset_freeze_signing_payload(&plan).unwrap();
        let evaluator_evidence = sign(
            writer.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &payload,
        );
        let mut freeze_samples = Vec::with_capacity(32);
        let rss_before_freeze_kib = process_rss_kib();
        for _ in 0..32 {
            let started = Instant::now();
            let dataset = writer
                .freeze_dataset(plan.clone(), &evaluator_evidence, 50)
                .unwrap();
            freeze_samples.push(started.elapsed().as_nanos());
            assert_eq!(dataset.snapshot.source_record_digests.len(), records);
            assert_eq!(dataset.snapshot.pending_outcomes as usize, records - 2);
        }
        println!(
            concat!(
                "HEPTA_FREEZE_GROWTH_V1 {{\"records\":{},\"samples\":32,",
                "\"freeze_p50_ns\":{},\"freeze_p95_ns\":{},\"freeze_p99_ns\":{},",
                "\"rss_before_freeze_kib\":{},\"rss_after_freeze_kib\":{}}}"
            ),
            records,
            percentile_ns(&mut freeze_samples, 50),
            percentile_ns(&mut freeze_samples, 95),
            percentile_ns(&mut freeze_samples, 99),
            optional_number(rss_before_freeze_kib),
            optional_number(process_rss_kib()),
        );
        let frontier = writer.witness_frontier().unwrap();
        assert_eq!(frontier.anchor.sequence, records as u64);
        let before_disk = fixture.file("ledger").metadata().unwrap().len();
        let before_witness = fixture.file("witness").metadata().unwrap().len();
        let mut retry_samples = Vec::with_capacity(32);
        for _ in 0..32 {
            let started = Instant::now();
            let retry = writer
                .append_decision(Digest32::ZERO, first.clone(), &signed, 50)
                .unwrap();
            retry_samples.push(started.elapsed().as_nanos());
            assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
            assert_eq!(retry.chain_digest, original.chain_digest);
        }
        assert_eq!(writer.witness_frontier().unwrap(), frontier);
        assert_eq!(
            fixture.file("ledger").metadata().unwrap().len(),
            before_disk
        );
        assert_eq!(
            fixture.file("witness").metadata().unwrap().len(),
            before_witness
        );
        let rss_before_reopen_kib = process_rss_kib();
        drop(writer);
        let trust = activated_trust();
        let started = Instant::now();
        let ledger = DurableLedger::recover(
            fixture.file("ledger"),
            binding(),
            8192,
            LedgerRecovery::Acknowledged(frontier.anchor),
        )
        .unwrap();
        let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
        writer =
            LedgerWriter::from_durable(ledger, witness, trust, &directory, &directory).unwrap();
        let reopen_ns = started.elapsed().as_nanos();
        assert_eq!(writer.witness_frontier().unwrap(), frontier);
        writer
            .verify_active_decision_binding(&first.record_id, &first.episode_id)
            .unwrap();
        let retry = writer
            .append_decision(Digest32::ZERO, first.clone(), &signed, 50)
            .unwrap();
        assert_eq!(retry.chain_digest, original.chain_digest);
        // A recovered cache must not admit a same-ID, different-body replay.
        let mut changed = first.clone();
        changed.support_digest = digest("substituted-curve-body");
        let changed_evidence = sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&changed).unwrap(),
        );
        assert!(
            writer
                .append_decision(Digest32::ZERO, changed, &changed_evidence, 50)
                .is_err()
        );
        assert_eq!(writer.witness_frontier().unwrap(), frontier);
        println!(
            concat!(
                "HEPTA_LEDGER_GROWTH_V1 {{\"records\":{},\"append_samples\":{},",
                "\"append_p50_ns\":{},\"append_p95_ns\":{},\"append_p99_ns\":{},",
                "\"lookup_p50_ns\":{},\"lookup_p99_ns\":{},\"retry_p99_ns\":{},",
                "\"reopen_ns\":{},\"ledger_bytes\":{},\"witness_bytes\":{},",
                "\"rss_before_reopen_kib\":{},\"rss_after_reopen_kib\":{},\"window_cpu_ticks\":{}}}"
            ),
            records,
            append_samples.len(),
            percentile_ns(&mut append_samples, 50),
            percentile_ns(&mut append_samples, 95),
            percentile_ns(&mut append_samples, 99),
            percentile_ns(&mut lookup_samples, 50),
            percentile_ns(&mut lookup_samples, 99),
            percentile_ns(&mut retry_samples, 99),
            reopen_ns,
            before_disk,
            before_witness,
            optional_number(rss_before_reopen_kib),
            optional_number(process_rss_kib()),
            optional_number(window_cpu_ticks)
        );
        committed = records;
    }
}
