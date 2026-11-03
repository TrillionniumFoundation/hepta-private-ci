# Four-consumer compatibility candidate — HOLD

This archive preserves newly executed, source-bound experiments. It is not a production migration or a claim of complete serde_yaml API compatibility. Official serde-saphyr 2.1.0 crate SHA256 is `3f4dc2714fc5632417a6e979602d7044bad8f2880c63fc7217087180acec31b6`. The existing research archive retains the original negative controls.

The final `value-compat-v2` candidate matches 1,574 scalar/typed observations and 28 concrete consumer-type examples; the expanded original harness has 14 passing tests. Its disabled compatibility profile remains byte-identical to the official matrix's 472 differences. The independent extended matrix has 13,011 observations and zero differences. Its preceding version had six explicit-empty-document differences; complete failing output is retained.

**Remaining resource failure:** the new full-profile resource test aborts with stack overflow at depth 64 in the unoptimized default Rust test thread. This has not been fixed or qualified. The filtered diagnostic run passes seven tests and fails one error-message assertion (`recursion limit exceeded` versus the test's expected substring `nesting`); it does not replace the original failed run. Official resource options are unchanged: the new parser's default depth cap is 64, versus legacy serde_yaml's recursion budget 128. No caps or thread stacks have been raised to obtain a pass.

Actual four-consumer workspace native builds and dependency/Bazel lock qualification have not run. Production acceptance remains false. The typed scalar compatibility module supports only the actual consumer scope (Any, Bool, U32, String, Option, collections); it is not a universal replacement deserializer.

`complete-source-bound-results.tar.gz` contains complete stdout/stderr, receipts with exact argv and input/source hashes, generated probe sources, and per-candidate patches against the pinned official package. No executable, rlib, target cache or full upstream tree is included. `OUTPUT_ARCHIVE_MANIFEST.json` gives all member lengths and SHA256. The partial string-option-v1 patch is retained as partial; later complete versions are distinct.
