# Original FinalUse issuer transport: local validation

Implementation commits: `6934408f898f411290be2932e8c2923dfaef9504` and
`2ef1e31b06f60cc74899befffaa3b80927d9349e`, stacked on the unchanged Notes
recovery source `0adaca4375fdfefe0fbae7f1cb7f25c437360c6e`.

The [final-byte manifest](final-bytes-execution-manifest.json) binds the final
provider source, original contracts source, harness inputs and toolchain before
and after execution. The actual [seven tests](issuer-final-bytes-tests.json)
and [Clippy](issuer-final-bytes-clippy.json) passed on those unchanged final
bytes with Rust 1.95.0. The tests use real private Unix sockets and the original
FinalUse signature/replay verifier; no skips or weakened timeouts were used.

This remains an isolated harness. Its [retained lock](isolated-harness-lock.json)
contains the exact TOML bytes and digest as JSON data; 32 registry entries
differ from the original workspace lock. These results do not establish an
original Agentd package build or execute the Tokio worker cancellation test.
The owning-package and reverse-consumer CI gates must pass before merge.

The implementation supplies an injected transport. It does not provision a
production issuer, clock, frontier, keyring, fresh authenticated revocation
head, recovered writer or current-cut authority. The I/O deadline excludes
blocking-pool queue time; AuthBus Objective signing remains a separate owner.
