use super::*;

fn args(extra: &[&str]) -> Vec<String> {
    ["--serve-ui", "--auth-keyring-account", "desktop"]
        .into_iter()
        .chain(extra.iter().copied())
        .map(str::to_owned)
        .collect()
}

#[test]
fn observer_requires_absolute_path_and_explicit_peer_identity() {
    for extra in [
        vec!["--observer-socket", "/run/hepta/observer/ctl"],
        vec!["--observer-owner-uid", "0"],
        vec!["--observer-socket", "relative", "--observer-owner-uid", "0"],
        vec![
            "--observer-socket",
            "/run/hepta/observer/ctl",
            "--observer-owner-uid",
            "wrong",
        ],
        vec![
            "--observer-socket",
            "/a",
            "--observer-socket",
            "/b",
            "--observer-owner-uid",
            "0",
        ],
    ] {
        assert!(parse(&args(&extra)).is_err());
    }
    let launch = parse(&args(&[
        "--observer-socket",
        "/run/hepta/observer/ctl",
        "--observer-owner-uid",
        "0",
    ]))
    .unwrap()
    .unwrap();
    let observer = launch.observer.unwrap();
    assert_eq!(observer.socket, PathBuf::from("/run/hepta/observer/ctl"));
    assert_eq!(observer.owner_uid, 0);
    let legacy = parse(&args(&[])).unwrap().unwrap();
    assert!(legacy.observer.is_none());
    assert!(legacy.controller.is_none());
}

#[test]
fn finite_controller_is_default_off_and_requires_explicit_fleet_source_and_identity() {
    for extra in [
        vec!["--controller-socket", "/run/hepta/controller/ctl"],
        vec!["--controller-owner-uid", "0"],
        vec![
            "--controller-socket",
            "/run/hepta/controller/ctl",
            "--controller-owner-uid",
            "0",
            "--lifecycle-auth-keyring-account",
            "desktop",
        ],
        vec![
            "--observer-socket",
            "/run/hepta/observer/ctl",
            "--observer-owner-uid",
            "0",
            "--controller-socket",
            "relative",
            "--controller-owner-uid",
            "0",
            "--lifecycle-auth-keyring-account",
            "desktop",
        ],
    ] {
        assert!(parse(&args(&extra)).is_err());
    }
    let launch = parse(&args(&[
        "--observer-socket",
        "/run/hepta/observer/ctl",
        "--observer-owner-uid",
        "0",
        "--controller-socket",
        "/run/hepta/controller/ctl",
        "--controller-owner-uid",
        "0",
        "--lifecycle-auth-keyring-account",
        "desktop.control",
    ]))
    .unwrap()
    .unwrap();
    assert!(launch.controller.is_some());
}
