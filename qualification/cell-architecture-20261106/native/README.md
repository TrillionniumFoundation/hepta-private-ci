# Native source preparation evidence

`source-stage1.tar.gz` preserves 127 original files (3,171,678 decoded bytes) from the completed source preparation stages on the configured native `desktop` host. Its SHA-256 is `d17ea73df84263cbf9a6791001d5fb4f22f009815a0f51167c27011762e18fa8`; the compressed archive is 337,930 bytes. `source-stage1.json` is the original per-member manifest and records the native paths, lengths and SHA-256 values.

The closed records cover the exact source checkout, original evidence pack / verification / restore, byte and Git-mode comparisons, the initial full formatter failure, the separate formatter repair, normal Git publication, and the official V8 release-checksum verification. The initial formatter failure is retained with its repair. Earlier launch-preparation failures and compiler outcomes belong to separate records; this archive does not establish that Rust product tests passed.

The archive was independently read back through the configured controller and checked against its file digest and every member digest before publication. Native paths in the manifest identify the original observations; the adjacent archive is the durable copy for review. Running compiler output was excluded from this snapshot and is recorded separately after its original job reaches a terminal state.

No record grants effect, deployment, training or lifecycle authority. The production adoption and service-quality limits in [the architecture document](../ARCHITECTURE.md) still apply.
