# Cloud-cache Chrono retirement on the joint candidate

This is a narrow dependency migration on joint base `7fc46c193a9ff8726e43fca2982d9b8f455e3dac`. The actual execution source is `616dccdbf8d68192aa984b676608a01d1a75e168`, tree `3fc080258ea689675dedb0e6267b0157b400b11c`. Later evidence commits do not replace that execution identity.

## Actual result

The original `just test --locked --offline -p codex-utils-time -p codex-cloud-config --retries 0 --test-threads 2 --no-tests fail --success-output final --failure-output final` completed on Mac with 45 distinct passing cases: all 35 cloud-config cases and all 10 codec cases. There were no skipped, failed or errored cases, and no retries. The child returned 0 through `subprocess.Popen.wait`; runtime job `1a1f043ffc2-ffbe-75a` independently completed with exit 0, durable complete output, no cancellation and no timeout.

[Original JUnit](retained/original-junit.xml), [case index](retained/CASES.json), [native result](retained/NATIVE_RESULT.json) and [complete readout](retained/READOUT.json) are retained unchanged. The JUnit UUID is `0fecdf54-ae91-46b5-a46f-ba7db6cbef67`; its SHA-256 is `fcc6f1eaaadcdd6f5cc8ddf8d458b0bc9ea1553f4056e443657347c6247fc7a5`. The command wall time, including compilation, was 151.839976833 seconds; this is not a performance qualification.

The seven original cache tests preserve identity, expiration, tamper, version, malformed-input and missing-input controls. The added signed-cache regression checks historical timestamp/HMAC bytes. The complete cloud service suite also ran. The codec tests cover retained old-parser/serializer vectors, negative epochs, precision and explicit leap-second values. Their imported fixtures and code provenance are in [ORIGIN.json](ORIGIN.json). No previous ROG test count is inherited.

## Source and locks

All 11,826 materialized tracked inputs were verified against their Git blobs. The canonical source inventory SHA-256 before and after the native command was identical:

`feca10b13c29d43784be042198fdc54aeb8fc5597c77707967f8948a608de0c7`

The complete inventory is inside the originals archive. [The source-freeze receipt](retained/SOURCE_FREEZE.json) binds the source and locks.

- Cargo lock: `eb050f4f0df4ca93175bcd5b3f361797aadcea116d55fedf41e3c4aa8bfdf187`.
- Bazel lock: `d240b972292c4101a01eceb1281dd15cdc43c77979711281bcaa5d0c680580c1`.
- Original `just bazel-lock-update` and `just bazel-lock-check` both actually returned 0. The regenerated Bazel lock remained byte-identical.
- Scoped `just fix -p codex-utils-time -p codex-cloud-config --locked --offline` and repository `just fmt` returned 0 before the source was frozen.
- The native target was an independent APFS clone of this task's completed target. All 78,861 regular files had distinct inodes and one hard link. The original target was not shared for writes.

## Preserved failures

The archive includes the unsuccessful preparation attempts, their real command outputs and their runtime exits.

| Attempt | Actual outcome |
| --- | --- |
| prepare-1 | Formatter exited 1 because the sparse checkout omitted tools/buildifier; no native cases ran. |
| prepare-2 | Mac Git rejected the unsupported sparse-checkout add --no-cone combination with exit 129. |
| prepare-3 | All-target offline Cargo metadata exited 101 because android_system_properties 0.1.6 was not cached. |
| prepare-4 | Explicit aarch64-apple-darwin metadata completed with exit 0; this does not qualify all platforms. |
| chrono-graph-1 | System Python lacked tomllib; the original scanner failure is retained. |
| chrono-graph-2 | The unchanged scanner ran under the installed compatible Python; its require-zero command actually exited 2. |

These failures are not replaced by the later successful steps.

## Remaining Chrono boundary

The unchanged #6624 scanners were rerun on the actual joint lock. They found 1,524 packages, 194 source-less candidate roots and 121 Chrono-reachable roots. Direct workspace roots decreased from 28 to 27; indirect-only roots increased from 93 to 94. The only retired direct edge is cloud-config. Its shortest remaining path is cloud-config → agent-identity → Chrono 0.4.45. The whole graph still has 35 direct edges into Chrono across local, registry and vendored packages.

[The exact graph result](retained/CHRONO_GRAPH.json) retains `require_zero_actual_exit: 2`. This step does not claim full Cargo-deny success, whole-workspace Chrono retirement, Windows qualification or all-platform metadata success. No advisory ignore or rejection boundary was relaxed.

## Complete originals

[CHRONO_CACHE_ORIGINALS.tar.xz](retained/CHRONO_CACHE_ORIGINALS.tar.xz) retains 214 original files, including every preparation stage, both locks, complete metadata, source inventory, original native outputs/JUnit and the nine runtime job receipts. Compiled targets and caches are outside this archive.

- Archive size: 2268320 bytes.
- Archive SHA-256: `1d46b479efdee5de223cb0d29047f2cb27b9715604a06d7a30d4a65c759f7eb1`.
- [INDEX.json](retained/INDEX.json) SHA-256: `e8b3739cd1eb54942204641bfd487c12bc012503a2d9c44aae48cebfd04da1bb`.

Every archive member was reread and matched against the index. The repository size-policy exception permits only these exact archive bytes at this exact path; the global 512000-byte limit and all other paths remain unchanged.

## Repository policy verification

The [first evidence commit receipt](policy/first-evidence-head/RESULT.json) binds commit `38f44145d80fff6dc3eb62ad475f820cc010827e`. The original seven size-policy tests passed, and the actual `7fc46c193a9ff8726e43fca2982d9b8f455e3dac` to evidence-head changed-blob check passed with the unchanged global 512000-byte limit. Original stdout/stderr and runtime exits are preserved beside the receipt. This metadata addition receives a separate actual final-head changed-blob check before publication; native tests are not repeated for evidence-only changes.
