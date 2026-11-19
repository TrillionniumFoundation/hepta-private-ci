# Cargo and Bazel dependency aliases

The seven-path repair has passed its scoped qualification. Canonical Cargo and Bazel lock operations, cargo-shear, configured provider and action queries, and both actual Bazel build targets completed successfully. Final `just fmt` made no source changes. The original failed attempts and the build timeout remain in the evidence archive.

Source commit: `6e1e9f7c19aa3423b1b0e99928b949ac75d4bd23`

Source tree: `fe5311b358c01f6253953808c2d266347fd539ea`

Parent: `b33751526c9c9c6158bafd3641c603c646b7da4a`

## Source scope

| Path | Change |
| --- | --- |
| `bazel/rules/cargo_crate_aliases.bzl` | Select Cargo renames from the same normal, development, build and platform dependency buckets as the consuming Rust target. |
| `bazel/rules/BUILD.bazel` | Export the new helper. |
| `defs.bzl` | Use the selected aliases for workspace libraries, binaries, tests and build scripts, including existing workspace test variants. |
| `codex-rs/Cargo.toml` | Remove the unused workspace-inherited stable-hash declaration; preserve the package member and direct path consumers. |
| `codex-rs/core/Cargo.toml` | Place `time` in development dependencies, where the original model-cache tests use it. |
| `codex-rs/hepta-matrix-sdk/Cargo.toml` | Remove the unused development dependency on wiremock. |
| `codex-rs/Cargo.lock` | Remove only the Matrix SDK to wiremock dependency edge. |

This batch changes no Rust implementation or test body. The independent c2d drafts and other agents' subsequent source changes are excluded. No lint, advisory, caller, blob-size or CI policy is relaxed.

## Why the alias change is required

The original Bazel rule retained only aliases named `serde_yaml`. The OTel crate uses reqwest 0.12.28 as `reqwest` and reqwest 0.13.5 as `reqwest_otel`. Removing the latter alias made both dependencies appear under the reqwest name and left `reqwest_otel` unresolved. The original SDK job `135764648393`, run `44581734289`, at commit `2e3040eedebce38b99fff1268b73dc69fd9ad058` reports E0464, E0432 and E0433 in those source files. The relevant original OTel and manifest paths are byte-identical at the repair's b337 parent; this binding is recorded separately from the new validation.

The new helper intersects the generated alias map with the dependency buckets selected by each rule. It preserves complete target-triple selects and applies the same workspace test replacement labels as the corresponding dependency helper. This prevents aliases from introducing dependencies belonging to an unrelated dependency kind or platform.

Binary unit tests explicitly add development aliases only. The inspected rules_rust implementation copies the compiled binary's normal aliases and dependencies before adding the test's explicit attributes. The configured provider proof confirms this inheritance for `hepta-infer-control` and its unit-test binary.

## Dependency graph and analysis results

The canonical Cargo workspace lock update exited zero. All 1,540 package identities, versions, sources and checksum values are unchanged. The only package-record change is removal of the Matrix SDK to wiremock dependency edge. The wiremock package remains available to its other consumers.

Native `just bazel-lock-update` and `just bazel-lock-check` both exited zero. `MODULE.bazel.lock` is unchanged; its SHA256 is `5336311a0fa5c53fd5b3f5ef966d661afed27453a69d84ff3dd55dbc431ff501`. The new Cargo lock SHA256 is `8f311b15cf68d471b7e3635dcf7ad0ce42bdcf44372ac8698c1aede59dc97de4`.

The verified cargo-shear 1.11.2 executable ran `cargo shear --locked` and exited zero. Its private offline cache contains lock-checksummed copies of the required archives. The tool's 21 existing warnings remain in the raw log; no ignore metadata was added.

The configured query covers five target labels: OTel library, OTel library unit tests, OTel integration tests, the infer-control binary, and its binary unit tests. Both configured query and Rust action query exited zero. Each of the three OTel actions has exactly one `reqwest` external dependency for 0.12.28 and one `reqwest_otel` external dependency for 0.13.5.

The expanded platform conditions contain ten complete triples, differentiated by CPU, operating system, libc or Windows ABI. They are mutually exclusive, and the alias helper uses the same conditions as the generated dependency selection. This is graph evidence; it does not claim execution on every listed platform.

## Actual build and final source binding

The actual native build covered:

```
//codex-rs/otel:otel
//codex-rs/hepta-infer-core:hepta-infer-control-bin-unit-tests-bin
```

The first build job, `1a1f53f9317-ffbe-12bb`, reached its original 3,600-second process limit while compiling LLVM and Clang. Its authoritative state is `timed_out`, process exit code 124, with complete durable output. This is retained as a failed attempt. The interrupted Bazel process did not publish a successful command result.

The single continuation job, `1a1f579392a-ffbe-135e`, reused the same isolated source and warm cache and built only those same two unfinished targets. It completed successfully: authoritative process state `succeeded`, exit code zero, complete durable logs, and no truncation. Bazel reports 12,488 of 12,488 actions complete and elapsed time 1,640.423 seconds. The source used the repository-pinned Bazel 9.3.0 and Rust 1.96.0 configuration, `--config=ci`, and `--lockfile_mode=error`.

The continuation used four jobs within the unchanged 400-percent CPU quota and 20-GiB memory limit. Its process limit was 7,200 seconds. No successful query or lock check was repeated. The binary unit-test target was compiled; this build command did not execute its test cases.

Post-build verification confirmed all seven native source postimages. Final `just fmt` then exited zero and changed no source bytes. The committed seven postimages therefore match the successful build exactly. Staged whitespace checking and the original 512,000-byte blob policy passed.

The previous 27-path time-repair manifest has one superseded entry: `codex-rs/Cargo.lock`. Its other 26 paths were verified unchanged in both the native build source and the final local source. The replacement lock preserves all package identities and removes only the unrelated Matrix SDK development edge. `source-postimages.json` records this transfer explicitly.

## Preserved earlier failures

The archive retains both initial cargo-shear offline-cache misses, the sparse third-party source omissions, the demonstrated `/tmp` disk-quota failure, and the inspection-wrapper errors. Missing source files were materialized from their exact baseline Git blobs. JVM temporary storage moved to the owned shared-memory directory after a real write probe failed in `/tmp`.

One configured-query wrapper expected five rows although the query legitimately returned a sixth execution-configuration row. A later wrapper completed both configured query and action query before an unconfigured `query` rejected the misplaced `--jobs` option. Only that platform query was corrected and rerun. Successful graph analysis is recorded separately from those wrapper exits.

The first local blob-policy invocation found the original allowlist absent from the sparse checkout. Its full traceback is retained. Materializing the exact committed allowlist bytes resolved that setup error; the policy file and size limit were not changed.

## Evidence and scope

`evidence-index.json` lists every archived member and its byte count and SHA256. The original compressed archive is split into exact decoded chunks of at most 400,000 bytes. Each chunk is independently wrapped in gzip with a zero timestamp; stored parts are at most 400,143 bytes. Verify the stored part hashes, decompress each part separately, verify its decoded byte count and hash, then concatenate the decoded chunks in the listed order. Verify the resulting original archive hash before extracting it. The original archive SHA256 remains `2302474a2c848d56e70a7722be5bcdedd58c94a2c93c0341c5c835d316e4120a`, and all 154 archived members retain their original bytes.

`validation-summary.json` describes the scoped results, and `source-postimages.json` binds the exact source commit. This evidence establishes the dependency and alias repair described above. It does not establish that unrelated repository CI checks or the main-branch merge gates have completed. No remote ref is updated by these source and evidence commits.

## Packaging follow-up

The full original Codespell matcher rejected raw part 004 with exit code 65 after its binary heuristic interpreted a compressed-data fragment as text. The initial text-only QA scan had not covered that case. This follow-up wraps each original chunk in a complete gzip stream; it changes neither source nor archive content and adds no exclusion or dictionary entry. The original failing command, stdout and stderr are retained as separately compressed files listed in the index. Reconstruction must decompress each part before concatenation; concatenating the stored wrappers directly does not recover the original archive.
