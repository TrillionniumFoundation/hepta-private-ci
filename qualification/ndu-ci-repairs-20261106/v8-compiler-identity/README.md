# V8 staged smoke compiler identity

The original PR #5040 GNU ARM64 sandbox job 127936579270 installed Rust 1.95 source successfully and completed three Bazel builds, then failed the Cargo smoke with six E0514 errors. Dependencies used rustc 1.95.0, while the V8 build script selected 1.91.0. The complete original decoded log is preserved in gzip form.

The current workspace requests Rust 1.96.0. The upstream rusty_v8 v150.4.0 toolchain file requests 1.91.0. Pinning only the Cargo executable does not pin the compiler selected in another working directory. Official Rustup documentation places RUSTUP_TOOLCHAIN before toolchain files.

This candidate reuses the executable ten-line change from PR #4705, with two comments corrected for this source. Only the existing native staged Cargo smoke gets RUSTUP_TOOLCHAIN=1.95.0. After entering codex-rs, both Cargo and rustc must report exactly the already-installed 1.95.0 release. The original smoke commands, features, archives and every other workflow step are preserved. The Windows upstream source builder intentionally keeps its original 1.91.0 selection.

Twelve shell checks execute the actual candidate smoke body against controlled compiler and Cargo stubs, including both original feature variants and rejection of either mismatched version, a missing step pin, a failing compiler probe and a failing smoke. This checks invocation and failure propagation; it is not native compilation. A fresh complete V8 matrix and the original Cargo tests remain required on the integrated source.
