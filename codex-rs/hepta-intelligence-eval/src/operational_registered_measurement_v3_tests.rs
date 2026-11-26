use super::*;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;
use serde_json::json;

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"actual unchanged head"),
        normalization_digest: Digest32::of_bytes(b"actual input normalization"),
        generation: Generation::new(2).unwrap(),
        width: 10,
        top_k: 1,
        temporal_decay_q24: 1 << 23,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: 1 << 23,
        target_activity_q24: 1 << 21,
        threshold_rate_q24: 1 << 18,
        threshold_min_q24: -(1 << 24),
        threshold_max_q24: 1 << 24,
        eligibility_decay_q24: 1 << 23,
    }
}
fn rows() -> Vec<(serde_json::Value, bool)> {
    (0..20)
        .map(|i| {
            (
                json!({"input_digest":Digest32::of_bytes(&[i]).to_string(),
        "drive_q24":[1<<24,0,0,0,0,0,0,0,0,0],"prediction_q24":[0,0,0,0,0,0,0,0,0,0]}),
                true,
            )
        })
        .collect()
}
#[test]
fn registered_sparse_replay_is_complete_repeatable_and_parameter_sensitive() {
    let native = config();
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"enrolled subject"),
        objective_digest: Digest32::of_bytes(b"current training objective"),
    };
    let body = Digest32::of_bytes(b"actual registered body");
    let original = replay_sparse(&native, scope, body, &rows()).unwrap();
    let again = replay_sparse(&native, scope, body, &rows()).unwrap();
    assert_eq!(original.0, again.0);
    assert!(original.0.all_require_calibration);
    assert!(original.1.resident_high_water_bytes > 0);
    let mut changed = native.clone();
    changed.temporal_decay_q24 = 1 << 22;
    assert_ne!(
        original.0,
        replay_sparse(&changed, scope, body, &rows()).unwrap().0
    );
    let mut foreign_scope = scope;
    foreign_scope.objective_digest = Digest32::of_bytes(b"another objective");
    assert_ne!(
        original.0,
        replay_sparse(&native, foreign_scope, body, &rows())
            .unwrap()
            .0
    );
}
#[test]
fn registered_sparse_replay_rejects_partial_non_numeric_or_wrong_width_rows() {
    let native = config();
    let scope = JournalScope {
        scope_digest: Digest32::of_bytes(b"subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    };
    let body = Digest32::of_bytes(b"body");
    for field in ["input_digest", "drive_q24", "prediction_q24"] {
        let mut values = rows();
        values[4].0.as_object_mut().unwrap().remove(field);
        assert!(replay_sparse(&native, scope, body, &values).is_err());
    }
    let mut values = rows();
    values[3].0["prediction_q24"] = json!(["0"]);
    assert!(replay_sparse(&native, scope, body, &values).is_err());
    assert!(replay_sparse(&native, scope, body, &[]).is_err());
}
