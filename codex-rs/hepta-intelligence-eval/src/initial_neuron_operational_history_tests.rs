//! Uses the original expired Linux E1 measurement and native signed cuts.
//! No signing fixtures, private keys or new authorization are created here.
use super::*;
use codex_hepta_learning_ledger::read_root_review_input;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HistoricalFixture {
    configuration: Source,
    report: Source,
}

fn original() -> HistoricalFixture {
    let path = std::env::var_os("HEPTA_INITIAL_OPERATIONAL_HISTORY_TEST_DESCRIPTOR")
        .expect("explicit protected original E1 descriptor");
    serde_json::from_slice(&read_root_review_input(Path::new(&path), 16 * 1024).unwrap()).unwrap()
}

fn inspect_history(input: &HistoricalFixture) -> HostResult<VerifiedInitialOperationalHistoryV1> {
    inspect_initial_neuron_operational_history(
        &input.configuration.path,
        input.configuration.digest.parse()?,
        &input.report.path,
        input.report.digest.parse()?,
    )
}

struct ChangedReport {
    path: std::path::PathBuf,
    digest: Digest32,
}
impl ChangedReport {
    fn new(input: &HistoricalFixture, mutate: impl FnOnce(&mut Value)) -> Self {
        let mut report: Value =
            serde_json::from_slice(&input.report.read(64 * 1024).unwrap()).unwrap();
        mutate(&mut report);
        let bytes = serde_json::to_vec(&report).unwrap();
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = input.report.path.parent().unwrap().join(format!(
            "history-rejection-{}-{nonce}.json",
            std::process::id()
        ));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        file.write_all(&bytes).unwrap();
        file.sync_all().unwrap();
        Self {
            path,
            digest: Digest32::of_bytes(&bytes),
        }
    }
    fn inspect(
        &self,
        input: &HistoricalFixture,
    ) -> HostResult<VerifiedInitialOperationalHistoryV1> {
        inspect_initial_neuron_operational_history(
            &input.configuration.path,
            input.configuration.digest.parse()?,
            &self.path,
            self.digest,
        )
    }
}
impl Drop for ChangedReport {
    fn drop(&mut self) {
        std::fs::remove_file(&self.path).unwrap();
    }
}

#[test]
#[ignore = "requires the protected original expired E1 descriptor and actual Root reader"]
fn original_expired_measurement_is_history_and_never_current_admission() {
    let input = original();
    let history = inspect_history(&input).unwrap();
    assert!(history.original_expires_at() < now_ms().unwrap());
    let bytes = input.report.read(64 * 1024).unwrap();
    let report: Report = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(history.measurements(), &report.body);
    history.revalidate_integrity().unwrap();
    assert!(
        inspect_initial_neuron_operational_evidence(
            &input.configuration.path,
            input.configuration.digest.parse().unwrap(),
            &input.report.path,
            input.report.digest.parse().unwrap(),
        )
        .is_err()
    );
}

#[test]
#[ignore = "requires the protected original expired E1 descriptor and actual Root reader"]
fn historical_measurement_rejects_changed_payload_even_with_new_file_digest() {
    let input = original();
    let changed = ChangedReport::new(&input, |report| {
        report["body"]["operational_constraints_passed"] = Value::Bool(false);
    });
    assert!(changed.inspect(&input).is_err());
    assert!(
        inspect_initial_neuron_operational_history(
            &input.configuration.path,
            Digest32::of_bytes(b"wrong-original-config"),
            &input.report.path,
            input.report.digest.parse().unwrap(),
        )
        .is_err()
    );
    inspect_history(&input)
        .unwrap()
        .revalidate_integrity()
        .unwrap();
}

#[test]
#[ignore = "requires the protected original expired E1 descriptor and actual Root reader"]
fn historical_measurement_rejects_future_instant_and_signature_substitution() {
    let input = original();
    let future = ChangedReport::new(&input, |report| {
        report["body"]["measured_at_ms"] = Value::from(now_ms().unwrap() + 60_000);
    });
    assert!(future.inspect(&input).is_err());
    let changed = ChangedReport::new(&input, |report| {
        report["evaluator_signed_evidence"]["signature_hex"] = Value::String("00".repeat(64));
    });
    assert!(changed.inspect(&input).is_err());
}
