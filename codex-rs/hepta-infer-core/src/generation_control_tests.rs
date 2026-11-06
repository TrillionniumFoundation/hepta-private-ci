use super::super::InferenceRequest;
use super::super::native::NativeDispatch;
use super::super::native::NativeRequest;
use super::super::native::NativeRunOutput;
use super::*;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const PAYLOAD: &[u8] = b"original generation request bytes";
static NEXT_PATH: AtomicU64 = AtomicU64::new(1);

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Result<Self, Error> {
        let sequence = NEXT_PATH.fetch_add(1, Ordering::Relaxed);
        let directory = std::env::temp_dir().join(format!(
            "hepta-generation-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&directory)?;
        Ok(Self(directory))
    }
    fn path(&self) -> PathBuf {
        self.0.join("control.journal")
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn binding(id: &str) -> GenerationBindingV1 {
    GenerationBindingV1 {
        request_id: id.into(),
        principal_id: "principal.1".into(),
        worker_generation: 7,
        manifest_digest: [1; 32],
        request_digest: [2; 32],
        predecessor_digest: [3; 32],
        payload_digest: *Digest32::of_bytes(PAYLOAD).as_array(),
        payload_bytes: PAYLOAD.len() as u32,
        result_limit_bytes: 4096,
        deadline_micros: 100,
    }
}

fn legacy(id: &str) -> InferenceRequest {
    InferenceRequest {
        request_id: id.into(),
        principal_id: "principal.1".into(),
        model_digest: "1".repeat(64),
        payload_digest: "2".repeat(64),
        maximum_tokens: 8,
        deadline_ms: 100,
        semantic_digest: "3".repeat(64),
    }
}

fn native(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.into(),
        principal_id: "principal.1".into(),
        worker_generation: 7,
        model: "model.1".into(),
        payload_digest: "4".repeat(64),
    }
}

#[test]
fn original_result_and_cancel_survive_reopen_without_redispatch() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let request = binding("generation.1");
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let (_, mut token) =
        control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
    assert!(control.generation_has_unresolved()?);
    control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
    assert!(token.is_none());
    let cancelled = control.cancel_generation(&request)?;
    assert!(cancelled.result.is_none());
    let before = fs::read(fixture.path())?;
    assert_eq!(control.cancel_generation(&request)?, cancelled);
    assert_eq!(
        control
            .admit_generation(/*now_micros*/ 200, request.clone(), PAYLOAD)?
            .0,
        cancelled
    );
    assert_eq!(fs::read(fixture.path())?, before);
    drop(control);
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let (restored, token) =
        control.admit_generation(/*now_micros*/ 200, request.clone(), PAYLOAD)?;
    assert_eq!(restored, cancelled);
    assert!(token.is_none());
    let bytes = b"actual late proposal; cpu and energy unknown".to_vec();
    let settled = control.settle_generation(&request, bytes.clone())?;
    assert!(!control.generation_has_unresolved()?);
    let before = fs::read(fixture.path())?;
    assert_eq!(control.settle_generation(&request, bytes)?, settled);
    assert_eq!(
        control.settle_generation(&request, b"different result".to_vec()),
        Err(Error::Conflict)
    );
    assert_eq!(fs::read(fixture.path())?, before);
    drop(control);
    let control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    assert_eq!(control.generation_record(&request)?, Some(&settled));
    assert_eq!(control.generation_record(&binding("absent"))?, None);
    assert_eq!(fs::read(fixture.path())?, before);
    Ok(())
}

#[test]
fn live_abort_retains_real_bytes_and_reopened_owner_cannot_recreate_proof() -> Result<(), Error> {
    for cancellation in [false, true] {
        let fixture = Fixture::new()?;
        let request = binding("pre-effect");
        let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
        let (_, mut token) =
            control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
        if cancellation {
            control.cancel_generation(&request)?;
        }
        assert!(
            control
                .dispatch_generation(/*now_micros*/ 100, &mut token)
                .is_err()
        );
        assert!(token.is_some());
        assert_eq!(
            control.settle_generation(&request, b"unproven".to_vec()),
            Err(Error::InvalidTransition)
        );
        assert_eq!(
            control.abort_generation(&mut token, vec![1; 4097]),
            Err(Error::CapacityExceeded)
        );
        assert!(token.is_some());
        let bytes = b"pre-effect terminal with measured queue cost".to_vec();
        let aborted = control.abort_generation(&mut token, bytes.clone())?;
        assert!(token.is_none());
        assert!(aborted.aborted_before_dispatch);
        assert!(aborted.dispatched_at_micros.is_none());
        assert_eq!(
            aborted.result,
            Some(GenerationResultV1 {
                digest: *Digest32::of_bytes(&bytes).as_array(),
                bytes
            })
        );
    }
    let fixture = Fixture::new()?;
    let request = binding("recovered-admission");
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let (original, mut token) =
        control.admit_generation(/*now_micros*/ 150, request.clone(), PAYLOAD)?;
    drop(control);
    let mut reopened = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    assert_eq!(
        reopened.abort_generation(&mut token, b"wrong owner".to_vec()),
        Err(Error::Conflict)
    );
    assert_eq!(
        reopened.dispatch_generation(/*now_micros*/ 11, &mut token),
        Err(Error::Conflict)
    );
    let (restored, fresh_token) =
        reopened.admit_generation(/*now_micros*/ 12, request, PAYLOAD)?;
    assert_eq!(restored, original);
    assert!(fresh_token.is_none());
    assert!(reopened.generation_has_unresolved()?);
    Ok(())
}

#[test]
fn exact_binding_payload_deadline_and_size_fail_without_writing() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let request = binding("bound");
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let mut invalid = request.clone();
    invalid.deadline_micros = 0;
    assert!(matches!(
        control.admit_generation(/*now_micros*/ 10, invalid, PAYLOAD),
        Err(Error::InvalidTime)
    ));
    let late = binding("arrived-after-deadline");
    let (admitted, mut late_token) =
        control.admit_generation(/*now_micros*/ 100, late.clone(), PAYLOAD)?;
    assert_eq!(admitted.admitted_at_micros, 100);
    for now in [99, 100, 101] {
        assert_eq!(
            control.dispatch_generation(now, &mut late_token),
            Err(Error::InvalidTime)
        );
        assert!(late_token.is_some());
    }
    let aborted =
        control.abort_generation(&mut late_token, b"actual elapsed queue cost".to_vec())?;
    assert_eq!(aborted.admitted_at_micros, 100);
    assert!(aborted.aborted_before_dispatch);
    assert!(matches!(
        control.admit_generation(/*now_micros*/ 10, request.clone(), b"wrong"),
        Err(Error::Conflict)
    ));
    let (_, mut token) =
        control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
    let before = fs::read(fixture.path())?;
    let changes: [fn(&mut GenerationBindingV1); 9] = [
        |b| b.principal_id = "principal.2".into(),
        |b| b.worker_generation += 1,
        |b| b.manifest_digest[0] ^= 1,
        |b| b.request_digest[0] ^= 1,
        |b| b.predecessor_digest[0] ^= 1,
        |b| b.payload_digest[0] ^= 1,
        |b| b.payload_bytes += 1,
        |b| b.result_limit_bytes += 1,
        |b| b.deadline_micros += 1,
    ];
    for change in changes {
        let mut changed = request.clone();
        change(&mut changed);
        assert_eq!(control.generation_record(&changed), Err(Error::Conflict));
        assert_eq!(control.cancel_generation(&changed), Err(Error::Conflict));
        assert_eq!(
            control.settle_generation(&changed, vec![1]),
            Err(Error::Conflict)
        );
    }
    assert_eq!(
        control.dispatch_generation(/*now_micros*/ 9, &mut token),
        Err(Error::InvalidTime)
    );
    assert!(token.is_some());
    assert_eq!(fs::read(fixture.path())?, before);
    control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
    let before = fs::read(fixture.path())?;
    assert_eq!(
        control.settle_generation(&request, vec![1; 4097]),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.settle_generation(&request, Vec::new()),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(fs::read(fixture.path())?, before);
    Ok(())
}

#[test]
fn all_three_families_share_ids_capacity_and_exclusive_file_lock() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 3)?;
    control.submit(/*now_ms*/ 1, legacy("legacy"))?;
    control.reserve_native(native("native"), /*maximum_in_flight*/ 1)?;
    let (record, _) =
        control.admit_generation(/*now_micros*/ 1, binding("generation"), PAYLOAD)?;
    for id in ["legacy", "native"] {
        assert!(matches!(
            control.admit_generation(/*now_micros*/ 1, binding(id), PAYLOAD),
            Err(Error::Conflict)
        ));
    }
    assert_eq!(
        control.submit(/*now_ms*/ 1, legacy("generation")),
        Err(Error::Conflict)
    );
    assert_eq!(
        control.reserve_native(native("generation"), /*maximum_in_flight*/ 1),
        Err(Error::Conflict)
    );
    assert!(matches!(
        control.admit_generation(/*now_micros*/ 1, binding("full"), PAYLOAD),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(
        control.submit(/*now_ms*/ 1, legacy("full")),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(
        control.reserve_native(native("full"), /*maximum_in_flight*/ 1),
        Err(Error::CapacityExceeded)
    );
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 3),
        Err(Error::WriterUnavailable)
    ));
    #[cfg(unix)]
    {
        let alias = fixture.0.join("same-inode");
        fs::hard_link(fixture.path(), &alias)?;
        assert!(matches!(
            DurableInferenceControl::open(alias, /*capacity*/ 3),
            Err(Error::WriterUnavailable)
        ));
    }
    drop(control);
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 2),
        Err(Error::CapacityExceeded)
    ));
    let reopened = DurableInferenceControl::open(fixture.path(), /*capacity*/ 3)?;
    assert_eq!(reopened.generation_record(&record.binding)?, Some(&record));
    Ok(())
}

#[test]
fn corrupted_result_truncated_tail_and_cross_family_replay_fail_closed() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let request = binding("collision");
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 8)?;
    let (_, mut token) =
        control.admit_generation(/*now_micros*/ 1, request.clone(), PAYLOAD)?;
    control.dispatch_generation(/*now_micros*/ 2, &mut token)?;
    control.settle_generation(&request, b"original".to_vec())?;
    drop(control);
    let complete = fs::read(fixture.path())?;
    fs::write(fixture.path(), &complete[..complete.len() - 1])?;
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 8),
        Err(Error::CorruptJournal("incomplete line"))
    ));
    assert_eq!(fs::read(fixture.path())?, &complete[..complete.len() - 1]);
    let text =
        String::from_utf8(complete.clone()).map_err(|_| Error::CorruptJournal("test utf8"))?;
    fs::write(
        fixture.path(),
        text.replace(
            "[111,114,105,103,105,110,97,108]",
            "[110,114,105,103,105,110,97,108]",
        ),
    )?;
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 8),
        Err(Error::InvalidDigest("generation result"))
    ));
    fs::write(fixture.path(), &complete)?;
    let other = Fixture::new()?;
    let mut old = DurableInferenceControl::open(other.path(), /*capacity*/ 8)?;
    old.submit(/*now_ms*/ 1, legacy("collision"))?;
    drop(old);
    fs::OpenOptions::new()
        .append(true)
        .open(fixture.path())?
        .write_all(&fs::read(other.path())?)?;
    let before = fs::read(fixture.path())?;
    assert!(matches!(
        DurableInferenceControl::open(fixture.path(), /*capacity*/ 8),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(fs::read(fixture.path())?, before);
    Ok(())
}

#[test]
fn real_file_capacity_preserves_cancel_dispatch_and_maximal_result_space() -> Result<(), Error> {
    let fixture = Fixture::new()?;
    let mut control = DurableInferenceControl::open(fixture.path(), /*capacity*/ 32)?;
    control.reserve_native(native("large-native"), /*maximum_in_flight*/ 1)?;
    let dispatch: NativeDispatch = serde_json::from_value(serde_json::json!({
        "thread_id":"thread.1", "model_provider":"provider.1", "context_digest":"2".repeat(64)
    }))
    .map_err(|_| Error::CorruptJournal("test dispatch"))?;
    control.dispatch_native("large-native", dispatch)?;
    let mut output: NativeRunOutput = serde_json::from_value(serde_json::json!({
        "thread_id":"thread.1", "turn_id":"turn.1", "model":"model.1", "model_provider":"provider.1",
        "status":"completed", "output":"\u{0}".repeat(1_000_000), "observed_output_tokens":0,
        "terminal_observed":true, "stop_reason":null
    })).map_err(|_| Error::CorruptJournal("test output"))?;
    // Genuine native usage refinements append ~6 MB each, without fake byte
    // counters, invalid padding, or manufacturing generation terminal results.
    for observed in 1..=10 {
        output.observed_output_tokens = Some(observed);
        control.settle_native("large-native", output.clone())?;
    }
    let mut request = binding("reserved");
    request.result_limit_bytes = MAX_GENERATION_RESULT_BYTES as u32;
    let (_, mut token) =
        control.admit_generation(/*now_micros*/ 10, request.clone(), PAYLOAD)?;
    let before = fs::metadata(fixture.path())?.len();
    assert!(before + 6_100_000 < super::super::MAX_JOURNAL_BYTES);
    output.observed_output_tokens = Some(11);
    assert_eq!(
        control.settle_native("large-native", output),
        Err(Error::CapacityExceeded)
    );
    let mut extra = request.clone();
    extra.request_id = "overflow".into();
    assert!(matches!(
        control.admit_generation(/*now_micros*/ 10, extra, PAYLOAD),
        Err(Error::CapacityExceeded)
    ));
    assert_eq!(fs::metadata(fixture.path())?.len(), before);
    control.dispatch_generation(/*now_micros*/ 11, &mut token)?;
    control.cancel_generation(&request)?;
    let bytes = vec![255; MAX_GENERATION_RESULT_BYTES];
    let settled = control.settle_generation(&request, bytes)?;
    drop(control);
    let reopened = DurableInferenceControl::open(fixture.path(), /*capacity*/ 32)?;
    assert_eq!(reopened.generation_record(&request)?, Some(&settled));
    Ok(())
}
