use super::*;
use std::io::Write;
use std::time::{SystemTime, UNIX_EPOCH};

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn generation(value: u64) -> Generation {
    Generation::new(value).expect("generation")
}
fn path(label: &str) -> std::path::PathBuf {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).expect("clock").as_nanos();
    std::env::temp_dir().join(format!("hepta-neuron-metrics-{}-{label}-{nonce}", std::process::id()))
}
fn event(label: &str) -> NeuronMetricEventV1 {
    NeuronMetricEventV1 {
        event_id: id(label),
        generation: generation(1),
        plan_digest: digest("plan"),
        execution_digest: digest("execution"),
        request_count: 2,
        elapsed_micros: 100,
        cpu_micros: 60,
        rss_bytes: 2048,
        p95_micros: 50,
        p99_micros: 95,
        lock_wait_micros: 2,
        recovered: false,
    }
}

#[test]
fn durable_group_reopens_and_duplicate_does_not_rewrite() {
    let p = path("group");
    {
        let mut writer = NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)).expect("open");
        let receipts = writer.append_group(vec![event("first"), event("second")]).expect("group");
        assert_eq!(receipts.len(), 2);
        assert_eq!(receipts[0].sequence, 1);
        assert_eq!(receipts[1].sequence, 2);
        assert_eq!(receipts[0].authority, AuthorityPosture::DENY_ALL);
        assert_eq!(writer.event_count(), 2);
        let before = std::fs::metadata(&p).expect("metadata").len();
        assert_eq!(writer.append(event("first")).expect("duplicate"), receipts[0]);
        assert_eq!(std::fs::metadata(&p).expect("metadata").len(), before);
        let mut changed = event("first");
        changed.rss_bytes += 1;
        assert_eq!(writer.append(changed), Err(MetricsError::DuplicateConflict));
    }
    {
        let mut writer = NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)).expect("reopen");
        assert_eq!(writer.event_count(), 2);
        let old = writer.append(event("second")).expect("idempotent replay");
        assert_eq!(old.sequence, 2);
        assert_eq!(writer.event_count(), 2);
    }
    std::fs::remove_file(p).expect("cleanup");
}

#[test]
fn rejects_scope_generation_latency_and_replay_drifts() {
    let p = path("binding");
    let mut writer = NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)).expect("open");
    let mut stale = event("old");
    stale.generation = generation(2);
    assert_eq!(writer.append(stale), Err(MetricsError::StaleGeneration));
    let mut invalid = event("invalid");
    invalid.p95_micros = invalid.p99_micros + 1;
    assert_eq!(writer.append(invalid), Err(MetricsError::InvalidEvent("latency quantiles")));
    assert_eq!(writer.event_count(), 0);
    drop(writer);
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(&p, digest("wrong"), generation(1)),
        Err(MetricsError::CorruptHeader)
    ));
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(2)),
        Err(MetricsError::CorruptHeader)
    ));
    std::fs::remove_file(p).expect("cleanup");
}

#[test]
fn incomplete_tail_is_repaired_but_complete_corruption_fails() {
    let p = path("recovery");
    {
        let mut writer = NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)).expect("open");
        writer.append(event("first")).expect("append");
    }
    let good_size = std::fs::metadata(&p).expect("metadata").len();
    {
        let mut file = OpenOptions::new().append(true).open(&p).expect("append tail");
        file.write_all(&[0, 0, 1, 0, 0xff]).expect("write torn tail");
        file.sync_all().expect("sync tail");
    }
    {
        let writer = NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)).expect("repair");
        assert_eq!(writer.event_count(), 1);
    }
    assert_eq!(std::fs::metadata(&p).expect("metadata").len(), good_size);
    {
        let mut bytes = std::fs::read(&p).expect("read");
        bytes[HEADER_BYTES as usize + 4 + 3] ^= 0x01;
        std::fs::write(&p, bytes).expect("corrupt");
    }
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(&p, digest("scope"), generation(1)),
        Err(MetricsError::CorruptFrame)
    ));
    std::fs::remove_file(p).expect("cleanup");
}
