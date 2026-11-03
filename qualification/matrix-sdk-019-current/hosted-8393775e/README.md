# Exact 8393775e qualification, including failures

Source: `8393775ed68714144d9e27449789ce42c254dc47`; workflow run `41685527480`.
The five original GitHub artifact ZIPs are retained losslessly; larger ZIPs use
the bounded parts listed in `../artifact-parts.json`. Each
download matched the service-provided size, SHA-256 digest, and ZIP CRC checks.
`VERIFIED.json` records the subsequent input, log, JUnit and committed-lock checks.
All 1,279 distinct recorded source inputs were reread from this exact Git commit.
Each mode recorded identical inputs before and after its commands.

The SQLite/Starlark, old encrypted-store migration, and live Synapse modes passed
221 + 1 + 1 original tests, with zero skips. These are this source's results,
not inherited results from the prior source or proof for a future combined graph.

The owner mode built the pinned D-Bus client and passed all 52 build/identity
commands, then failed actual Rust test compilation: SDK 0.19 removed the writable
`bundled_latest_thread_event` field used by one gap-fill test. No owner test ran.
The successor retains the original oversized auxiliary-metadata discard test
through the supported push-action API and adds an oversized raw bundled-thread
rejection test. It does not change production gap-fill code or its bounds.

Bazel passed the original committed-lock check, lock update, and lock recheck;
the generated lock exactly equals the committed lock. The actual SDK, SQLx, and
Starlark dependency build passed. Regression-test analysis then failed because
the pre-existing zstd patch did not apply to zstd-sys 2.1.2. The successor imports
the already reviewed root fix, exact blob
`0f7de3a271dfba3db8d18f57c9453be4a4334354`, rather than changing dependency policy.
No Bazel regression test passed in this run.

This remains DRAFT / HOLD_NO_GO. These scoped successes do not establish complete
platform CI, all owner tests, or paired-host admission.
