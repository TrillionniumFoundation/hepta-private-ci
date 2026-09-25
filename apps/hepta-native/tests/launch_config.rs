mod common;
use common::private_tempdir;
use hepta_native::launch_config::expand_launch_arguments;
#[test]
fn file_configuration_freezes_explicit_options_and_rejects_unknown_fields() {
    let root = private_tempdir();
    let path = root.path().join("launch.json");
    let mut value = serde_json::json!({"endpoint_manifest":root.path().join("endpoint.json"),"trusted_keys":root.path().join("keys.json"),"state_dir":root.path().join("state"),"allow_clipboard":false});
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    let args = vec!["--config".into(), path.to_str().unwrap().into()];
    let expanded = expand_launch_arguments(&args).unwrap();
    assert!(expanded.iter().any(|v| v == "--state-dir"));
    assert!(!expanded.iter().any(|v| v == "--allow-clipboard"));
    value["allow_clipboard"] = true.into();
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(
        expand_launch_arguments(&args)
            .unwrap()
            .contains(&"--allow-clipboard".into())
    );
    assert!(!expanded.contains(&"--allow-clipboard".into()));
    value["unreviewed_fallback"] = true.into();
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(expand_launch_arguments(&args).is_err());
}
#[test]
fn config_and_inline_policy_cannot_be_ambiguously_combined() {
    assert!(
        expand_launch_arguments(&["--config".into(), "/a".into(), "--allow-clipboard".into()])
            .is_err()
    );
}
