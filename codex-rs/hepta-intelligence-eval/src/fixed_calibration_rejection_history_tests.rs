use super::*;

fn original() -> (Value, Value, Digest32, Digest32) {
    let config = Digest32::of_bytes(b"original config");
    let result = Digest32::of_bytes(b"independent result");
    let request = serde_json::json!({"schema":"original pinned request"});
    let completion = serde_json::json!({
        "schema":"hepta.fixed-calibration-cycle.completed.v1", "scope":"calibration-only",
        "config_digest":config.to_string(), "independent_result_digest":result.to_string(),
        "original_inputs":request, "native_started_at_ms":10, "completed_at_ms":20,
        "qualified":false, "holdout_consumed":false, "production_activation":false,
        "authority_grants_any":false,
    });
    (completion, request, config, result)
}

#[test]
fn old_completion_retains_historical_time_but_never_accepts_effect_flags_or_changed_pins()
-> HostResult<()> {
    let (completion, request, config, result) = original();
    assert_eq!(
        validate_completion(&completion, config, &request, result, 50_000)?,
        20
    );
    for flag in [
        "qualified",
        "holdout_consumed",
        "production_activation",
        "authority_grants_any",
    ] {
        let mut changed = completion.clone();
        changed[flag] = serde_json::json!(true);
        assert!(validate_completion(&changed, config, &request, result, 50_000).is_err());
    }
    assert!(
        validate_completion(
            &completion,
            Digest32::of_bytes(b"different config"),
            &request,
            result,
            50_000
        )
        .is_err()
    );
    assert!(
        validate_completion(
            &completion,
            config,
            &request,
            Digest32::of_bytes(b"different result"),
            50_000
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn future_completion_changed_original_request_and_reversed_clock_fail_before_historical_authentication()
 {
    let (completion, request, config, result) = original();
    assert!(validate_completion(&completion, config, &request, result, 19).is_err());
    assert!(
        validate_completion(
            &completion,
            config,
            &serde_json::json!({"changed":true}),
            result,
            50
        )
        .is_err()
    );
    let mut reversed = completion;
    reversed["native_started_at_ms"] = serde_json::json!(21);
    assert!(validate_completion(&reversed, config, &request, result, 50).is_err());
}
