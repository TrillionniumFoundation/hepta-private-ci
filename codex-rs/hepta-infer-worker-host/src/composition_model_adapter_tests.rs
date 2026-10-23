use std::cell::RefCell;
use std::rc::Rc;

use super::*;
use crate::composition::CellHeadManifest;
use crate::composition::CompositionKey;
use crate::composition::CompositionRunObservation;
use crate::composition::SharedEncoderPool;

#[derive(Default)]
struct Counters {
    loads: u32,
    unloads: u32,
    runs: u32,
}

struct CountingDriver {
    counters: Rc<RefCell<Counters>>,
}

impl CompositionDriver for CountingDriver {
    type Handle = String;

    fn load_encoder(&mut self, key: &CompositionKey) -> Result<String, CompositionError> {
        self.counters.borrow_mut().loads += 1;
        Ok(key.weights_digest.clone())
    }

    fn unload_encoder(
        &mut self,
        _key: &CompositionKey,
        _handle: String,
    ) -> Result<(), CompositionError> {
        self.counters.borrow_mut().unloads += 1;
        Ok(())
    }

    fn run_head(
        &mut self,
        _handle: &String,
        head: &CellHeadManifest,
        request: &CompositionRequest,
    ) -> Result<CompositionRunObservation, CompositionError> {
        assert_eq!(head.cell_id, request.cell_id);
        self.counters.borrow_mut().runs += 1;
        Ok(CompositionRunObservation {
            output_digest: "e".repeat(64),
            consumed_tokens: request.maximum_tokens,
        })
    }
}

fn model(model_id: &str) -> ModelManifest {
    ModelManifest {
        model_id: model_id.to_owned(),
        model_digest: "a".repeat(64),
        weights_digest: "b".repeat(64),
        tokenizer_digest: "c".repeat(64),
        preprocessor_digest: "d".repeat(64),
        quantization_digest: "1".repeat(64),
        runtime_digest: "2".repeat(64),
        device_digest: "3".repeat(64),
        maximum_tokens: 128,
    }
}

fn composition(value: &ModelManifest, cell_id: &str) -> CompositionManifestV1 {
    CompositionManifestV1::from_model_manifest(
        value,
        cell_id.to_owned(),
        "4".repeat(64),
        "5".repeat(64),
        100,
        20,
    )
}

fn adapter(
    maximum_memory_bytes: u64,
) -> (
    CompositionModelDriverAdapter<CountingDriver>,
    Rc<RefCell<Counters>>,
) {
    let counters = Rc::new(RefCell::new(Counters::default()));
    let worker = CompositionWorker::new(
        SharedEncoderPool::new(2, 8).expect("pool"),
        CountingDriver {
            counters: counters.clone(),
        },
    );
    let grant = ResourceGrant {
        grant_id: "grant.1".into(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 100_000,
        revoked: false,
        maximum_models: 8,
        maximum_active_requests: 8,
        maximum_memory_bytes,
        semantic_digest: "6".repeat(64),
    };
    (
        CompositionModelDriverAdapter::new_qualification(1, worker, &grant).expect("qualification"),
        counters,
    )
}

fn request() -> WorkerRequest {
    WorkerRequest {
        request_id: "request.1".into(),
        reservation_id: "reservation.1".into(),
        model_digest: "a".repeat(64),
        payload_digest: "7".repeat(64),
        maximum_tokens: 16,
        deadline_ms: 1000,
        lease_payload_digest: "7".repeat(64),
        reservation_model_digest: "a".repeat(64),
        reservation_maximum_tokens: 16,
        cancelled: false,
    }
}

#[test]
fn one_encoder_two_heads_and_worker_wide_memory_receipts() {
    let (mut adapter, counts) = adapter(140);
    let model_a = model("model.a");
    let model_b = model("model.b");
    adapter
        .register_qualification_binding(model_a.clone(), composition(&model_a, "cell.a"))
        .expect("register a");
    adapter
        .register_qualification_binding(model_b.clone(), composition(&model_b, "cell.b"))
        .expect("register b");
    let a = adapter.load(&model_a).expect("load a");
    assert_eq!(a.observed_memory_bytes, 120);
    let b = adapter.load(&model_b).expect("load b");
    assert_eq!(b.observed_memory_bytes, 140);
    assert_eq!(adapter.resident_encoder_count(), 1);
    assert_eq!(counts.borrow().loads, 1);
    let observed = adapter.run(&b, &request()).expect("run b");
    assert_eq!(observed.observed_memory_bytes, 140);
    assert_eq!(observed.output_digest, Some("e".repeat(64)));
    assert_eq!(counts.borrow().runs, 1);
    adapter.unload(a).expect("unload a");
    assert_eq!(counts.borrow().unloads, 0);
    adapter.unload(b).expect("unload b");
    assert_eq!(counts.borrow().unloads, 1);
    assert_eq!(adapter.active_model_count(), 0);
}

#[test]
fn grant_blocks_third_head_before_any_mutation() {
    let (mut adapter, counts) = adapter(140);
    let mut handles = Vec::new();
    for i in 0..3 {
        let m = model(&format!("model.{i}"));
        adapter
            .register_qualification_binding(m.clone(), composition(&m, &format!("cell.{i}")))
            .expect("register");
        if i < 2 {
            handles.push(adapter.load(&m).expect("load"));
        } else {
            assert_eq!(adapter.load(&m), Err(Error::ModelCapacity));
        }
    }
    assert_eq!(adapter.active_model_count(), 2);
    assert_eq!(adapter.resident_encoder_count(), 1);
    assert_eq!(counts.borrow().loads, 1);
    for handle in handles {
        adapter.unload(handle).expect("unload");
    }
    assert_eq!(counts.borrow().unloads, 1);
}

#[test]
fn mismatched_explicit_binding_rejected() {
    let (mut adapter, _) = adapter(140);
    let m = model("model.a");
    let mut c = composition(&m, "cell.a");
    c.runtime_digest = "9".repeat(64);
    assert_eq!(
        adapter.register_qualification_binding(m, c),
        Err(Error::ModelMismatch)
    );
}

#[test]
fn fake_handle_and_mismatched_request_are_denied() {
    let (mut adapter, _) = adapter(140);
    let m = model("model.a");
    adapter
        .register_qualification_binding(m.clone(), composition(&m, "cell.a"))
        .expect("register");
    let handle = adapter.load(&m).expect("load");
    let fake = DriverModelHandle {
        opaque_id: "composition.handle.999".into(),
        observed_memory_bytes: 120,
    };
    assert_eq!(adapter.run(&fake, &request()), Err(Error::ModelNotLoaded));
    let mut wrong = request();
    wrong.model_digest = "f".repeat(64);
    assert_eq!(adapter.run(&handle, &wrong), Err(Error::ModelMismatch));
    let mut cancelled = request();
    cancelled.cancelled = true;
    assert_eq!(
        adapter.run(&handle, &cancelled),
        Err(Error::FeatureContract)
    );
    adapter.unload(handle).expect("unload");
}

#[test]
fn grant_expiry_and_revocation_are_rejected_before_construction() {
    let counter = Rc::new(RefCell::new(Counters::default()));
    let make_worker = || {
        CompositionWorker::new(
            SharedEncoderPool::new(1, 1).expect("pool"),
            CountingDriver {
                counters: counter.clone(),
            },
        )
    };
    let mut grant = ResourceGrant {
        grant_id: "grant.1".into(),
        authority_epoch: 1,
        generation: 1,
        expires_at_ms: 100,
        revoked: false,
        maximum_models: 1,
        maximum_active_requests: 1,
        maximum_memory_bytes: 1000,
        semantic_digest: "6".repeat(64),
    };
    assert!(matches!(
        CompositionModelDriverAdapter::new_qualification(100, make_worker(), &grant),
        Err(Error::GrantExpired)
    ));
    grant.revoked = true;
    assert!(matches!(
        CompositionModelDriverAdapter::new_qualification(1, make_worker(), &grant),
        Err(Error::GrantRevoked)
    ));
}
