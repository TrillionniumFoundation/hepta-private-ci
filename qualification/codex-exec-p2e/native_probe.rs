//! Test-only differential probe. Deserialization never invokes an executor.

use codex_exec_server_protocol::JSONRPCMessage;
use serde::Deserialize;
use serde_json::Value;
use serde_json::json;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    id: String,
    raw: String,
    hepta_accepts: bool,
    native_accepts: bool,
}

#[derive(Deserialize)]
struct Corpus {
    schema: u32,
    authority: String,
    cases: Vec<Case>,
}

fn inspect(raw: &str) -> Option<Value> {
    let message = serde_json::from_str::<JSONRPCMessage>(raw).ok()?;
    let JSONRPCMessage::Request(request) = message else {
        return None;
    };
    if request.method != "process/start" {
        return None;
    }
    let params = super::decode_params(request.params?).ok()?;
    Some(json!({
        "request_id": request.id,
        "process_id": params.process_id.as_str(),
        "argv": params.argv,
        "cwd": params.cwd,
        "env": params.env,
        "tty": params.tty,
        "pipe_stdin": params.pipe_stdin,
        "arg0": params.arg0,
        "env_policy": params.env_policy,
        "shell_snapshot": params.shell_snapshot,
        "sandbox": params.sandbox,
        "enforce_managed_network": params.enforce_managed_network,
        "managed_network": params.managed_network,
        "network_proxy": params.network_proxy,
    }))
}

#[test]
fn all_shared_cases_match_the_actual_native_deserializer() {
    let corpus: Corpus = serde_json::from_str(include_str!("corpus.json")).expect("corpus");
    assert_eq!(corpus.schema, 1);
    assert_eq!(corpus.authority, "DENY_ALL");
    assert_eq!(corpus.cases.len(), 50);
    for case in corpus.cases {
        let actual = inspect(&case.raw);
        assert_eq!(actual.is_some(), case.native_accepts, "{}", case.id);
        if case.hepta_accepts {
            let value = actual.as_ref().expect("Hepta subset must parse natively");
            // These are decoded defaults, NOT verified runtime isolation.
            assert_eq!(value["env"], json!({}));
            assert_eq!(value["env_policy"], Value::Null);
            assert_eq!(value["sandbox"], Value::Null);
            assert_eq!(value["enforce_managed_network"], json!(false));
        }
        println!(
            "P2E_NATIVE_ROW {}",
            json!({"id": case.id, "accepted": actual.is_some(), "projection": actual})
        );
    }
}
