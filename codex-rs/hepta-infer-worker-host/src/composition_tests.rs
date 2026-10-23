use super::*;

fn key(device: &str) -> CompositionKey {
    CompositionKey {
        encoder_digest: "encoder-v1".into(),
        weights_digest: "weights-v1".into(),
        tokenizer_digest: "tokenizer-v1".into(),
        preprocessor_digest: "preprocessor-v1".into(),
        normalization_digest: "normalization-v1".into(),
        quantization_digest: "quantization-v1".into(),
        runtime_digest: "runtime-v1".into(),
        device_digest: device.into(),
    }
}

fn head(cell_id: &str, bytes: u64) -> CellHeadManifest {
    CellHeadManifest {
        cell_id: cell_id.into(),
        head_digest: format!("head-{cell_id}"),
        private_memory_bytes: bytes,
        maximum_tokens: 128,
    }
}

#[derive(Default)]
struct WorkerDriver {
    loads: usize,
    unloads: usize,
    runs: usize,
}

impl CompositionDriver for WorkerDriver {
    type Handle = String;

    fn load_encoder(&mut self, key: &CompositionKey) -> Result<Self::Handle, CompositionError> {
        self.loads += 1;
        Ok(format!("encoder:{}", key.device_digest))
    }

    fn unload_encoder(
        &mut self,
        _key: &CompositionKey,
        _handle: Self::Handle,
    ) -> Result<(), CompositionError> {
        self.unloads += 1;
        Ok(())
    }

    fn run_head(
        &mut self,
        handle: &Self::Handle,
        head: &CellHeadManifest,
        request: &CompositionRequest,
    ) -> Result<CompositionRunObservation, CompositionError> {
        self.runs += 1;
        assert!(handle.starts_with("encoder:"));
        assert_eq!(head.cell_id, request.cell_id);
        Ok(CompositionRunObservation {
            output_digest: format!("output:{}", request.input_digest),
            consumed_tokens: request.maximum_tokens,
        })
    }
}

#[test]
fn composition_worker_loads_once_and_unloads_after_last_cell() {
    let pool = SharedEncoderPool::new(2, 8).expect("pool");
    let mut worker = CompositionWorker::new(pool, WorkerDriver::default());
    worker
        .attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    worker
        .attach_cell(key("cuda-0"), head("cell-b", 20), 100)
        .expect("second");
    assert_eq!(worker.driver.loads, 1);
    let observed = worker
        .run(CompositionRequest {
            cell_id: "cell-b".into(),
            input_digest: "input-1".into(),
            maximum_tokens: 16,
        })
        .expect("run");
    assert_eq!(observed.shared_memory_bytes, 100);
    assert_eq!(worker.driver.runs, 1);
    worker.detach_cell("cell-a").expect("detach first");
    assert_eq!(worker.driver.unloads, 0);
    worker.detach_cell("cell-b").expect("detach last");
    assert_eq!(worker.driver.unloads, 1);
    assert_eq!(worker.resident_encoder_count(), 0);
}

fn manifest(cell_id: &str, weights: &str) -> CompositionManifestV1 {
    CompositionManifestV1 {
        cell_id: cell_id.into(),
        encoder_digest: "encoder-v1".into(),
        weights_digest: weights.into(),
        tokenizer_digest: "tokenizer-v1".into(),
        preprocessor_digest: "preprocessor-v1".into(),
        normalization_digest: "normalization-v1".into(),
        quantization_digest: "quantization-v1".into(),
        runtime_digest: "runtime-v1".into(),
        device_digest: "cuda-0".into(),
        head_digest: format!("head-{cell_id}"),
        shared_memory_bytes: 100,
        private_memory_bytes: 20,
        maximum_tokens: 128,
    }
}

#[test]
fn manifest_bridge_binds_base_weights_and_private_head() {
    let mut worker = CompositionWorker::new(
        SharedEncoderPool::new(2, 8).expect("pool"),
        WorkerDriver::default(),
    );
    worker
        .attach_manifest(manifest("cell-a", "weights-v1"))
        .expect("manifest");
    worker
        .attach_manifest(manifest("cell-b", "weights-v1"))
        .expect("manifest");
    assert_eq!(worker.driver.loads, 1);
    assert_eq!(worker.active_cell_count(), 2);
    worker
        .attach_manifest(manifest("cell-c", "weights-v2"))
        .expect("new weights");
    assert_eq!(worker.driver.loads, 2);
    assert_eq!(worker.resident_encoder_count(), 2);
}

#[test]
fn legacy_model_manifest_bridge_preserves_runtime_identity() {
    let model = crate::model_worker::ModelManifest {
        model_id: "base.1".into(),
        model_digest: "a".repeat(64),
        weights_digest: "b".repeat(64),
        tokenizer_digest: "c".repeat(64),
        preprocessor_digest: "d".repeat(64),
        quantization_digest: "e".repeat(64),
        runtime_digest: "f".repeat(64),
        device_digest: "g".repeat(64),
        maximum_tokens: 128,
    };
    let manifest = CompositionManifestV1::from_model_manifest(
        &model,
        "cell-a".into(),
        "normalization-v1".into(),
        "head-a".into(),
        100,
        20,
    );
    manifest.validate().expect("composition manifest");
    assert_eq!(manifest.key().weights_digest, model.weights_digest);
    assert_eq!(manifest.key().tokenizer_digest, model.tokenizer_digest);
    assert_eq!(manifest.head().cell_id, "cell-a");
}

#[test]
fn worker_legacy_manifest_bridge_requires_explicit_composition_fields() {
    let model = crate::model_worker::ModelManifest {
        model_id: "base.1".into(),
        model_digest: "a".repeat(64),
        weights_digest: "b".repeat(64),
        tokenizer_digest: "c".repeat(64),
        preprocessor_digest: "d".repeat(64),
        quantization_digest: "e".repeat(64),
        runtime_digest: "f".repeat(64),
        device_digest: "g".repeat(64),
        maximum_tokens: 128,
    };
    let mut worker = CompositionWorker::new(
        SharedEncoderPool::new(2, 8).expect("pool"),
        WorkerDriver::default(),
    );
    let receipt = worker
        .attach_model_manifest(
            &model,
            "cell-a".into(),
            "normalization-v1".into(),
            "head-a".into(),
            100,
            20,
        )
        .expect("legacy manifest bridge");
    assert!(receipt.encoder_loaded);
    assert_eq!(receipt.shared_memory_bytes, 100);
    assert_eq!(receipt.private_head_memory_bytes, 20);
    assert_eq!(worker.active_cell_count(), 1);
    assert_eq!(worker.resident_encoder_count(), 1);
}

#[test]
fn shared_encoder_loads_once_and_heads_fan_out() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    let first = pool
        .attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    let second = pool
        .attach_cell(key("cuda-0"), head("cell-b", 20), 100)
        .expect("second");
    assert!(first.encoder_loaded);
    assert!(!second.encoder_loaded);
    assert_eq!(pool.resident_encoder_count(), 1);
    assert_eq!(pool.total_resident_memory_bytes().expect("memory"), 140);
    let fanout = pool
        .fanout(&key("cuda-0"), &["cell-a".into(), "cell-b".into()])
        .expect("fanout");
    assert_eq!(fanout.shared_memory_bytes, 100);
    assert_eq!(fanout.private_head_memory_bytes, 40);
}

#[test]
fn encoder_identity_includes_runtime_and_device() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    let second = pool
        .attach_cell(key("cuda-1"), head("cell-b", 20), 100)
        .expect("second");
    assert!(second.encoder_loaded);
    assert_eq!(pool.resident_encoder_count(), 2);
}

#[test]
fn mismatched_shared_bytes_are_rejected() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    assert_eq!(
        pool.attach_cell(key("cuda-0"), head("cell-b", 20), 101),
        Err(CompositionError::EncoderIdentityMismatch)
    );
}

#[test]
fn detached_last_cell_releases_encoder() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    pool.attach_cell(key("cuda-0"), head("cell-b", 20), 100)
        .expect("second");
    pool.detach_cell("cell-a").expect("detach first");
    assert_eq!(pool.resident_encoder_count(), 1);
    pool.detach_cell("cell-b").expect("detach last");
    assert_eq!(pool.resident_encoder_count(), 0);
    assert_eq!(pool.active_cell_count(), 0);
}

#[test]
fn fanout_rejects_cross_device_cell() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    pool.attach_cell(key("cuda-1"), head("cell-b", 20), 100)
        .expect("second");
    assert_eq!(
        pool.fanout(&key("cuda-0"), &["cell-a".into(), "cell-b".into()]),
        Err(CompositionError::CellKeyMismatch)
    );
}

#[test]
fn capacity_is_fail_closed() {
    let mut pool = SharedEncoderPool::new(1, 1).expect("pool");
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    assert_eq!(
        pool.attach_cell(key("cuda-1"), head("cell-b", 20), 100),
        Err(CompositionError::CellCapacity)
    );
    assert_eq!(
        pool.attach_cell(key("cuda-0"), head("cell-c", 20), 100),
        Err(CompositionError::CellCapacity)
    );
}
#[test]
fn attachment_rejects_memory_overflow_without_mutation() {
    let mut pool = SharedEncoderPool::new(2, 8).expect("pool");
    let maximum_shared_bytes = u64::MAX - 20;
    pool.attach_cell(key("cuda-0"), head("cell-a", 20), maximum_shared_bytes)
        .expect("first");
    assert_eq!(
        pool.attach_cell(key("cuda-0"), head("cell-b", 20), maximum_shared_bytes),
        Err(CompositionError::ArithmeticOverflow)
    );
    assert_eq!(pool.active_cell_count(), 1);
    assert_eq!(pool.encoder_reference_count(&key("cuda-0")), Ok(1));
    assert_eq!(pool.total_resident_memory_bytes(), Ok(u64::MAX));
}

#[test]
fn missing_handle_blocks_attach_and_detach_without_dropping_cell() {
    let mut worker = CompositionWorker::new(
        SharedEncoderPool::new(2, 8).expect("pool"),
        WorkerDriver::default(),
    );
    worker
        .attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("first");
    // Deliberately corrupt the internal driver map to test fail-closed handling.
    worker.handles.clear();
    assert_eq!(
        worker.attach_cell(key("cuda-0"), head("cell-b", 20), 100),
        Err(CompositionError::DriverFailure("missing encoder handle"))
    );
    assert_eq!(worker.active_cell_count(), 1);
    assert_eq!(
        worker.detach_cell("cell-a"),
        Err(CompositionError::DriverFailure("missing encoder handle"))
    );
    assert_eq!(worker.active_cell_count(), 1);
    assert_eq!(worker.resident_encoder_count(), 1);
}

#[test]
fn logical_cell_scale_has_one_resident_encoder_and_exact_head_charges() {
    // Logical lifecycle/ledger proof only. No physical GPU residency,
    // model accuracy, feature cache or measured inference throughput.
    for count in [8_usize, 64, 256, 1024] {
        let mut worker = CompositionWorker::new(
            SharedEncoderPool::new(1, count).expect("pool"),
            WorkerDriver::default(),
        );
        let mut cell_ids = Vec::new();
        for index in 0..count {
            let cell_id = format!("cell-{index}");
            worker
                .attach_cell(key("cuda-0"), head(&cell_id, 20), 100)
                .expect("attach");
            cell_ids.push(cell_id);
        }
        assert_eq!(worker.driver.loads, 1, "{count} logical Cells");
        assert_eq!(worker.resident_encoder_count(), 1);
        assert_eq!(worker.active_cell_count(), count);
        assert_eq!(
            worker.total_resident_memory_bytes(),
            Ok(100 + 20 * (count as u64)),
        );

        for cell_id in &cell_ids[..count - 1] {
            worker.detach_cell(cell_id).expect("detach nonfinal");
        }
        assert_eq!(worker.driver.unloads, 0, "{count} logical Cells");
        assert_eq!(worker.resident_encoder_count(), 1);
        worker
            .detach_cell(&cell_ids[count - 1])
            .expect("detach final");
        assert_eq!(worker.driver.unloads, 1);
        assert_eq!(worker.active_cell_count(), 0);
        assert_eq!(worker.resident_encoder_count(), 0);
        assert_eq!(worker.total_resident_memory_bytes(), Ok(0));
    }
}

struct FaultInjectingDriver {
    fail_load: bool,
    fail_unload: bool,
    successful_loads: usize,
}

impl CompositionDriver for FaultInjectingDriver {
    type Handle = String;

    fn load_encoder(&mut self, _key: &CompositionKey) -> Result<Self::Handle, CompositionError> {
        if self.fail_load {
            return Err(CompositionError::DriverFailure("injected load failure"));
        }
        self.successful_loads += 1;
        Ok("resident-handle".to_string())
    }

    fn unload_encoder(
        &mut self,
        _key: &CompositionKey,
        _handle: Self::Handle,
    ) -> Result<(), CompositionError> {
        if self.fail_unload {
            return Err(CompositionError::DriverFailure("injected unload failure"));
        }
        Ok(())
    }

    fn run_head(
        &mut self,
        _handle: &Self::Handle,
        _head: &CellHeadManifest,
        request: &CompositionRequest,
    ) -> Result<CompositionRunObservation, CompositionError> {
        Ok(CompositionRunObservation {
            output_digest: format!("output:{}", request.input_digest),
            consumed_tokens: request.maximum_tokens,
        })
    }
}

#[test]
fn encoder_load_failure_rolls_back_new_cell_and_resident_record() {
    let mut worker = CompositionWorker::new(
        SharedEncoderPool::new(1, 2).expect("pool"),
        FaultInjectingDriver {
            fail_load: true,
            fail_unload: false,
            successful_loads: 0,
        },
    );
    assert_eq!(
        worker.attach_cell(key("cuda-0"), head("cell-a", 20), 100),
        Err(CompositionError::DriverFailure("injected load failure"))
    );
    assert_eq!(worker.active_cell_count(), 0);
    assert_eq!(worker.resident_encoder_count(), 0);
    assert!(worker.handles.is_empty());
    assert_eq!(worker.total_resident_memory_bytes(), Ok(0));
}

#[test]
fn last_cell_unload_failure_preserves_cell_and_handle_for_retry() {
    let mut worker = CompositionWorker::new(
        SharedEncoderPool::new(1, 2).expect("pool"),
        FaultInjectingDriver {
            fail_load: false,
            fail_unload: true,
            successful_loads: 0,
        },
    );
    worker
        .attach_cell(key("cuda-0"), head("cell-a", 20), 100)
        .expect("load");
    assert_eq!(
        worker.detach_cell("cell-a"),
        Err(CompositionError::DriverFailure("injected unload failure"))
    );
    assert_eq!(worker.active_cell_count(), 1);
    assert_eq!(worker.resident_encoder_count(), 1);
    assert_eq!(worker.handles.len(), 1);
    assert_eq!(worker.total_resident_memory_bytes(), Ok(120));
    worker.driver.fail_unload = false;
    worker.detach_cell("cell-a").expect("retry detach");
    assert!(worker.handles.is_empty());
    assert_eq!(worker.total_resident_memory_bytes(), Ok(0));
}
