#[test] fn real_cargo_invocation_keeps_warnings_out_of_parser_and_retains_dependency_rows() {
    let cwd = std::env::current_dir().unwrap();
    let target = "--target=wasm32-unknown-unknown";
    let stdout = hepta_cargo_tree(&cwd, "robrix", target).unwrap();
    assert!(stdout.starts_with("robrix v1.0.0-beta.1 "));
    assert!(stdout.contains("[build-dependencies]"));
    assert!(stdout.contains("[dev-dependencies]"));
    assert!(stdout.contains("(*)"));
    assert!(stdout.contains("makepad-platform v2.0.0 (https://github.com/makepad/makepad?rev=493d23a7630f487d29912dd73f2cbb5b639b74ca#493d23a7)"));
    assert!(!stdout.contains("warning:"));
    for line in stdout.lines().skip(1) {
        if hepta_dependency_heading(line) { assert_eq!(extract_dependency_paths(line), None); }
        else { assert!(extract_dependency_paths(line).is_some()); }
    }
    // The real upstream helper, process and actual application graph produce this warning.
    let (out, err, ok) = shell_env_cap_split(&[], &cwd, "cargo", &["+nightly-2026-10-01", "tree", "--locked", "--offline", "--color", "never", "-p", "robrix", target]);
    assert!(ok); assert!(err.contains("warning: skipping duplicate package"));
    assert_eq!(hepta_tree_stdout(out.clone(), err.clone(), ok).unwrap(), out);
    // The former concatenation is rejected, not normalized or silently skipped.
    assert!(hepta_tree_stdout(format!("{out}{err}"), String::new(), true).is_err());
    assert!(hepta_cargo_tree(&cwd, "hepta-does-not-exist", target).is_err());
    assert!(hepta_tree_stdout(String::new(), String::new(), true).is_err());
    assert!(hepta_tree_stdout("valid-name not-a-version".into(), String::new(), true).is_err());
}
