fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    // Only this controlled regression fixture omits DWARF. Deployment still
    // hashes every byte of its actual linked executable through the original
    // release owner; product binaries and the build profile are unchanged.
    let argument = match std::env::var("CARGO_CFG_TARGET_OS").as_deref() {
        Ok("linux") => Some("-Wl,--strip-debug"),
        Ok("macos") => Some("-Wl,-S"),
        _ => None,
    };
    if let Some(argument) = argument {
        println!("cargo:rustc-link-arg-bin=hepta-supervisor-pair-test-fixture={argument}");
    }
}
