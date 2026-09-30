use super::super::FeatureOperationRecordV1;
use super::super::tests::private_directory;
use super::super::tests::receipt;
use super::super::tests::request;
use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn observe(control: &mut DurableInferenceControl, request: &crate::NeuronFeatureRequestV1) {
    control.reserve_feature(request.clone()).expect("reserve");
    control
        .dispatch_feature(request)
        .expect("original dispatch");
    control
        .observe_feature(request, &receipt(request))
        .expect("original terminal receipt");
}

#[test]
fn feature_cold_history_keeps_original_truth_with_bounded_hot_records_and_restart() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 2).expect("owner");
    let mut unknown = request();
    unknown.request_id = StableId::new("feature.unknown").expect("ID");
    control.reserve_feature(unknown.clone()).expect("reserved");
    control
        .dispatch_feature(&unknown)
        .expect("unresolved physical fence");
    let mut originals = Vec::new();
    for ordinal in 0..48 {
        let mut item = request();
        item.request_id = StableId::new(format!("feature.finished.{ordinal}")).expect("ID");
        item.feature_vector_q24[0] += ordinal;
        observe(&mut control, &item);
        let result = control
            .maintain_feature_history(8, DEFAULT_FEATURE_COLD_BYTE_LIMIT, Duration::from_secs(180))
            .expect("physical archive and compact");
        assert_eq!(result.archived_records, 1);
        assert_eq!(result.resident_feature_records, 1);
        assert_eq!(result.cold_records, ordinal as u64 + 1);
        assert!(result.journal_compacted);
        assert!(result.journal_bytes < 8192);
        originals.push(item);
        if ordinal % 8 == 0 {
            drop(control);
            control = DurableInferenceControl::open(&path, /*capacity*/ 2).expect("bounded replay");
        }
    }
    let cold = control.features.history.cold_bytes;
    let actual: u64 = std::fs::read_dir(path.with_file_name("control.log.feature-history-v1"))
        .expect("archive root")
        .flat_map(|first| std::fs::read_dir(first.expect("shard").path()).expect("shards"))
        .flat_map(|second| std::fs::read_dir(second.expect("shard").path()).expect("receipts"))
        .map(|entry| entry.expect("file").metadata().expect("metadata").len())
        .sum();
    assert_eq!(cold, actual);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 2).expect("restart");
    for item in originals {
        let expected = FeatureOperationRecordV1 {
            request: item.clone(),
            state: FeatureOperationStateV1::Observed(Box::new(receipt(&item))),
        };
        assert_eq!(
            control.feature_record(&item).expect("full cold query"),
            Some(expected.clone())
        );
        assert_eq!(
            control
                .reserve_feature(item.clone())
                .expect("idempotent cold reserve"),
            expected
        );
        assert!(matches!(
            control.dispatch_feature(&item),
            Err(Error::InvalidTransition)
        ));
        let mut changed = item.clone();
        changed.feature_vector_q24[0] += 1;
        assert!(matches!(
            control.feature_record(&changed),
            Err(Error::Conflict)
        ));
        assert!(matches!(
            control.reserve_feature(changed),
            Err(Error::Conflict)
        ));
    }
    assert_eq!(
        control
            .feature_record(&unknown)
            .expect("unknown stays hot")
            .expect("record")
            .state,
        FeatureOperationStateV1::Dispatched
    );
    assert_eq!(control.resident_feature_records(), 1);
}

#[test]
fn feature_cold_intent_and_file_commit_crash_cuts_resume_original_receipt() {
    for cut in 0..4 {
        let directory = private_directory();
        let path = directory.join("control.log");
        let item = request();
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("owner");
        observe(&mut control, &item);
        control
            .commit_feature_history(Event::Pin {
                limit: DEFAULT_FEATURE_COLD_BYTE_LIMIT,
            })
            .expect("pin");
        let record = control
            .features
            .records
            .get(item.request_id.as_str())
            .expect("hot");
        let prepared = archive_store::prepare(&path, record).expect("prepare original bytes");
        control
            .commit_feature_history(Event::Intent {
                intent: Intent {
                    request_id: item.request_id.to_string(),
                    record_digest: prepared.digest.clone(),
                    delta_bytes: prepared.delta_bytes,
                    temporary_bytes: prepared.temporary_bytes,
                },
            })
            .expect("durable intent before files");
        if cut > 0 {
            prepared
                .persist()
                .expect("files durable before retirement commit");
            if cut == 1 || cut == 3 {
                let key = Digest32::of_bytes(item.request_id.as_str().as_bytes()).to_string();
                let shard = path
                    .with_file_name("control.log.feature-history-v1")
                    .join(&key[..2])
                    .join(&key[2..4]);
                std::fs::remove_file(shard.join("identities.jsonl"))
                    .expect("cut after receipt before index");
                if cut == 3 {
                    use std::io::Write;
                    let blob = shard.join(format!("{key}.json"));
                    let raw = std::fs::read(&blob).expect("exact original archive bytes");
                    std::fs::remove_file(&blob).expect("cut before receipt rename");
                    let mut file = super::super::super::archive_store::private_options()
                        .create_new(true)
                        .write(true)
                        .open(blob.with_extension("feature-pending"))
                        .expect("partial temp");
                    file.write_all(&raw[..raw.len() / 2])
                        .expect("actual partial write");
                    file.sync_all().expect("durable partial prefix");
                }
                std::fs::File::open(shard)
                    .expect("directory")
                    .sync_all()
                    .expect("durable cut");
            }
        }
        assert!(
            control
                .compact_native_history(Instant::now(), Duration::from_secs(180))
                .expect("compact single pending intent with original hot receipt")
        );
        drop(control);
        let mut control =
            DurableInferenceControl::open(&path, /*capacity*/ 1).expect("recover cut");
        assert_eq!(control.resident_feature_records(), 1);
        assert_eq!(
            control
                .feature_record(&item)
                .expect("original query")
                .expect("record")
                .state,
            FeatureOperationStateV1::Observed(Box::new(receipt(&item)))
        );
        let report = control
            .maintain_feature_history(1, DEFAULT_FEATURE_COLD_BYTE_LIMIT, Duration::from_secs(10))
            .expect("resume existing intent");
        assert_eq!(report.archived_records, 1);
        assert_eq!(report.cold_records, 1);
        drop(control);
        let control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("cold reopen");
        assert_eq!(control.resident_feature_records(), 0);
        assert_eq!(
            control
                .feature_record(&item)
                .expect("full original receipt")
                .expect("record")
                .state,
            FeatureOperationStateV1::Observed(Box::new(receipt(&item)))
        );
    }
}

#[test]
fn feature_cold_byte_pressure_preserves_hot_receipt_and_does_not_write_archive() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let item = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("owner");
    observe(&mut control, &item);
    let record = control
        .features
        .records
        .get(item.request_id.as_str())
        .expect("hot");
    let prepared = archive_store::prepare(&path, record).expect("real byte cost");
    let limit = prepared.delta_bytes + prepared.temporary_bytes - 1;
    assert!(matches!(
        control.maintain_feature_history(1, limit, Duration::from_secs(10)),
        Err(Error::CapacityExceeded)
    ));
    assert!(
        !path
            .with_file_name("control.log.feature-history-v1")
            .exists()
    );
    assert_eq!(control.features.history.pending, None);
    drop(control);
    let control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("pressure restart");
    assert_eq!(control.feature_history_cold_byte_limit(), Some(limit));
    assert_eq!(
        control
            .feature_record(&item)
            .expect("original retained")
            .expect("record")
            .state,
        FeatureOperationStateV1::Observed(Box::new(receipt(&item)))
    );
}

#[test]
fn feature_cold_compaction_preserves_native_fences_and_shared_identity_namespace() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let item = request();
    let native = super::super::super::native::NativeRequest {
        request_id: "native.unresolved".into(),
        principal_id: "principal".into(),
        worker_generation: 1,
        model: "model".into(),
        payload_digest: Digest32::of_bytes(b"native").to_string(),
    };
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 2).expect("owner");
    let native_record = control
        .reserve_native(native.clone(), 1)
        .expect("native reservation");
    observe(&mut control, &item);
    control
        .maintain_feature_history(1, DEFAULT_FEATURE_COLD_BYTE_LIMIT, Duration::from_secs(10))
        .expect("mixed journal compact");
    drop(control);
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 2).expect("mixed restart");
    assert_eq!(
        control.native_record(&native.request_id),
        Some(&native_record)
    );
    let mut collision = native;
    collision.request_id = item.request_id.to_string();
    assert!(matches!(
        control.reserve_native(collision, 1),
        Err(Error::Conflict)
    ));
    assert_eq!(
        control
            .feature_record(&item)
            .expect("feature cold preserved")
            .expect("record")
            .state,
        FeatureOperationStateV1::Observed(Box::new(receipt(&item)))
    );
}

#[test]
fn feature_cold_missing_receipt_is_corruption_and_never_a_new_dispatch() {
    let directory = private_directory();
    let path = directory.join("control.log");
    let item = request();
    let mut control = DurableInferenceControl::open(&path, /*capacity*/ 1).expect("owner");
    observe(&mut control, &item);
    control
        .maintain_feature_history(1, DEFAULT_FEATURE_COLD_BYTE_LIMIT, Duration::from_secs(10))
        .expect("archive");
    let key = Digest32::of_bytes(item.request_id.as_str().as_bytes()).to_string();
    let blob = path
        .with_file_name("control.log.feature-history-v1")
        .join(&key[..2])
        .join(&key[2..4])
        .join(format!("{key}.json"));
    std::fs::remove_file(blob).expect("simulate lost cold storage");
    assert!(matches!(
        control.reserve_feature(item.clone()),
        Err(Error::CorruptJournal(_))
    ));
    drop(control);
    assert!(matches!(
        DurableInferenceControl::open(&path, /*capacity*/ 1),
        Err(Error::CorruptJournal(_))
    ));
}
