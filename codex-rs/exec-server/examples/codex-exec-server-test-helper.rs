//! Explicit test-fixture entry point for targets whose ctors precede Rust args initialization.
//! This target is a Cargo example and a Bazel test-only binary, never a product install bin.

#[path = "../tests/common/dispatch.rs"]
mod dispatch;

fn main() {
    // Run before starting threads, matching the original ctor's environment
    // and alias setup. Recognized server/helper roles do not return.
    let _guard = dispatch::configure_and_dispatch();
    eprintln!("unrecognized exec-server test-helper invocation");
    std::process::exit(2);
}
