// Link HIA-emitted ELF only when explicitly selected. No silent Rust fallback.
fn main() {
    println!("cargo:rerun-if-env-changed=CODEX_HIA_NATIVE_LIB_DIR");
    if std::env::var_os("CARGO_FEATURE_HIA_NATIVE").is_none() {
        return;
    }
    if std::env::consts::OS != "linux" || std::env::consts::ARCH != "x86_64" {
        panic!("HIA native patch matching requires Linux x86-64");
    }
    let dir = match std::env::var("CODEX_HIA_NATIVE_LIB_DIR") {
        Ok(dir) => dir,
        Err(_) => panic!("HIA native build requires CODEX_HIA_NATIVE_LIB_DIR"),
    };
    let library = std::path::Path::new(&dir).join("libcodex_hia_seek_sequence.so");
    assert!(library.is_file(), "missing HIA library: {}", library.display());
    println!("cargo:rustc-link-search=native={dir}");
    println!("cargo:rustc-link-lib=dylib=codex_hia_seek_sequence");
}
