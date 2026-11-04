# Explicit Core fixture metadata capability

Status: candidate, original gates pending. Production activation is not requested.

This candidate preserves the complete model-provider-info source and its strict public OpenAI URL helper. Ordinary ModelClient and ThreadManager constructors retain no fixture lease. Only the existing hidden test-support injection can attach a private capability to a newly constructed fixture manager. There is no global registry, serialization field, environment switch, Cargo feature or alternate Bazel Core type.

The test builder captures its own built-in OpenAI provider before applying configuration mutators. A literal HTTP loopback IP, explicit nonzero nondefault port, exact /v1 path, and absence of userinfo/query/fragment are required. Provider ID and all provider fields must still match, except five explicitly enumerated transport settings: request retries, stream retries, stream idle timeout, WebSocket connect timeout, and WebSocket transport enablement. The resulting complete configuration is frozen into the private lease.

Each manager spawn overwrites the private nonpersistent attachment using that manager's lease and current full provider identity. Session passes a strong reference into its own ModelClient. Every metadata decision additionally matches the full provider snapshot and exact resolved wire URL. An unrelated client at the same port has no capability; provider or URL changes fail closed. Explicit client clones own their lease even when the TestCodex wrapper has been dropped.

The hidden bridge follows the existing core::test_support convention, which explicitly prefers one Core crate identity over a crate-feature permutation. It is trusted Rust test code, not a runtime security boundary against a caller deliberately invoking test-support APIs. No new endpoint is added to the production URL allowlist.

## Qualification

The isolated workflow first runs 13 reader controls and the original formatter. Any formatter proposal is exported as exact bytes, then the run fails before native qualification. It must be adopted as a new commit before native results can be attributed to committed source.

On Linux and Windows the original Cargo nextest inventory is compiled without filters. Native runs select 10 exact unit cases: eight new capability controls and two unchanged original wire/identity controls. The integration target selects the 21 original GNU failures supplied by the original job, the unchanged same-port third-party negative, four new real runtime lifecycle/identity tests, and two additional original recovery fixture regressions. The abort_tasks module is excluded by the original Windows cfg; that one absent case is recorded explicitly and cannot conceal a compiled case. The complete model-provider-info library also executes with no qualification filter and no ignored cases.

Each selected case must occur exactly once in a fresh original JUnit report, with zero failures, skips or retries. Unselected compiled cases and original ignored cases remain visible, and are not counted as executed. Original test budgets, 8 MiB Rust stack, default production features, zero retries, and original scoped Clippy are retained. Linux uses the existing pinned D-Bus client builder and verifies its products before and after the run.

This is not full Core acceptance, full workspace CI, macOS qualification or Bazel compilation. No dependency version, Cargo feature, Cargo.lock, MODULE.bazel.lock or BUILD definition changes are proposed. The original combined Bazel and product gates remain required when the candidate is composed.

The root-owned recovery fixture files retain their original assertions and budgets. The first provider event is held behind the existing gate, original Plan settings precede recovery, and the cold replacement uses the same provider endpoint and full configuration. Remote executor environment identity is still an actual qualification condition, not waived by these fixture changes.

The root-provided Landlock compile prerequisite changes only the renamed `no_new_privs(true)` call to the pinned 0.4.4 API `set_no_new_privs(true)`. The original true argument and strict enforcement handling are unchanged. This fixes the observed original SDK E0599 without changing dependencies or permissions.

The independent hook repair uses a dedicated configured-hook lookup in the same already filtered, ready, captured MCP calls map. Model-visible lookup, governance, active policy, timeout and stale-catalog checks are retained. Its original 14 `hooks_mcp` cases are selected unchanged, alongside all five original and three new binding controls. These extra scopes are tracked separately from metadata qualification and do not imply full Core or MCP acceptance.

The original `suite/mod.rs` also excludes the entire `hooks_mcp` module on Windows. All fourteen absent hook cases are therefore explicitly recorded as platform exclusions there; Linux must execute them. The reader rejects any platform exclusion that actually appears in the compiled inventory. The MCP binding library controls remain selected on both hosts unless an actual compilation condition proves otherwise.
