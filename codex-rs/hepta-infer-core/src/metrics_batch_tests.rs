use super::*;

fn path(label: &str) -> std::path::PathBuf {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("hepta-metrics-batch-{label}-{nonce}.bin"))
}

fn lane() -> Digest32 {
    Digest32::of_bytes(b"lane")
}

fn sample(kind: MetricKindV1) -> MetricObservationV1 {
    MetricObservationV1 {
        lane_digest: lane(),
        kind,
        monotonic_micros: 100,
        value: 5,
    }
}

#[test]
fn fsync_is_per_batch_and_reopens_with_hash_chain() {
    let file = path("reopen");
    let first;
    {
        let mut sink = BatchedMetricJournalV1::open(&file, 8).expect("open");
        sink.record(sample(MetricKindV1::CasLatencyMicros)).expect("record");
        sink.record(sample(MetricKindV1::SignatureLatencyMicros)).expect("record");
        sink.record(sample(MetricKindV1::CnsLatencyMicros)).expect("record");
        assert_eq!(sink.pending_count(), 3);
        first = sink.flush().expect("flush").expect("receipt");
        assert_eq!(first.sequence, 1);
        assert_eq!(first.sample_count, 3);
        assert_eq!(sink.pending_count(), 0);
        assert_eq!(sink.flush(), Ok(None));
    }
    {
        let mut reopened = BatchedMetricJournalV1::open(&file, 8).expect("reopen");
        reopened.record(sample(MetricKindV1::ModelLatencyMicros)).expect("record");
        let second = reopened.flush().expect("flush").expect("receipt");
        assert_eq!(second.sequence, 2);
        assert_ne!(second.frame_digest, first.frame_digest);
    }
    BatchedMetricJournalV1::open(&file, 8).expect("complete replay");
    fs::remove_file(file).expect("cleanup");
}

#[test]
fn corruption_cannot_be_reinterpreted_as_a_clean_tail() {
    let file = path("corrupt");
    {
        let mut sink = BatchedMetricJournalV1::open(&file, 8).expect("open");
        sink.record(sample(MetricKindV1::CasLatencyMicros)).expect("record");
        sink.flush().expect("flush");
    }
    {
        use std::io::{Seek, SeekFrom};
        let mut f = OpenOptions::new().write(true).open(&file).expect("open");
        f.seek(SeekFrom::Start(HEADER_BYTES as u64 + 5)).expect("seek");
        f.write_all(&[255]).expect("corrupt");
        f.sync_all().expect("sync");
    }
    assert!(matches!(
        BatchedMetricJournalV1::open(&file, 8),
        Err(MetricsErrorV1::CorruptFrame)
    ));
    fs::remove_file(file).expect("cleanup");
}

#[test]
fn metric_loss_cannot_change_operation_result() {
    let file = path("measure");
    let mut sink = BatchedMetricJournalV1::open(&file, 1).expect("open");
    let (successful, recorded) = sink.measure(
        lane(),
        MetricKindV1::CasLatencyMicros,
        10,
        || Ok::<u64, ()>(42),
    );
    assert_eq!(successful, Ok(42));
    assert_eq!(recorded, Ok(()));
    let (failed, full) = sink.measure(
        lane(),
        MetricKindV1::CnsLatencyMicros,
        10,
        || Err::<u64, &str>("route unavailable"),
    );
    assert_eq!(failed, Err("route unavailable"));
    assert_eq!(full, Err(MetricsErrorV1::BufferFull));
    drop(sink);
    fs::remove_file(file).expect("cleanup");
}

#[test]
fn invalid_lanes_and_capacity_are_bounded() {
    let file = path("bounded");
    let mut sink = BatchedMetricJournalV1::open(&file, 1).expect("open");
    assert_eq!(
        sink.record(MetricObservationV1 {
            lane_digest: Digest32::ZERO,
            ..sample(MetricKindV1::WriteBytes)
        }),
        Err(MetricsErrorV1::MissingLane)
    );
    sink.record(sample(MetricKindV1::WriteBytes)).expect("record");
    assert_eq!(
        sink.record(sample(MetricKindV1::WriteBytes)),
        Err(MetricsErrorV1::BufferFull)
    );
    drop(sink);
    fs::remove_file(file).expect("cleanup");
}
