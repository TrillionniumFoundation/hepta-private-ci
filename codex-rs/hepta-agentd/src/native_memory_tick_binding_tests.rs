use super::*;
use std::io::Write;
use std::process::{Command, Stdio};
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use std::assert_eq;
use crate::native_memory_test_support::fixture;

#[tokio::test]
async fn native_tick_binding_preserves_model_tuple_and_rejects_rebinding() {
    let f = fixture().await;
    let mut port = NativeMemoryModelPort::new(f.writer, f.admission, f.config,
        tokio::runtime::Handle::current(), Arc::new(AtomicU64::new(0)),
        tokio_util::sync::CancellationToken::new()).unwrap();
    let mut request = port.request();
    let input = NeuronTickInputV1 {
        tick_id: request.request_id.clone(), subject_id: StableId::new("subject:fixture").unwrap(),
        logical_sequence: 1, monotonic_time_micros: 10, checkpoint_digest: Digest32::ZERO,
        input_feature_digest: canonical_feature_vector_digest_v1(&request.feature_vector_q24),
        feature_vector_q24: request.feature_vector_q24.clone(),
        objective_digest: Digest32::of_bytes(b"controlled objective fixture"),
        ndu_snapshot_digest: Digest32::of_bytes(b"controlled NDU fixture"),
        body_generation: None, modulator_digest: None,
    };
    request.input_digest = input.semantic_digest().unwrap();
    let mut wrong = request.clone();
    wrong.weights_digest = Digest32::of_bytes(b"substituted weights");
    assert!(port.bind_tick(&input, &wrong).is_err());
    port.bind_tick(&input, &request).unwrap();
    assert_eq!(port.request(), request);
    assert!(port.bind_tick(&input, &request).is_err());
}

#[tokio::test]
async fn native_tick_wire_matches_python_and_tampered_live_context_is_rejected() {
    let f = fixture().await;
    let port = NativeMemoryModelPort::new(f.writer, Arc::clone(&f.admission), f.config,
        tokio::runtime::Handle::current(), Arc::new(AtomicU64::new(0)),
        tokio_util::sync::CancellationToken::new()).unwrap();
    let helper = codex_utils_cargo_bin::find_resource!("../../scripts/memory_cell_native/native_tick_interop.py")
        .expect("declared interop resource must exist");
    for body_generation in [None, Some(7)] {
        let mut request = port.request();
        let input = NeuronTickInputV1 {
            tick_id: request.request_id.clone(), subject_id: StableId::new("subject:interop").unwrap(),
            logical_sequence: 1, monotonic_time_micros: 1234, checkpoint_digest: Digest32::ZERO,
            input_feature_digest: canonical_feature_vector_digest_v1(&request.feature_vector_q24),
            feature_vector_q24: request.feature_vector_q24.clone(),
            objective_digest: Digest32::of_bytes(b"controlled objective fixture"),
            ndu_snapshot_digest: Digest32::of_bytes(b"controlled NDU fixture"),
            body_generation,
            modulator_digest: body_generation.map(|_| Digest32::of_bytes(b"controlled modulator")),
        };
        request.input_digest = input.semantic_digest().unwrap();
        let binding = NativeTickBindingV1::new(&input, f.admission.binding()).unwrap();
        let document = serde_json::json!({
            "schema": "hepta.memory-cell.native-request.v2",
            "query_digest": f.admission.binding().query_digest.to_string(),
            "source_binding_digest": f.admission.binding().binding_digest.to_string(),
            "neuron_request": NativeNeuronRequestV1::from(&request), "tick_binding": binding,
        });
        for tampered in [false, true] {
            let mut supplied = document.clone();
            if tampered { supplied["tick_binding"]["ndu_snapshot_digest"] =
                serde_json::json!(Digest32::of_bytes(b"later NDU fixture").to_string()); }
            let mut child = Command::new(if cfg!(windows) { "python" } else { "python3" })
                .args(["-I", "-S", "-B"]).arg(&helper)
                .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped())
                .spawn().expect("Python is required for wire qualification; absence is not a pass");
            child.stdin.take().unwrap().write_all(&serde_json::to_vec(&supplied).unwrap()).unwrap();
            let output = child.wait_with_output().unwrap();
            if tampered {
                assert!(!output.status.success());
                assert!(String::from_utf8_lossy(&output.stderr).contains("source/query/full tick binding mismatch"));
            } else {
                assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
                assert_eq!(serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap(),
                    serde_json::json!({"tick_digest": request.input_digest.to_string()}));
            }
        }
    }
}
