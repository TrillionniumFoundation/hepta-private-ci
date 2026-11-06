# V8 Rust source component setup

This replays the exact eight-line workflow change from PR #4401, commit `60924e75305083f730deef6af386bd5e0ec569f0`. The complete preimage and postimage match that donor.

The four original Linux jobs in run `42226629678` built their Bazel V8 archive targets, then failed in the Cargo smoke step. Two Rust shim processes downloaded the same `rust-src` component concurrently; a shared partial-file rename failed with ENOENT. The original decoded logs are preserved losslessly as gzip files. Their actual merge commit `3ef779adacbfa71a62cfa9cc592270de895e7b56` has the exact source tree of PR #5025.

The existing pinned action installs Rust 1.95.0 with the minimal profile. One sequential, failure-propagating component installation now completes before parallel Cargo begins. The existing toolchain version and action pin, twelve archive matrix entries, two Windows source entries, smoke commands, permissions, artifact uploads, and policy checks retain their original bytes. The current workspace's Rust 1.96 file is also unchanged.

Local validation compared complete YAML objects after removing only the new step and exercised the exact shell body with successful and failing rustup stubs. These checks do not install Rust or execute native compilation. The final integrated head still requires actual V8 builds and Cargo smoke results. Earlier failures and unrelated platform gates remain independently recorded.
