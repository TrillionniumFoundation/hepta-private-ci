//! Wire-boundary controls only; these explicit JSON fixtures are not model runs.
#[path = "smollm_neural_initial_journal_tests.rs"]
mod initial_journal;

use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn hash(label: &str) -> String {
    Digest32::of_bytes(label.as_bytes()).to_string()
}
fn denied() -> Value {
    json!({"installation_authorized":false,"selection_authorized":false,
        "independent_accepted":false,"prospective_accepted":false,
        "public_reward_eligible":false,"hepta_final_use":false})
}
fn ready() -> Value {
    json!({"schema":SCHEMA,"actual_loaded_parent":hash("actual adapter"),
        "file_sha256":hash("actual parameter file"),
        "contract":"2bb480a2becd44b7f4e4b03e557e270ed92a4bb952e0a634562d23d7f0f97e46",
        "generation":2,
        "backbone":"c320c094769446c21d7e4a33795d7f9310b5e4c8ca5a6fecca40207b1f735b7c",
        "tokenizer":"a1883207efeacecee399f4dc699d2b547eb2d6ddb7500522933ed76c1521fb93",
        "source_pins":{"explicit-source-boundary-fixture":hash("source")},
        "worker_source":hash("worker"),"actions":[],"observed_rss_bytes":1234,
        "authority":denied()})
}
fn admitted(id: &str) -> Admitted {
    Admitted {
        request_id: id.to_owned(),
        reservation_id: format!("reservation-{id}"),
        payload_digest: hash("control payload fixture"),
        deadline_ms: 1,
        revision: 1,
    }
}
fn response() -> Value {
    json!({"schema":SCHEMA,"request_id":"original-query",
        "input_sha256":hash("actual input frame"),"file_sha256":hash("actual parameter file"),
        "artifact":hash("actual adapter"),
        "contract":"2bb480a2becd44b7f4e4b03e557e270ed92a4bb952e0a634562d23d7f0f97e46",
        "profile":super::super::PROFILE,"action_ids":["action"],"scores_q32":[123],
        "input_tokens":17,"logits_sha256":hash("actual logits"),
        "execution_ns":2345,"observed_rss_bytes":5678,"authority":denied()})
}
fn bytes(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).unwrap()
}

#[test]
fn fixed_backbone_proof_checks_observed_roots_and_original_settled_load() {
    let mut observations = Measurements::default();
    let raw = bytes(&ready());
    observations.retain_ready(&raw).unwrap();
    assert!(observations.observe(|_, _| ()).is_err());
    assert!(
        observations
            .ready
            .as_ref()
            .unwrap()
            .fixed_initial_backbone()
            .is_err()
    );
    observations.settle_load(&admitted("original-load"));
    observations
        .observe(|load, forward| {
            let proof = load.fixed_initial_backbone().unwrap();
            assert_eq!(proof.measured().ready_digest(), Digest32::of_bytes(&raw));
            assert_eq!(
                proof.measured().parameter_file_digest().to_string(),
                ready()["file_sha256"]
            );
            assert_eq!(
                load.control_load_ids(),
                Some(("original-load", "reservation-original-load"))
            );
            assert!(forward.is_none());
        })
        .unwrap();
    for root in ["backbone", "tokenizer", "contract"] {
        let mut other = ready();
        other[root] = json!(hash("different actual root"));
        observations.retain_ready(&bytes(&other)).unwrap();
        observations.settle_load(&admitted("other-original-load"));
        assert!(
            observations
                .observe(|load, _| load.fixed_initial_backbone().is_err())
                .unwrap()
        );
    }
}

#[test]
fn actual_forward_frame_hash_and_original_control_ids_refuse_mixed_observations() {
    let mut observations = Measurements::default();
    observations.retain_ready(&bytes(&ready())).unwrap();
    observations.settle_load(&admitted("original-load"));
    let raw = bytes(&response());
    let receipt = Digest32::of_bytes(&raw);
    observations
        .retain_forward(&admitted("original-query"), &raw, receipt)
        .unwrap();
    observations
        .observe(|load, forward| {
            let forward = forward.unwrap();
            assert_eq!(forward.ready_digest(), load.ready_digest());
            assert_eq!(
                forward.control_ids(),
                ("original-query", "reservation-original-query")
            );
            assert_eq!(forward.response_digest(), receipt);
            assert_eq!(
                (
                    forward.execution_ns(),
                    forward.input_tokens(),
                    forward.observed_rss_bytes()
                ),
                (2345, 17, 5678)
            );
        })
        .unwrap();
    assert!(
        observations
            .retain_forward(&admitted("another-query"), &raw, receipt)
            .is_err()
    );
    assert!(
        observations
            .observe(|_, forward| forward.is_none())
            .unwrap()
    );
    assert!(
        observations
            .retain_forward(
                &admitted("original-query"),
                &raw,
                Digest32::of_bytes(b"another raw response")
            )
            .is_err()
    );
    for field in ["artifact", "file_sha256", "contract"] {
        let mut altered = response();
        altered[field] = json!(hash("mixed observed material"));
        let altered = bytes(&altered);
        assert!(
            observations
                .retain_forward(
                    &admitted("original-query"),
                    &altered,
                    Digest32::of_bytes(&altered)
                )
                .is_err()
        );
    }
}

#[test]
fn authority_unknown_fields_and_bounds_cannot_be_minted_as_measurement() {
    let mut observations = Measurements::default();
    let mut altered = ready();
    altered["authority"]["hepta_final_use"] = json!(true);
    assert!(observations.retain_ready(&bytes(&altered)).is_err());
    let mut altered = ready();
    altered["expected_backbone"] = json!(hash("untrusted expectation"));
    assert!(observations.retain_ready(&bytes(&altered)).is_err());
    assert!(observations.retain_ready(&vec![b' '; 65537]).is_err());
    observations.retain_ready(&bytes(&ready())).unwrap();
    observations.settle_load(&admitted("original-load"));
    let mut altered = response();
    altered["authority"]["hepta_final_use"] = json!(true);
    let altered = bytes(&altered);
    assert!(
        observations
            .retain_forward(
                &admitted("original-query"),
                &altered,
                Digest32::of_bytes(&altered)
            )
            .is_err()
    );
    assert!(
        observations
            .retain_forward(
                &admitted("original-query"),
                &vec![b' '; 128 * 1024 + 1],
                Digest32::ZERO
            )
            .is_err()
    );
}

#[test]
fn replacement_and_terminal_clear_keep_one_ready_and_one_forward_only() {
    let mut observations = Measurements::default();
    observations.retain_ready(&bytes(&ready())).unwrap();
    observations.settle_load(&admitted("original-load"));
    let raw = bytes(&response());
    observations
        .retain_forward(&admitted("original-query"), &raw, Digest32::of_bytes(&raw))
        .unwrap();
    observations.clear_forward();
    assert!(
        observations
            .observe(|_, forward| forward.is_none())
            .unwrap()
    );
    observations.retain_ready(&bytes(&ready())).unwrap();
    assert!(observations.observe(|_, _| ()).is_err());
    observations.settle_load(&admitted("new-original-load"));
    assert_eq!(
        observations
            .observe(|load, _| load.control_load_ids().unwrap().0.to_owned())
            .unwrap(),
        "new-original-load"
    );
    observations.suspend();
    assert!(observations.ready.is_some());
    assert!(observations.observe(|_, _| ()).is_err());
    observations.settle_load(&admitted("cannot-rebind-an-old-load"));
    assert!(observations.observe(|_, _| ()).is_err());
    assert_eq!(
        observations.ready.as_ref().unwrap().control_load_ids(),
        Some(("new-original-load", "reservation-new-original-load"))
    );
    observations.clear();
    assert!(observations.observe(|_, _| ()).is_err());
}

#[test]
fn settled_load_output_is_separate_from_ready_and_cannot_rebind() {
    let mut observations = Measurements::default();
    let raw = bytes(&ready());
    let original = admitted("original-load");
    let output = Digest32::of_parts(&[
        b"hepta.smollm-loaded.v1\0",
        b"explicit fixture handle",
        &1234_u64.to_be_bytes(),
    ]);
    observations.retain_ready(&raw).unwrap();
    observations.settle_load(&original);
    assert!(
        observations
            .ready
            .as_ref()
            .unwrap()
            .settled_load_output_digest()
            .is_none()
    );
    assert!(
        observations
            .settle_load_output(&admitted("other-load"), output)
            .is_err()
    );
    observations.settle_load_output(&original, output).unwrap();
    observations
        .observe(|load, _| {
            assert_eq!(load.ready_digest(), Digest32::of_bytes(&raw));
            assert_eq!(load.settled_load_output_digest(), Some(output));
            assert_ne!(load.ready_digest(), output);
            assert_eq!(
                load.control_load_ids(),
                Some(("original-load", "reservation-original-load"))
            );
        })
        .unwrap();
    assert!(
        observations
            .settle_load_output(&original, Digest32::of_bytes(b"other output"))
            .is_err()
    );
    assert_eq!(
        observations
            .ready
            .as_ref()
            .unwrap()
            .settled_load_output_digest(),
        Some(output)
    );
    observations.clear();
    assert!(observations.observe(|_, _| ()).is_err());
}
