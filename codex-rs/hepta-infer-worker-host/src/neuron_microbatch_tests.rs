use codex_hepta_neuron::CompatibleModelIndexV1;
use codex_hepta_neuron::FeatureSnapshotV1;
use codex_hepta_neuron::HeadExecutionRequestV1;
use codex_hepta_neuron::LightweightHeadV1;
use codex_hepta_neuron::ReferenceBackendBatchV1;
use codex_hepta_neuron::RetiredIdRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::Mutex;

use super::*;

const Q24: i64 = 1 << 24;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn snapshot() -> FeatureSnapshotV1 {
    let features = vec![Q24 / 2, -Q24 / 4];
    FeatureSnapshotV1::new(
        digest("encoder"),
        generation(1),
        codex_hepta_neuron::canonical_feature_vector_digest_v1(&features),
        features,
    )
    .expect("snapshot")
}

fn backend() -> ReferenceBackendBatchV1 {
    let head = LightweightHeadV1 {
        head_digest: digest("head"),
        feature_width: 2,
        output_width: 2,
        weights_q24: vec![vec![Q24, 0], vec![0, Q24]],
        bias_q24: vec![0, 0],
    };
    let mut index = CompatibleModelIndexV1::new();
    index
        .register(id("head"), generation(1), digest("encoder"), head)
        .expect("model");
    ReferenceBackendBatchV1::new(index, RetiredIdRegistryV1::new())
}

fn requests() -> Vec<HeadExecutionRequestV1> {
    vec![HeadExecutionRequestV1 {
        request_id: id("request"),
        model_id: id("head"),
        generation: generation(1),
        snapshot: snapshot(),
    }]
}

#[test]
fn worker_executes_only_its_frozen_plan() {
    let worker = NeuronMicrobatchWorkerV1::new(id("worker"), generation(1), backend());
    let plan = worker.plan(10, 100, requests()).expect("plan");
    let execution = worker.execute(99, &plan).expect("execution");
    assert_eq!(execution.worker_id, id("worker"));
    assert_eq!(execution.outputs.len(), 1);
    assert_eq!(
        execution.authority,
        codex_hepta_types::AuthorityPosture::DENY_ALL
    );
    assert_ne!(execution.execution_digest, Digest32::ZERO);
}

#[test]
fn worker_rejects_plan_owner_generation_and_deadline_drift() {
    let worker = NeuronMicrobatchWorkerV1::new(id("worker"), generation(1), backend());
    let plan = worker.plan(10, 100, requests()).expect("plan");

    let other_worker = NeuronMicrobatchWorkerV1::new(id("other"), generation(1), backend());
    assert_eq!(
        other_worker.execute(99, &plan),
        Err(NeuronMicrobatchWorkerError::WorkerMismatch)
    );

    let next_generation = NeuronMicrobatchWorkerV1::new(id("worker"), generation(2), backend());
    assert_eq!(
        next_generation.execute(99, &plan),
        Err(NeuronMicrobatchWorkerError::GenerationMismatch)
    );
    assert_eq!(
        worker.execute(100, &plan),
        Err(NeuronMicrobatchWorkerError::DataPlane(
            DataPlaneError::InvalidMicrobatchPlan
        ))
    );
}

#[test]
fn worker_persists_a_durable_metric_for_each_production_batch() {
    let path = std::env::temp_dir().join(format!(
        "hepta-worker-metrics-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock")
            .as_nanos()
    ));
    let writer = codex_hepta_neuron::NeuronMetricsGroupCommitWriterV1::open(
        &path,
        digest("scope"),
        generation(1),
    )
    .expect("metrics writer");
    let writer = Arc::new(Mutex::new(writer));
    let worker = NeuronMicrobatchWorkerV1::new(id("worker"), generation(1), backend())
        .with_metrics_writer(Arc::clone(&writer));
    let plan = worker.plan(10, 100, requests()).expect("plan");
    worker.execute(99, &plan).expect("execute");
    assert_eq!(writer.lock().expect("lock").event_count(), 1);
    drop(worker);
    drop(writer);
    std::fs::remove_file(path).expect("cleanup");
}

#[test]
fn planner_rejects_empty_and_mixed_snapshot_batches() {
    let worker = NeuronMicrobatchWorkerV1::new(id("worker"), generation(1), backend());
    assert_eq!(
        worker.plan(10, 100, Vec::new()),
        Err(NeuronMicrobatchWorkerError::DataPlane(
            DataPlaneError::InvalidMicrobatchPlan
        ))
    );
    // Two requests with an identical semantic snapshot are a valid shared batch.
    let mut same_snapshot = requests();
    same_snapshot.push(HeadExecutionRequestV1 {
        request_id: id("request-2"),
        model_id: id("head"),
        generation: generation(1),
        snapshot: snapshot(),
    });
    let plan = worker
        .plan(10, 100, same_snapshot)
        .expect("identical snapshots form one shared-feature batch");
    assert_eq!(plan.requests().len(), 2);

    // Change an actual feature value: the old fixture duplicated the first
    // snapshot and therefore incorrectly expected a valid plan to be denied.
    let mut mixed = requests();
    let features = vec![Q24 / 2, -Q24 / 4 + 1];
    mixed.push(HeadExecutionRequestV1 {
        request_id: id("request-2"),
        model_id: id("head"),
        generation: generation(1),
        snapshot: FeatureSnapshotV1::new(
            digest("encoder"),
            generation(1),
            codex_hepta_neuron::canonical_feature_vector_digest_v1(&features),
            features,
        )
        .expect("snapshot"),
    });
    assert_eq!(
        worker.plan(10, 100, mixed),
        Err(NeuronMicrobatchWorkerError::DataPlane(
            DataPlaneError::InvalidMicrobatchPlan
        ))
    );

    let shared = snapshot();
    let oversized = (0..=codex_hepta_neuron::MAX_MICROBATCH_REQUESTS_V1)
        .map(|index| HeadExecutionRequestV1 {
            request_id: id(&format!("request-{index}")),
            model_id: id("head"),
            generation: generation(1),
            snapshot: shared.clone(),
        })
        .collect();
    assert_eq!(
        worker.plan(10, 100, oversized),
        Err(NeuronMicrobatchWorkerError::DataPlane(
            DataPlaneError::InvalidMicrobatchPlan
        ))
    );
}
