#[cfg(not(all(target_os = "linux", target_env = "musl")))]
use std::env;
use std::path::PathBuf;

use codex_test_binary_support::TestBinaryDispatchGuard;
use ctor::ctor;

mod dispatch;
pub(crate) mod exec_server;
#[cfg(all(target_os = "linux", target_env = "musl"))]
mod explicit_helper;

pub(crate) const DELAYED_OUTPUT_AFTER_EXIT_PARENT_ARG: &str =
    dispatch::DELAYED_OUTPUT_AFTER_EXIT_PARENT_ARG;
pub(crate) const SYSTEM_PROXY_REQUEST_URL_ENV: &str = dispatch::SYSTEM_PROXY_REQUEST_URL_ENV;
pub(crate) const SYSTEM_PROXY_URL_ENV: &str = dispatch::SYSTEM_PROXY_URL_ENV;

// Preserve the original test-process alias setup. GNU can also dispatch helper
// re-execs here because glibc initializes Rust's argument storage before ctors.
#[ctor]
pub static TEST_BINARY_DISPATCH_GUARD: Option<TestBinaryDispatchGuard> =
    dispatch::configure_and_dispatch();

#[cfg(all(target_os = "linux", target_env = "musl"))]
pub(crate) fn current_test_binary_helper_paths() -> anyhow::Result<(PathBuf, Option<PathBuf>)> {
    // musl runs ctors before Rust initializes std::env::args. Re-exec the
    // explicit fixture main so every original helper sees initialized args.
    explicit_helper::paths()
}

#[cfg(not(all(target_os = "linux", target_env = "musl")))]
pub(crate) fn current_test_binary_helper_paths() -> anyhow::Result<(PathBuf, Option<PathBuf>)> {
    let current_exe = env::current_exe()?;
    let codex_linux_sandbox_exe = if cfg!(target_os = "linux") {
        TEST_BINARY_DISPATCH_GUARD
            .as_ref()
            .and_then(|guard| guard.paths().codex_linux_sandbox_exe.clone())
            .or_else(|| Some(current_exe.clone()))
    } else {
        None
    };
    Ok((current_exe, codex_linux_sandbox_exe))
}
