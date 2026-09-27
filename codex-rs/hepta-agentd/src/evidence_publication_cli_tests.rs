use super::*;

fn args() -> Vec<OsString> {
    ["--evidence-mode=production", "--evidence-publication-request-file", "/owner/request.json",
        "--evidence-production-config-file", "/owner/production.json",
        "--evidence-trust-file", "/owner/issuer.json",
        "--evidence-frontier-signer-trust-file", "/external/signers.json"]
        .into_iter().map(OsString::from).collect()
}

#[test]
fn publication_cli_parses_all_four_distinct_production_roles() {
    assert_eq!(parse_publication_files(&args()).unwrap(), Some(PublicationFiles {
        request: PathBuf::from("/owner/request.json"),
        descriptor: PathBuf::from("/owner/production.json"),
        issuer: PathBuf::from("/owner/issuer.json"),
        signers: PathBuf::from("/external/signers.json"),
    }));
}

#[test]
fn ordinary_daemon_arguments_are_not_intercepted() {
    assert_eq!(parse_publication_files(&[OsString::from("--evidence-mode=development")]).unwrap(), None);
}

#[test]
fn publication_cli_rejects_downgrade_missing_and_duplicate_roles() {
    for index in [0, 3, 5, 7] {
        let mut altered = args();
        altered[index] = OsString::from("--evidence-mode=development");
        assert!(parse_publication_files(&altered).is_err());
    }
    let mut duplicate = args();
    duplicate[7] = OsString::from("--evidence-trust-file");
    assert!(parse_publication_files(&duplicate).is_err());
    let mut missing = args();
    missing.pop();
    assert!(parse_publication_files(&missing).is_err());
}

#[test]
fn publication_cli_rejects_relative_paths_and_role_aliasing() {
    for index in [2, 4, 6, 8] {
        let mut relative = args();
        relative[index] = OsString::from("relative.json");
        assert!(parse_publication_files(&relative).is_err());
    }
    let mut alias = args();
    alias[8] = alias[6].clone();
    assert!(parse_publication_files(&alias).is_err());
}

#[test]
fn publication_cli_does_not_accept_other_runtime_effect_flags() {
    let mut altered = args();
    altered[7] = OsString::from("--automation-effect-host-file");
    assert!(parse_publication_files(&altered).is_err());
}

#[test]
fn actual_async_command_entry_is_linked() {
    let _ = run_if_requested;
}
