use super::super::DurableInferenceControl;
use super::super::Event;
use super::super::JOURNAL_PREFIX;
use super::super::NativeCheckpoint;
use super::super::NativeDispatch;
use super::super::NativeJournal;
use super::super::NativeReservationState;
use super::super::sha256_hex;
use super::super::write_content_addressed;
use super::*;
use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

struct StorePath {
    root: PathBuf,
    journal: PathBuf,
}
impl StorePath {
    fn new(label: &str) -> TestResult<Self> {
        let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        let root = std::env::temp_dir().join(format!(
            "bound-admission-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&root)?;
        Ok(Self {
            journal: root.join("owner.journal"),
            root,
        })
    }
}
impl Drop for StorePath {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn proof(
    request: &NativeRequest,
    record: &NativeBoundSourceRecordV2,
    socket: &Path,
) -> TestResult<NativeBoundSourceProof> {
    Ok(NativeBoundSourceProof::verify(
        request,
        "private fixture prompt",
        &None,
        socket,
        1000,
        record.clone(),
    )?)
}

fn checkpoint(path: &StorePath) -> TestResult<(Event, NativeCheckpoint)> {
    let text = fs::read_to_string(&path.journal)?;
    let line = text.lines().last().ok_or("missing checkpoint reference")?;
    let reference: Event = serde_json::from_str(
        line.strip_prefix(JOURNAL_PREFIX)
            .ok_or("native reference prefix")?,
    )?;
    let Event::CheckpointReference {
        checkpoint_path, ..
    } = &reference
    else {
        return Err("not a checkpoint reference".into());
    };
    let checkpoint = serde_json::from_slice(&fs::read(checkpoint_path)?)?;
    Ok((reference, checkpoint))
}

#[test]
fn bound_metadata_survives_reopen_and_compaction_without_plaintext() {
    let path = StorePath::new("reopen").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    let admitted = owner
        .reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap(),
        )
        .unwrap();
    assert_eq!(admitted.bound_source, Some(source));
    let text = fs::read_to_string(&path.journal).unwrap();
    assert!(!text.contains("private fixture prompt"));
    assert!(!text.contains("bound-source-agent.sock"));
    drop(owner);
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    assert_eq!(owner.native_record(&request.request_id), Some(&admitted));
    owner.compact_native_journal().unwrap();
    let (_, image) = checkpoint(&path).unwrap();
    assert_eq!(image.schema_version, 3);
    let encoded = serde_json::to_string(&image).unwrap();
    assert!(!encoded.contains("private fixture prompt"));
    assert!(!encoded.contains("bound-source-agent.sock"));
    drop(owner);
    let owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    assert_eq!(owner.native_record(&request.request_id), Some(&admitted));
}

#[test]
fn idempotent_bound_admission_and_legacy_collision_do_not_append() {
    let path = StorePath::new("idempotence").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    let first = owner
        .reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap(),
        )
        .unwrap();
    let before = fs::read(&path.journal).unwrap();
    assert_eq!(
        owner
            .reserve_native_bound(
                request.clone(),
                1,
                proof(&request, &source, &socket).unwrap()
            )
            .unwrap(),
        first
    );
    assert_eq!(
        owner.reserve_native(request.clone(), 1),
        Err(Error::Conflict)
    );
    assert_eq!(fs::read(&path.journal).unwrap(), before);
    drop(owner);
    let other = StorePath::new("legacy-first").unwrap();
    let mut owner = DurableInferenceControl::open(&other.journal, 8).unwrap();
    owner.reserve_native(request.clone(), 1).unwrap();
    assert_eq!(
        owner.reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap()
        ),
        Err(Error::Conflict)
    );
}

#[test]
fn bound_capacity_counts_other_held_records_before_staging() {
    let path = StorePath::new("capacity").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    let mut first = request.clone();
    first.request_id = "legacy-held".to_string();
    owner.reserve_native(first, 1).unwrap();
    let before = fs::read(&path.journal).unwrap();
    assert_eq!(
        owner.reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap()
        ),
        Err(Error::CapacityExceeded)
    );
    assert_eq!(owner.native_record(&request.request_id), None);
    assert_eq!(fs::read(&path.journal).unwrap(), before);
}

#[test]
fn legacy_dispatch_cannot_bypass_bound_profile_in_owner_or_replay() {
    let path = StorePath::new("legacy-dispatch").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    let admitted = owner
        .reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap(),
        )
        .unwrap();
    let dispatch: NativeDispatch = serde_json::from_value(serde_json::json!({"thread_id":"thread-one", "model_provider":"provider", "context_digest":"a".repeat(64)})).unwrap();
    assert_eq!(
        owner.dispatch_native(&request.request_id, dispatch.clone()),
        Err(Error::InvalidTransition)
    );
    assert_eq!(owner.native_record(&request.request_id), Some(&admitted));
    let mut replay = NativeJournal::default();
    replay
        .apply(Event::ReserveBound {
            request: request.clone(),
            maximum_in_flight: 1,
            source,
        })
        .unwrap();
    assert_eq!(
        replay.apply(Event::Dispatch {
            request_id: request.request_id.clone(),
            dispatch
        }),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        replay.records[&request.request_id].state,
        NativeReservationState::Reserved
    );
}

#[test]
fn ordinary_checkpoint_stays_v2_and_bound_data_cannot_hide_in_v2() {
    let path = StorePath::new("schema").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    owner.reserve_native(request.clone(), 1).unwrap();
    owner.compact_native_journal().unwrap();
    assert_eq!(checkpoint(&path).unwrap().1.schema_version, 2);
    drop(owner);
    let bound = StorePath::new("bound-schema").unwrap();
    let mut owner = DurableInferenceControl::open(&bound.journal, 8).unwrap();
    owner
        .reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap(),
        )
        .unwrap();
    owner.compact_native_journal().unwrap();
    drop(owner);
    let (reference, mut image) = checkpoint(&bound).unwrap();
    image.schema_version = 2;
    let bytes = serde_json::to_vec(&image).unwrap();
    let digest = sha256_hex(b"hepta.inference-control.checkpoint.v1\0", &bytes);
    let Event::CheckpointReference {
        generation,
        checkpoint_path,
        archive_segment_digest,
        archive_chain_digest,
        ..
    } = reference
    else {
        unreachable!()
    };
    let forged = Path::new(&checkpoint_path)
        .parent()
        .unwrap()
        .join(format!("{digest}.json"));
    write_content_addressed(&forged, &bytes).unwrap();
    let rewritten = Event::CheckpointReference {
        generation,
        checkpoint_path: forged.to_str().unwrap().to_string(),
        checkpoint_digest: digest,
        archive_segment_digest,
        archive_chain_digest,
    };
    fs::write(
        &bound.journal,
        format!(
            "{JOURNAL_PREFIX}{}\n",
            serde_json::to_string(&rewritten).unwrap()
        ),
    )
    .unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&bound.journal, 8),
        Err(Error::CorruptJournal(
            "bound native checkpoint requires schema 3"
        ))
    ));
}

#[test]
fn cached_bound_ack_cannot_survive_retained_journal_tampering() {
    let path = StorePath::new("retained-ack").unwrap();
    let (request, source, socket) = super::tests::fixture("private fixture prompt").unwrap();
    let mut owner = DurableInferenceControl::open(&path.journal, 8).unwrap();
    owner
        .reserve_native_bound(
            request.clone(),
            1,
            proof(&request, &source, &socket).unwrap(),
        )
        .unwrap();
    let original = fs::read(&path.journal).unwrap();
    fs::OpenOptions::new()
        .write(true)
        .open(&path.journal)
        .unwrap()
        .set_len(0)
        .unwrap();
    assert!(
        owner
            .reserve_native_bound(
                request.clone(),
                1,
                proof(&request, &source, &socket).unwrap()
            )
            .is_err()
    );
    fs::write(&path.journal, original).unwrap();
    assert!(
        owner
            .reserve_native_bound(
                request.clone(),
                1,
                proof(&request, &source, &socket).unwrap()
            )
            .is_err()
    );
}
