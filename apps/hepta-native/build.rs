fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=packaging/windows/app.manifest");

    if std::env::var_os("CARGO_CFG_WINDOWS").is_some() {
        embed_manifest::embed_manifest_file("packaging/windows/app.manifest")
            .expect("embed Hepta Native Windows application manifest");
    }
}
