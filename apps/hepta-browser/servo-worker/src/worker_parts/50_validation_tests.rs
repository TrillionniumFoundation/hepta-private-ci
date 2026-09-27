fn validate_action_target(
    action: &Map<String, Value>,
    observation: &Value,
) -> Result<(), String> {
    let kind = action
        .get("kind")
        .and_then(Value::as_str)
        .ok_or_else(|| "typedAction.kind must be a string".to_string())?;
    if !matches!(kind, "click" | "type" | "focus") {
        return Ok(());
    }
    let selector = action
        .get("selector")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{kind}.selector must be a string"))?;
    let control = observed_control(observation, selector)?
        .ok_or_else(|| "typed action selector is not in the admitted action surface".to_string())?;
    let disabled = control
        .get("disabled")
        .and_then(Value::as_bool)
        .ok_or_else(|| "semantic observation control.disabled must be boolean".to_string())?;
    if disabled {
        return Err("typed action selector is disabled in the admitted action surface".to_string());
    }
    let tag = control
        .get("tag")
        .and_then(Value::as_str)
        .ok_or_else(|| "semantic observation control.tag must be a string".to_string())?;
    let input_type = control
        .get("type")
        .and_then(Value::as_str)
        .ok_or_else(|| "semantic observation control.type must be a string".to_string())?;
    if kind == "click"
        && tag.eq_ignore_ascii_case("input")
        && input_type.eq_ignore_ascii_case("file")
    {
        return Err("file chooser capability is not connected".to_string());
    }
    if kind == "type" {
        if tag.eq_ignore_ascii_case("input") {
            if input_type.eq_ignore_ascii_case("password") {
                return Err("generic type action cannot target a password control".to_string());
            }
            let normalized = input_type.to_ascii_lowercase();
            if !matches!(normalized.as_str(), "" | "text" | "search" | "email" | "url" | "tel") {
                return Err("type action target is not a supported text-entry control".to_string());
            }
        } else if !tag.eq_ignore_ascii_case("textarea") {
            return Err("type action target is not a text-entry control".to_string());
        }
        let read_only = control
            .get("readOnly")
            .and_then(Value::as_bool)
            .ok_or_else(|| "semantic observation control.readOnly must be boolean".to_string())?;
        if read_only {
            return Err("type action target is read-only".to_string());
        }
    }
    Ok(())
}

fn validate_dispatch_snapshot_state(
    payload: &Value,
    action_kind: &str,
    worker_page_generation: u64,
    last_document_digest: Option<&str>,
    observed_navigation_epoch: Option<u64>,
    current_navigation_epoch: u64,
) -> Result<(), String> {
    let requested_page_generation = payload
        .get("pageGeneration")
        .and_then(Value::as_u64)
        .filter(|value| *value <= MAX_SAFE_INTEGER)
        .ok_or_else(|| "dispatch.pageGeneration must be a safe non-negative integer".to_string())?;
    let document = payload
        .get("documentDigest")
        .ok_or_else(|| "dispatch.documentDigest is missing".to_string())?;
    let bootstrap_navigation = action_kind == "navigate" && requested_page_generation == 0;
    if bootstrap_navigation {
        if worker_page_generation != 0 || !document.is_null() {
            return Err("bootstrap navigation snapshot is stale".to_string());
        }
        return Ok(());
    }
    if requested_page_generation == 0 || requested_page_generation != worker_page_generation {
        return Err("worker page generation drifted before dispatch".to_string());
    }
    let requested_document_digest = document
        .as_str()
        .filter(|value| is_digest(value))
        .ok_or_else(|| "dispatch.documentDigest must be a non-zero SHA-256 digest".to_string())?;
    if last_document_digest != Some(requested_document_digest) {
        return Err("worker document digest drifted before dispatch".to_string());
    }
    let observed_epoch = observed_navigation_epoch
        .ok_or_else(|| "worker has no admitted semantic observation for dispatch".to_string())?;
    if observed_epoch != current_navigation_epoch {
        return Err("worker navigation epoch drifted before dispatch".to_string());
    }
    Ok(())
}

fn validate_safe_json(value: &Value, depth: usize) -> Result<(), String> {
    if depth > 32 {
        return Err("private channel JSON nesting exceeds limit".to_string());
    }
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => Ok(()),
        Value::Number(number) => {
            if number
                .as_i64()
                .is_some_and(|value| value.unsigned_abs() <= MAX_SAFE_INTEGER)
                || number.as_u64().is_some_and(|value| value <= MAX_SAFE_INTEGER)
            {
                Ok(())
            } else {
                Err("private channel numbers must be safe integers".to_string())
            }
        }
        Value::Array(values) => values
            .iter()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
        Value::Object(object) => object
            .values()
            .try_for_each(|value| validate_safe_json(value, depth + 1)),
    }
}

fn canonical_json(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(value) => value.to_string(),
        Value::Number(value) => value.to_string(),
        Value::String(value) => serde_json::to_string(value).expect("string serialization cannot fail"),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(canonical_json).collect::<Vec<_>>().join(",")
        ),
        Value::Object(object) => {
            let mut keys: Vec<_> = object.keys().collect();
            keys.sort();
            let fields = keys
                .into_iter()
                .map(|key| format!("{}:{}", serde_json::to_string(key).unwrap(), canonical_json(&object[key])))
                .collect::<Vec<_>>()
                .join(",");
            format!("{{{fields}}}")
        }
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}

fn stable_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn navigation_requests_are_scoped_to_the_current_effect_origin() {
        let allowed = HashSet::from([
            "https://a.example".to_string(),
            "https://b.example".to_string(),
        ]);
        let blank = Url::parse("about:blank").expect("about blank");
        let a = Url::parse("https://a.example/path").expect("origin a");
        let b = Url::parse("https://b.example/path").expect("origin b");

        assert!(navigation_request_allowed(&blank, &allowed, None));
        assert!(!navigation_request_allowed(&a, &allowed, None));
        assert!(navigation_request_allowed(
            &a,
            &allowed,
            Some("https://a.example")
        ));
        assert!(!navigation_request_allowed(
            &b,
            &allowed,
            Some("https://a.example")
        ));
    }

    #[test]
    fn dispatch_snapshot_rejects_generation_document_and_navigation_drift() {
        let digest = "1".repeat(64);
        let payload = json!({
            "pageGeneration": 7,
            "documentDigest": digest,
        });
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(digest.as_str()),
                Some(11),
                11,
            )
            .is_ok()
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                8,
                Some(digest.as_str()),
                Some(11),
                11,
            )
            .unwrap_err()
            .contains("page generation")
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(&"2".repeat(64)),
                Some(11),
                11,
            )
            .unwrap_err()
            .contains("document digest")
        );
        assert!(
            validate_dispatch_snapshot_state(
                &payload,
                "click",
                7,
                Some(digest.as_str()),
                Some(11),
                12,
            )
            .unwrap_err()
            .contains("navigation epoch")
        );
    }

    #[test]
    fn action_surface_digest_ignores_visible_text_but_tracks_actionable_drift() {
        let base = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title A",
            "visibleText": "dynamic counter 1",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":false,"readOnly":false,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        let text_changed = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title B",
            "visibleText": "dynamic counter 2",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":false,"readOnly":false,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        let control_changed = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title B",
            "visibleText": "dynamic counter 2",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":true,"readOnly":false,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        let readonly_changed = json!({
            "schema": "hepta.browser.semantic-observation.v1",
            "title": "Title B",
            "visibleText": "dynamic counter 2",
            "links": [{"text":"A","href":"https://example.com/a","selector":"a:nth-of-type(1)"}],
            "controls": [{"selector":"button:nth-of-type(1)","tag":"button","role":"","type":"","name":"","ariaLabel":"Go","placeholder":"","disabled":false,"readOnly":true,"checked":false}],
            "forms": [],
            "viewport": {"width":1280,"height":720},
            "truncated": false,
        });
        assert_eq!(
            action_surface_digest(&base).expect("base digest"),
            action_surface_digest(&text_changed).expect("text digest"),
        );
        assert_ne!(
            action_surface_digest(&base).expect("base digest"),
            action_surface_digest(&control_changed).expect("control digest"),
        );
        assert_ne!(
            action_surface_digest(&base).expect("base digest"),
            action_surface_digest(&readonly_changed).expect("readonly digest"),
        );
    }

    #[test]
    fn page_local_action_selector_must_be_observed_and_sensitive_targets_fail_closed() {
        let observation = json!({
            "controls": [
                {"selector":"button:nth-of-type(1)","tag":"button","type":"","disabled":false,"readOnly":false},
                {"selector":"input:nth-of-type(1)","tag":"input","type":"text","disabled":false,"readOnly":false},
                {"selector":"input:nth-of-type(2)","tag":"input","type":"password","disabled":false,"readOnly":false},
                {"selector":"input:nth-of-type(3)","tag":"input","type":"text","disabled":true,"readOnly":false},
                {"selector":"input:nth-of-type(4)","tag":"input","type":"checkbox","disabled":false,"readOnly":false},
                {"selector":"input:nth-of-type(5)","tag":"input","type":"text","disabled":false,"readOnly":true},
                {"selector":"input:nth-of-type(6)","tag":"input","type":"file","disabled":false,"readOnly":false},
                {"selector":"textarea:nth-of-type(1)","tag":"textarea","type":"","disabled":false,"readOnly":false}
            ]
        });

        let click_value = json!({"kind":"click","selector":"button:nth-of-type(1)"});
        assert!(validate_action_target(
            click_value.as_object().expect("click object"),
            &observation,
        ).is_ok());

        let missing_value = json!({"kind":"click","selector":"#not-observed"});
        assert!(validate_action_target(
            missing_value.as_object().expect("missing object"),
            &observation,
        )
        .unwrap_err()
        .contains("not in the admitted action surface"));

        let password_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(2)",
            "text":"secret"
        });
        assert!(validate_action_target(
            password_value.as_object().expect("password object"),
            &observation,
        )
        .unwrap_err()
        .contains("password"));

        let disabled_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(3)",
            "text":"blocked"
        });
        assert!(validate_action_target(
            disabled_value.as_object().expect("disabled object"),
            &observation,
        )
        .unwrap_err()
        .contains("disabled"));

        let checkbox_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(4)",
            "text":"not-text"
        });
        assert!(validate_action_target(
            checkbox_value.as_object().expect("checkbox object"),
            &observation,
        )
        .unwrap_err()
        .contains("supported text-entry"));

        let readonly_value = json!({
            "kind":"type",
            "selector":"input:nth-of-type(5)",
            "text":"blocked"
        });
        assert!(validate_action_target(
            readonly_value.as_object().expect("readonly object"),
            &observation,
        )
        .unwrap_err()
        .contains("read-only"));

        let file_click = json!({
            "kind":"click",
            "selector":"input:nth-of-type(6)"
        });
        assert!(validate_action_target(
            file_click.as_object().expect("file click object"),
            &observation,
        )
        .unwrap_err()
        .contains("not connected"));

        let textarea_type = json!({
            "kind":"type",
            "selector":"textarea:nth-of-type(1)",
            "text":"allowed"
        });
        assert!(validate_action_target(
            textarea_type.as_object().expect("textarea object"),
            &observation,
        ).is_ok());
    }

    #[test]
    fn private_action_handles_detect_identical_shape_node_replacement() {
        let original = json!({
            "ok": true,
            "handles": [{"selector": "button:nth-of-type(1)", "handle": "token:1"}],
        });
        let replacement = json!({
            "ok": true,
            "handles": [{"selector": "button:nth-of-type(1)", "handle": "token:2"}],
        });
        let original = parse_private_action_handles(&original, 1).expect("original handle");
        let replacement =
            parse_private_action_handles(&replacement, 1).expect("replacement handle");
        assert_ne!(original, replacement);
    }

    #[test]
    fn private_bridge_uses_hidden_secret_bound_native_primitive() {
        let script = private_action_bridge_script("__bridge_deadbeef", "secret", "token");
        assert!(script.contains("WeakMap"));
        assert!(script.contains("target_identity_drift"));
        assert!(script.contains("configurable:false"));
        assert!(script.contains("supportedTextInput"));
        assert!(script.contains("readOnly"));
        assert!(script.contains("capability_not_connected"));
        let request = private_bridge_request_script(
            "__bridge_deadbeef",
            "secret",
            &json!({"kind":"act","action":"click","selector":"button","handle":"token:1"}),
        )
        .expect("bridge request");
        assert!(request.contains("__bridge_deadbeef"));
        assert!(request.contains("!==\"function\""));
        assert!(request.contains("\"action\":\"click\""));
    }

    #[test]
    fn only_initial_navigation_may_dispatch_without_an_observation() {
        let payload = json!({
            "pageGeneration": 0,
            "documentDigest": null,
        });
        assert!(
            validate_dispatch_snapshot_state(&payload, "navigate", 0, None, None, 0)
                .is_ok()
        );
        assert!(
            validate_dispatch_snapshot_state(&payload, "click", 0, None, None, 0)
                .is_err()
        );
        assert!(
            validate_dispatch_snapshot_state(&payload, "navigate", 1, None, None, 1)
                .is_err()
        );
    }
}