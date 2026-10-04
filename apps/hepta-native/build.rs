fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=packaging/windows/app.manifest");

    println!("cargo:rerun-if-env-changed=HEPTA_NATIVE_ASSET_INPUT");
    if std::env::var_os("CARGO_FEATURE_ROBRIX_PREVIEW").is_some()
        && std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("linux")
    {
        let source = std::env::var_os("HEPTA_NATIVE_ASSET_INPUT")
            .expect("robrix-preview requires the verified native asset build wrapper");
        println!(
            "cargo:rerun-if-changed={}",
            std::path::Path::new(&source).display()
        );
        let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
        std::fs::copy(source, output.join("native-assets.rs"))
            .expect("copy verified native resource bindings");
    }

    if std::env::var_os("CARGO_CFG_WINDOWS").is_some() {
        embed_manifest::embed_manifest_file("packaging/windows/app.manifest")
            .expect("embed Hepta Native Windows application manifest");
    }
}
