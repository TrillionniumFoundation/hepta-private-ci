# Workflow Strategy

The workflows in this directory are split so that pull requests get fast, review-friendly signal while `main` still gets the full cross-platform verification pass.

## Pull Requests

- Required checks run against GitHub's synthetic merge commit, not the pull
  request head alone. This includes changes already on `main` and catches
  conflicts before they reach the branch.
- `bazel.yml` is the main pre-merge verification path for Rust code.
  It runs Bazel `test` and Bazel `clippy` on the supported Bazel targets,
  including the generated Rust test binaries needed to lint inline `#[cfg(test)]`
  code.
- `rust-ci.yml` keeps the Cargo-native PR checks intentionally small:
  - `cargo fmt --check`
  - `cargo shear`
  - `argument-comment-lint` on Linux, macOS, and Windows
  - `tools/argument-comment-lint` package tests when the lint or its workflow wiring changes

## Post-Merge On `main`

- `bazel.yml` also runs on pushes to `main`.
  This re-verifies the merged Bazel path and helps keep the BuildBuddy caches warm.
- `rust-ci-full.yml` is the full Cargo-native verification workflow.
  It keeps the heavier checks off the PR path while still validating them after merge:
  - the full Cargo `clippy` matrix
  - the full Cargo `nextest` matrix via per-platform archive-backed shards
  - Windows ARM64 nextest archives cross-compiled on Windows x64, then replayed on native Windows ARM64 shards
  - release-profile Cargo builds
  - cross-platform `argument-comment-lint`
  - Linux remote-env tests

## Rule Of Thumb

- If a build/test/clippy check can be expressed in Bazel, prefer putting the PR-time version in `bazel.yml`.
- Keep `rust-ci.yml` fast enough that it usually does not dominate PR latency.
- Reserve `rust-ci-full.yml` for heavyweight Cargo-native coverage that Bazel does not replace yet.

## Pinned Bazel and lock regeneration

`.bazelversion` selects Bazel 9.3.0 through the existing pinned Bazelisk action.
The 9.0.0 runner crashed inside `ActionInputMap.getIndex` while asynchronous
remote output upload read an input map that action postprocessing was still
mutating. The same null `paths[index]` stack occurred in the
[macOS blocking job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39371863795/job/118466002030)
and the earlier
[ARM GNU V8 job](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39352706696/job/118438289361).
An internal Bazel exit is not evidence that a Rust test failed or passed.

Upstream [Bazel change #30693](https://github.com/bazelbuild/bazel/pull/30693),
commit `6ea95086c919be3d70f7feb327dccfdcf0e17b58`, moves inputs discovered after
execution into a separate map. The
[9.3.0 source](https://github.com/bazelbuild/bazel/blob/9.3.0/src/main/java/com/google/devtools/build/lib/skyframe/ActionExecutionFunction.java)
contains that change. The stable pin retains the existing remote cache, build
event evidence, target selection, and original platform checks.

Bazel 9.3.0 uses lock format 28; 9.0.0 used 26. Regenerate the complete graph with
`just bazel-lock-update`, then run `scripts/check-module-bazel-lock.sh`. Do not
edit the format number by hand. The `Bazel stable lock proposal` workflow runs
these original commands on the exact candidate in hosted CI, retains the real
postimage and logs, and checks that a second generation is byte-identical. Its
artifact is a reviewable lock candidate; it does not replace any required
build, test, clippy, or security check.
