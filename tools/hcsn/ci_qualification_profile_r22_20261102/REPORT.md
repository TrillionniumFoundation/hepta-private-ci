# Test-only Bazel dependency profile candidate

At source `94252595fa741ed331b9946d7a910b28c96e44cf`,
`DurableLedger::append_qualification` exists. It is intentionally available only
with the learning-ledger feature `qualification-legacy-write`; the production
raw append method is crate-private. The reported E0599 is therefore consistent
with the test linking the ordinary ledger variant, rather than a stale API call
or an unimplemented method.

Agentd's Cargo dev-dependency explicitly enables that feature. Its Bazel build
already maps the ledger to the test-only qualification variant for unit tests,
but the generated integration-test rules bypass that replacement helper. They
also link the ordinary Agentd host library. The root macro is `defs.bzl`.

The candidate adds an explicit integration dependency replacement parameter and
a private test-only host-library variant with matching replacements. All three
generated integration-test shapes use that graph. Agentd opts in through its
existing test dependency closure. Existing production library and binary rule
calls are unchanged; no qualification feature is enabled on a product target,
no Rust API is modified, and no stub is added. The candidate files are separate
copies under `candidate/`; nothing has been applied to the repository paths.

`baseline/` contains exact fetched originals. Twelve primary source files are
preserved in verified `SOURCE_EVIDENCE.json.gz`. The patch passes `git apply
--check`, AST syntax/model checks, production-call invariance and isolated
default/mapped library/binary-only profile checks. These are static checks;
Bazel, buildifier and Rust tools were unavailable locally. They do not establish
Starlark analysis, complete transitive crate identity, compilation or execution.

The required hosted Ubuntu check is:

```bash
bazel test //codex-rs/hepta-agentd:hepta-agentd-plasticity_process_e2e-test --compilation_mode=fastbuild --@rules_rust//rust/settings:extra_rustc_flag=-Cdebug-assertions=no --@rules_rust//rust/settings:extra_exec_rustc_flag=-Cdebug-assertions=no
```

Also rerun the existing release build sweep and inspect the qualification
target's transitive Rust identities. The same workspace crate must not cross a
typed boundary in both ordinary and qualification variants. The existing unit
replacement map is reused, but its sufficiency for every integration fixture
remains a hosted-analysis obligation. Production build actions should continue
to omit the legacy-write feature. No repaired CI or green build is claimed.
