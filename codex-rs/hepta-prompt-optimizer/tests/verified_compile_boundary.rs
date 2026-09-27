//! Downstream compilation checks: raw DTOs are not verified capabilities.
//!
//! A positive control is compiled first with exactly the same rustc/library
//! arguments, so a missing toolchain or broken dependency cannot masquerade as
//! a successful negative test. No generated test source is executed.

use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Output;

fn compiler_inputs() -> (PathBuf, PathBuf) {
    let executable =
        std::env::current_exe().unwrap_or_else(|error| panic!("locate test executable: {error}"));
    let directory = executable
        .parent()
        .unwrap_or_else(|| panic!("test executable has no dependency directory"))
        .to_path_buf();
    let mut libraries = std::fs::read_dir(&directory)
        .unwrap_or_else(|error| panic!("read dependency directory: {error}"))
        .map(|entry| {
            entry
                .unwrap_or_else(|error| panic!("read dependency entry: {error}"))
                .path()
        })
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.starts_with("libcodex_hepta_prompt_optimizer-") && name.ends_with(".rlib")
                })
        })
        .collect::<Vec<_>>();
    libraries.sort();
    if libraries.len() != 1 {
        panic!(
            "compile-boundary qualification requires one exact optimizer rlib, found {}: use a clean target directory",
            libraries.len()
        );
    }
    (directory, libraries.remove(0))
}

fn compile(directory: &Path, library: &Path, work: &Path, name: &str, source: &str) -> Output {
    let source_path = work.join(format!("{name}.rs"));
    std::fs::write(&source_path, source)
        .unwrap_or_else(|error| panic!("write compilation fixture: {error}"));
    let compiler = std::env::var_os("RUSTC").unwrap_or_else(|| "rustc".into());
    Command::new(compiler)
        .arg("--edition=2024")
        .arg("--crate-type=lib")
        .arg("--emit=metadata")
        .arg("--error-format=json")
        .arg("--out-dir")
        .arg(work)
        .arg("-L")
        .arg(format!("dependency={}", directory.display()))
        .arg("--extern")
        .arg(format!(
            "codex_hepta_prompt_optimizer={}",
            library.display()
        ))
        .arg(source_path)
        .output()
        .unwrap_or_else(|error| panic!("execute rustc qualification: {error}"))
}

#[test]
fn downstream_cannot_mutate_construct_or_substitute_verified_phases() {
    let (directory, library) = compiler_inputs();
    let work =
        tempfile::tempdir().unwrap_or_else(|error| panic!("create compilation directory: {error}"));
    let control = compile(
        &directory,
        &library,
        work.path(),
        "positive_control",
        r#"
        use codex_hepta_prompt_optimizer::canonical::{
            SelectedPromptPortfolioV1, RawSelectedPromptPortfolioV1,
            PricedPromptCandidatesV1, RawPricedPromptCandidatesV1,
        };
        pub fn inspect(v: &SelectedPromptPortfolioV1) -> usize { v.selected.len() }
        pub fn inspect_price(v: &PricedPromptCandidatesV1) -> usize { v.rows.len() }
        pub fn raw_inspection(v: &RawSelectedPromptPortfolioV1) -> usize { v.selected.len() }
        pub fn raw_price(v: &RawPricedPromptCandidatesV1) -> usize { v.rows.len() }
    "#,
    );
    assert!(
        control.status.success(),
        "positive compiler control failed: {}",
        String::from_utf8_lossy(&control.stderr)
    );

    let cases = [
        (
            "raw_portfolio_substitution",
            "E0308",
            r#"
            use codex_hepta_prompt_optimizer::canonical::{SelectedPromptPortfolioV1, RawSelectedPromptPortfolioV1};
            fn accepts_verified(_: &SelectedPromptPortfolioV1) {}
            pub fn bypass(raw: &RawSelectedPromptPortfolioV1) { accepts_verified(raw); }
        "#,
        ),
        (
            "raw_pricing_substitution",
            "E0308",
            r#"
            use codex_hepta_prompt_optimizer::canonical::{PricedPromptCandidatesV1, RawPricedPromptCandidatesV1};
            fn accepts_verified(_: &PricedPromptCandidatesV1) {}
            pub fn bypass(raw: &RawPricedPromptCandidatesV1) { accepts_verified(raw); }
        "#,
        ),
        (
            "portfolio_mutation",
            "E0594",
            r#"
            use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
            pub fn bypass(mut verified: SelectedPromptPortfolioV1) {
                verified.receipt.total_token_upper_bound = 0;
            }
        "#,
        ),
        (
            "pricing_mutation",
            "E0596",
            r#"
            use codex_hepta_prompt_optimizer::canonical::PricedPromptCandidatesV1;
            pub fn bypass(mut verified: PricedPromptCandidatesV1) { verified.rows.clear(); }
        "#,
        ),
        (
            "enumeration_construction",
            "E0451",
            r#"
            use codex_hepta_prompt_optimizer::canonical::{EnumeratedPromptCandidatesV1, RawEnumeratedPromptCandidatesV1};
            pub fn bypass(raw: RawEnumeratedPromptCandidatesV1) -> EnumeratedPromptCandidatesV1 {
                EnumeratedPromptCandidatesV1 { inner: raw }
            }
        "#,
        ),
        (
            "private_engine",
            "E0603",
            r#"
            pub use codex_hepta_prompt_optimizer::canonical_engine::select_portfolio_v1;
        "#,
        ),
    ];
    for (name, expected_code, source) in cases {
        let output = compile(&directory, &library, work.path(), name, source);
        let diagnostic = String::from_utf8_lossy(&output.stderr);
        assert!(
            !output.status.success(),
            "downstream bypass unexpectedly compiled: {name}"
        );
        assert!(
            diagnostic.contains(expected_code),
            "{name} failed for an unexpected reason; expected {expected_code}: {diagnostic}"
        );
    }
}
