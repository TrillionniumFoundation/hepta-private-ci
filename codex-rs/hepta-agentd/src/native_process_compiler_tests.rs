use super::*;

use pretty_assertions::assert_eq;

fn policy() -> NativeProcessPolicy {
    NativeProcessPolicy {
        host: "configured-worker".to_owned(),
        cwd: "/srv/assigned-workspace".to_owned(),
        executables: BTreeSet::from(["/usr/bin/python3".to_owned(), "/usr/bin/git".to_owned()]),
        env: BTreeMap::from([("LANG".to_owned(), "C.UTF-8".to_owned())]),
        timeout_seconds: 20,
        nice: Some(5),
        cpu_quota_percent: Some(100),
        memory_max_bytes: Some(256 * 1024 * 1024),
    }
}

fn proposal(arguments: Value) -> anyhow::Result<ToolCall> {
    Ok(ToolCall {
        call_id: "model-call".to_owned(),
        name: TOOL_NAME.to_owned(),
        arguments: serde_json::to_vec(&arguments)?,
    })
}

#[test]
fn exact_model_arguments_preserve_every_original_host_field_without_minting_a_key() -> anyhow::Result<()> {
    let compiler = NativeProcessToolCompiler::new(policy()).expect("policy");
    let params = compiler.compile(&proposal(json!({
        "executable": "/usr/bin/python3",
        "args": ["-c", "import sys; print(sys.stdin.read())", "literal $() ; `text`"],
        "stdin": "original bytes\n中文"
    }))?).expect("compile proposal");
    assert_eq!(serde_json::to_value(params).expect("parameters"), json!({
        "host": "configured-worker",
        "executable": "/usr/bin/python3",
        "args": ["-c", "import sys; print(sys.stdin.read())", "literal $() ; `text`"],
        "cwd": "/srv/assigned-workspace",
        "env": {"LANG":"C.UTF-8"},
        "stdin": "original bytes\n中文",
        "timeout_seconds": 20,
        "idempotency_key": null,
        "nice": 5,
        "cpu_quota_percent": 100,
        "memory_max_bytes": 256 * 1024 * 1024
    }));
    Ok(())
}

#[test]
fn model_cannot_replace_host_scope_policy_or_original_operation_identity() -> anyhow::Result<()> {
    let compiler = NativeProcessToolCompiler::new(policy()).expect("policy");
    for (name, value) in [
        ("host", json!("another-worker")),
        ("cwd", json!("/another-workspace")),
        ("env", json!({"PATH":"/untrusted"})),
        ("timeout_seconds", json!(86_400)),
        ("idempotency_key", json!("reused-operation")),
        ("cpu_quota_percent", json!(1000)),
    ] {
        let mut arguments = json!({"executable":"/usr/bin/git","args":["status"],"stdin":null});
        arguments[name] = value;
        assert!(compiler.compile(&proposal(arguments)?).is_err(), "accepted replacement of {name}");
    }
    assert!(compiler.compile(&proposal(json!({"executable":"/bin/sh","args":["-c","true"],"stdin":null}))?).is_err());
    assert!(compiler.compile(&ToolCall { name: "pty_start".to_owned(), ..proposal(json!({"executable":"/usr/bin/git","args":[],"stdin":null}))? }).is_err());
    Ok(())
}

#[test]
fn byte_limits_apply_after_json_decoding_and_to_the_complete_owner_payload() -> anyhow::Result<()> {
    let compiler = NativeProcessToolCompiler::new(policy()).expect("policy");
    for (args, stdin) in [
        (vec!["中".repeat(MAX_ARGUMENT_BYTES / 3 + 1)], None),
        (vec!["status".to_owned()], Some("中".repeat(MAX_STDIN_BYTES / 3 + 1))),
        (vec!["bad\0argument".to_owned()], None),
    ] {
        assert!(compiler.compile(&proposal(json!({"executable":"/usr/bin/git","args":args,"stdin":stdin}))?).is_err());
    }
    let mut configured = policy();
    configured.env.insert("LARGE_OWNER_VALUE".to_owned(), "x".repeat(MAX_COMPILED_BYTES));
    let compiler = NativeProcessToolCompiler::new(configured).expect("host policy");
    assert!(compiler.compile(&proposal(json!({"executable":"/usr/bin/git","args":["status"],"stdin":null}))?).is_err());
    Ok(())
}
