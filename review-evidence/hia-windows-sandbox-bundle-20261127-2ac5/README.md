# Original Windows sandbox consumers: executable sibling bundle

The original 60bb run 46051634787 / job 140684128523 failed. Its complete raw job log, original ZIP, per-member CRC and SHA256 readback, and the bounded execution-log diagnostic are retained here. No original failure is replaced by a source review or formatting result.

The exec-server cases reached the real sandbox setup and then failed at CreateProcessWithLogonW with error 2. The product resolves the command runner from trusted executable sibling layouts; it does not resolve it from CARGO_BIN_EXE or PATH. Its explicit non-null application name also does not receive PATH lookup. The original launcher only supplied helper runfiles through the environment. This mismatch is the source defect addressed by this candidate.

The CLI target separately reported a missing declared runner before a test method started. Its original execution graph contains the exact runner and setup artifacts, but that metadata does not prove the file existed when the launcher checked it. The original observation is retained without inventing a more specific cause.

The two unsharded sandbox targets now receive separate physical output directories containing their original test executable and every declared Cargo executable, including the runner and setup helper. The existing pinned bazel_skylib copy rule creates real copies, with symlinks disabled. These files are explicit top-level test outputs. The wrapper preserves the original RunEnvironmentInfo, cwd, arguments and test timeout. Production helper search and all original Rust assertions are unchanged. The original sharded core launcher is unchanged.

The shared Windows resolver freezes resolved paths as absolute paths before consumers change directory and includes the missing path in its refusal message. The workflow differs only by allowing this unique candidate branch; its three complete targets, 60-minute limit, uncached tests, no-FLAKY/no-retry checks and clean-worktree gate remain exact.

Actual just fmt succeeded. The original Windows three-target qualification is pending; no Windows or whole-matrix PASS is claimed by this commit. The copied test layout does not grant runtime authority or relax filesystem permissions.

Primary API reference: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-createprocesswithlogonw
Pinned existing copy rule: https://github.com/bazelbuild/bazel-skylib/blob/1.9.0/rules/copy_file.bzl
