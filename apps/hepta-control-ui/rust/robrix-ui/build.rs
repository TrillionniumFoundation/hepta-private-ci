fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    // Web and the embedded native host use their own verified packaging paths.
    if std::env::var_os("CARGO_FEATURE_UI").is_none()
        || std::env::var_os("CARGO_FEATURE_NATIVE_HOST").is_some()
        || std::env::var("CARGO_CFG_TARGET_ARCH").as_deref() == Ok("wasm32")
    {
        return;
    }
    let root = std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    for (name, length) in [
        ("NotoSansSC-Regular.otf", 8_331_336),
        ("NotoSansSC-Bold.otf", 8_543_168),
    ] {
        let path = root.join("resources/fonts").join(name);
        println!("cargo:rerun-if-changed={}", path.display());
        assert_eq!(
            std::fs::metadata(&path).map(|m| m.len()).ok(),
            Some(length),
            "Rust desktop CJK resources are missing or invalid; use python3 tools/run-desktop.py (or npm run desktop), which verifies hashes and prepares an offline-reusable staged workspace"
        );
    }
}
