// Explicitly require the HIA-emitted artifact, never silently fall back to Rust.
fn main() {
    println!("cargo:rerun-if-env-changed=CODEX_HIA_NATIVE_LIB_DIR");
    if std::env::var_os("CARGO_FEATURE_HIA_NATIVE").is_none() {
        return;
    }
    assert!(
        std::env::consts::OS == "linux" && std::env::consts::ARCH == "x86_64",
        "HIA native UTF-8 boundaries require Linux x86-64"
    );
    let dir = std::env::var("CODEX_HIA_NATIVE_LIB_DIR")
        .expect("HIA native build requires CODEX_HIA_NATIVE_LIB_DIR");
    let library = std::path::Path::new(&dir).join("libcodex_hia_utf8_boundaries.so");
    assert!(
        library.is_file(),
        "missing HIA library: {}",
        library.display()
    );
    println!("cargo:rustc-link-search=native={dir}");
    println!("cargo:rustc-link-lib=dylib=codex_hia_utf8_boundaries");
}
