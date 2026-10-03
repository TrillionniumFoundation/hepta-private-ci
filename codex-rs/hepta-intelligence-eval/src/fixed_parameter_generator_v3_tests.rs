use super::*;
#[test]
fn unprotected_generator_config_is_rejected_before_role_or_key_use() {
    let path = std::env::temp_dir().join(format!("parameter-g-unprotected-{}", std::process::id()));
    std::fs::write(&path, b"{\"schema\":\"caller claimed G\"}").expect("public fixture");
    assert!(run_fixed_parameter_generator_v3(&path).is_err());
    assert_eq!(
        std::fs::read(&path).expect("unchanged"),
        b"{\"schema\":\"caller claimed G\"}"
    );
    std::fs::remove_file(path).expect("cleanup");
}
