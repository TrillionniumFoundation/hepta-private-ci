use super::test_codex_exec;
use pretty_assertions::assert_eq;

#[test]
fn exec_fixture_home_is_private() {
    use std::os::unix::fs::PermissionsExt;
    let test = test_codex_exec();
    assert_eq!(
        std::fs::metadata(test.home_path())
            .expect("fixture home")
            .permissions()
            .mode()
            & 0o777,
        0o700
    );
}
