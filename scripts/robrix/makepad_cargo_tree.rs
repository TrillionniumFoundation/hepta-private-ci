// Tool-only adapter: preserve diagnostics while parsing stdout alone.
fn hepta_tree_stdout(stdout: String, stderr: String, success: bool) -> Result<String, String> {
    if !stderr.is_empty() { eprint!("{stderr}"); }
    if !success { return Err("cargo tree failed; see preserved stderr".into()); }
    if stdout.trim().is_empty() { return Err("cargo tree returned empty stdout".into()); }
    for line in stdout.lines() {
        if hepta_dependency_heading(line) { continue; }
        let row = line.trim_start_matches(|c: char| c.is_whitespace() || matches!(c, '│' | '├' | '└' | '─'));
        let mut tokens = row.split_whitespace();
        let name = tokens.next().unwrap_or("");
        let version = tokens.next().unwrap_or("");
        if name.is_empty() || name.len() > 128 || !name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-' || c == b'_')
            || !version.strip_prefix('v').is_some_and(|v| v.as_bytes().first().is_some_and(u8::is_ascii_digit)) {
            return Err(format!("malformed cargo tree stdout row (first 160 chars): {:?}", row.chars().take(160).collect::<String>()));
        }
    }
    Ok(stdout)
}

fn hepta_cargo_tree(cwd: &std::path::Path, build_crate: &str, target: &str) -> Result<String, String> {
    let toolchain = format!("+{}", std::env::var("MAKEPAD_WASM_TOOLCHAIN").expect("pinned Cargo tree toolchain"));
    let (stdout, stderr, success) = shell_env_cap_split(
        &[], cwd, "cargo", &[&toolchain, "tree", "--locked", "--offline", "--color", "never", "-p", build_crate, target]);
    hepta_tree_stdout(stdout, stderr, success)
}
