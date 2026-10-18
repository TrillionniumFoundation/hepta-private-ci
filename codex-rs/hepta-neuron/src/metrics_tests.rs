use super::*;

use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-neuron-metrics-{}-{serial}",
            std::process::id()
        ));
        Self(path)
    }

    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&self.0)
            .expect("open")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn scope() -> Digest32 {
    Digest32::of_bytes(b"scope")
}

fn generation() -> Generation {
    Generation::new(1).expect("generation")
}

fn event(value: u8) -> NeuronBatchMetricV1 {
    NeuronBatchMetricV1 {
        plan_digest: Digest32::of_bytes(&[value, 1]),
        execution_digest: Digest32::of_bytes(&[value, 2]),
        request_count: 2,
        elapsed_micros: 20,
        observed_cpu_micros: 0,
        observed_rss_bytes: 0,
        p95_micros: 20,
        p99_micros: 20,
        lock_wait_micros: 1,
        measurements_mask: 0b100,
    }
}

#[test]
fn group_commit_and_reopen_preserve_sequence_chain() {
    let fixture = Fixture::new();
    let mut writer = NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation())
        .expect("open");
    let receipt = writer.append_group(&[event(1), event(2)]).expect("commit");
    assert_eq!(receipt.committed_events, 2);
    assert_eq!(receipt.first_sequence, 1);
    assert_eq!(receipt.final_sequence, 2);
    assert_eq!(receipt.data_syncs, 1);
    drop(writer);
    let mut replay = NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation())
        .expect("reopen");
    assert_eq!(
        replay
            .append_group(&[event(3)])
            .expect("append")
            .final_sequence,
        3
    );
}

#[test]
fn partial_tail_is_recovered_but_complete_corruption_is_not() {
    let fixture = Fixture::new();
    let mut writer = NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation())
        .expect("open");
    writer.append_group(&[event(1)]).expect("commit");
    drop(writer);

    let mut file = fixture.file();
    file.seek(SeekFrom::End(0)).expect("seek");
    file.write_all(&[0, 0]).expect("partial prefix");
    file.sync_data().expect("sync");
    drop(file);
    let mut reopened =
        NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation())
            .expect("recover");
    assert!(
        reopened
            .append_group(&[event(2)])
            .expect("commit")
            .recovered_partial_tail
    );
    drop(reopened);

    let mut file = fixture.file();
    file.seek(SeekFrom::End(-1)).expect("seek");
    let mut old_byte = [0_u8; 1];
    file.read_exact(&mut old_byte).expect("read");
    file.seek(SeekFrom::End(-1)).expect("seek");
    file.write_all(&[old_byte[0] ^ 0xFF]).expect("tamper");
    file.sync_data().expect("sync");
    drop(file);
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation()),
        Err(NeuronMetricsErrorV1::Corrupt)
    ));
}

#[test]
fn scope_mismatch_and_competing_writer_fail_closed() {
    let fixture = Fixture::new();
    let writer = NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation())
        .expect("first owner");
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(fixture.file(), scope(), generation()),
        Err(NeuronMetricsErrorV1::Busy)
    ));
    drop(writer);
    assert!(matches!(
        NeuronMetricsGroupCommitWriterV1::open(
            fixture.file(),
            Digest32::of_bytes(b"other scope"),
            generation(),
        ),
        Err(NeuronMetricsErrorV1::ScopeMismatch)
    ));
}
