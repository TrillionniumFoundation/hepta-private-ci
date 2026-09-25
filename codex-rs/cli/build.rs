fn main() {
    emit_build_identity();
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-ObjC");
    }
}

fn emit_build_identity() {
    use codex_utils_build_identity::BUILD_SOURCE_DIRTY_ENV;
    use codex_utils_build_identity::BuildIdentity;
    use codex_utils_build_identity::RELEASE_SOURCE_SHA_ENV;

    println!("cargo:rerun-if-env-changed={RELEASE_SOURCE_SHA_ENV}");
    println!("cargo:rerun-if-env-changed={BUILD_SOURCE_DIRTY_ENV}");
    let release_source_sha = std::env::var(RELEASE_SOURCE_SHA_ENV).ok();
    let source_dirty = std::env::var(BUILD_SOURCE_DIRTY_ENV).ok();
    let identity = BuildIdentity::resolve(release_source_sha.as_deref(), source_dirty.as_deref())
        .unwrap_or_else(|error| panic!("invalid Codex build identity: {error}"));
    println!(
        "cargo:rustc-env=CODEX_BUILD_SOURCE_IDENTITY={}",
        identity.summary()
    );
}
