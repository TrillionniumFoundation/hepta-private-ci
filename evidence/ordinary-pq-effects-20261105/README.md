# Ordinary PQ effects: implementation and native evidence

Date: 2026-11-05. PR: [#4877](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4877).

The reachable ordinary HTTP/PoN effect loader now requires PQ contract and FinalUse authority. The four selected verification scopes passed **170 tests**, including 19 new PQ controls. The separately selected real ordinary PQ → Chain test **failed** on both original attempts because the 49,508-byte packet exceeds the unchanged 24,576-byte ordinary limit. **That full-path qualification is BLOCKED; whole-chain PQ qualification remains HOLD.** This directory does not certify production provisioning, independent trust custody, Chain task authority, network confidentiality, physical-state rollback or quantum PoN work security.

## Source identities

| Role | Immutable identity |
| --- | --- |
| Fixed Hepta base | `1556a4df6e279055fd8196f81a4ca2fe0f19384a` |
| X230 tested Hepta source | `b0b7d95105bb4c63b422c3097e159caa6c65fe00`, tree `89fc387e70e2a0f96edf0a6a0e096b54fe9d8a9d` |
| ROG tested Hepta source / code freeze | `ee57cd57c322a8fecdf674a662c741452baf6478`, tree `ec40412aff2091fd05e0feaf31a46179f8afaa46` |
| Hepta Cargo.lock SHA256 at both tested sources | `0f458d7746a0ca0b95bedc5404fd3347c1b0a7508f1c387f3b1f3f71ced08663` |
| Actual native Chain input source | `04be5f02c84cf5cb626a53f34bc03a5bd6ff5137`, tree `d4f4a85c439982d8decec9265c1993408f3577cf` |
| Actual Chain Cargo.lock SHA256 | `00f3573879f3da7d5a702a8bc13245196bbfd53b86b0b6eb19c51f14887cef61` |
| Broader Chain source audit candidate | `7ae0d1b227853fc75e02334b497f69dd52d50235`, compared with `a16a89f92a0db5ff6af9c1d7790f201841f079aa` |

The two Chain identities have different purposes. The native continuation uses the existing CI source pair at `04be5f02`; it assigns no execution credit to the separate `7ae0d1b2` audit candidate or to a prospective merge lane.

The [changed-source manifest](CHANGED-SOURCE-MANIFEST.json) records all 20 changed code/workflow files, their Git blobs and byte hashes at the code freeze. Every local source file used to prepare this evidence matched its GitHub blob. The [successor proof](SOURCE-SUCCESSOR-BOUNDARY.json) independently compares complete Git trees from `b0b7` to `ee57`: only three Agentd test files change, adding the required invalid runtime input to one rejection fixture and removing two undeclared assertion-formatting imports. Both tested package subtrees, Cargo manifests/lockfile, Rust toolchain selection, justfile, formatting script, nextest script/configuration and all production code remain identical. The 131 X230 passes retain their actual `b0b7` test identity; they are not relabeled as execution of the complete successor tree.

Evidence files are committed after the frozen code. Adding this directory does not create a new native test result.

## Actual scoped results

| Command scope | Native source / host | Result | Primary evidence |
| --- | --- | --- | --- |
| `just test --locked -p codex-model-provider` | `b0b7`, X230 | **89 run / 89 passed / 0 skipped**; six new PQ cases passed | [Receipt](native/x230/b0b7-model-provider-first-test-receipt.json), [terminal](native/x230/b0b7-model-provider-first-test-terminal.json), [complete log](native/x230/b0b7-model-provider-first-test-stderr.log), [original JUnit](native/x230/b0b7-model-provider-first-test-discovered-junit-1.xml) |
| `just test --locked -p codex-hepta-automation --test authorized_effect` | `b0b7`, X230 | **42 run / 42 passed / 0 skipped**; six new PQ cases passed | [Receipt](native/x230/b0b7-automation-authorized-effect-first-test-receipt.json), [terminal](native/x230/b0b7-automation-authorized-effect-first-test-terminal.json), [complete log](native/x230/b0b7-automation-authorized-effect-first-test-stderr.log), [original JUnit](native/x230/b0b7-automation-authorized-effect-first-test-junit.xml) |
| `just test --locked -p codex-hepta-agentd --lib -E 'test(automation_effect_host::)'` | `ee57`, ROG | **38 run / 38 passed / 222 skipped**; seven new PQ cases passed | [Receipt](native/rog/agentd-effects-ee57cd57.receipt.json), [terminal](native/rog/agentd-ee57cd57-terminal.json), [complete log](native/rog/agentd-effects-ee57cd57.log) |
| `just test --locked -p codex-hepta-agentd --test neural_cognitive_bootstrap -E 'test(ordinary_native_composition_rejects_untrusted_qualification_before_inference_owners)'` | `ee57`, ROG | **1 run / 1 passed / 2 skipped** | [Receipt](native/rog/agentd-negative-qualification-ee57cd57.receipt.json), [terminal](native/rog/agentd-negative-ee57cd57-terminal.json), [complete log](native/rog/agentd-negative-qualification-ee57cd57.log) |
| Explicit real ordinary PQ → Chain continuation | `ee57` + actual `04be` Node | **1 run / 0 passed / 1 failed / 259 skipped**; original retry also failed; **BLOCKED** at 49,508 > 24,576 bytes | [Receipt](native/rog/agentd-real-chain-ee57cd57.receipt.json), [terminal](native/rog/agentd-real-chain-ee57cd57-terminal.json), [complete log](native/rog/agentd-real-chain-ee57cd57.log), [source size proof](TRANSPORT-BLOCKER.md) |

Across all five commands, 171 distinct selected test cases executed: **170 passed and one failed**. The failed case had two attempts under the unchanged nextest retry setting; it is one failed test, not two. The first four commands completed 170 passing tests. The 222 and 2 skipped cases reflect each command's selector/ignored scope and receive no pass credit. The real Chain case is ignored by the 38-test command and must be explicitly selected. No complete Agentd library, entire workspace, ARM, Windows, macOS, GitHub merge lane or neural model campaign pass is claimed by these commands.

All 19 newly added contract, durable automation and ordinary-owner controls passed. The real Chain continuation is a separate twentieth new case and failed before constructing the ordinary PQ host. Original assertions in existing tests remain in place.

### What the new tests establish

The contract tests use real ML-DSA-65 signatures and reject altered contract ID/digest/epoch/signature, mismatched key identity/algorithm, V1 or foreign signing domains and post-signing HTTP endpoint/header/timeout changes. A verified classical contract cannot claim PQ authentication.

The durable automation cases use the original SQLite/outbox owner. They check one dispatch and spent-nonce persistence after reopen, actual classical-wire rejection before consumption, revoked/spent/old-epoch denial, stale-owner refusal after retained frontier progress, refusal of a restored old local authority image against the retained external frontier, and unknown outcomes restricted to reconciliation.

The seven ordinary Agentd cases cover a real wiremock HTTP dispatch and exact receipt identity; valid legacy V1/V3 and missing/classical-profile refusal; invalid, expired and stale signed feeds; grant lifetime bounded by feed lifetime; authenticated head change before driver entry; missing frontier before/after owner opening; and a PoN configuration binding an inert real ELF and namespace marker. The inert ELF case performs no Chain business execution.

The head-change case constructs the original store driver directly. It does not independently schedule that race inside ordinary `execute`, and it is not a dedicated mutation test deleting only the second worker check. Production lease typing and both actual checks are verified by source review. These coverage limits are retained in the [claim boundary](SCOPE-AND-CLAIM-BOUNDARY.md).

Cold startup still needs live clock/frontier services. The executed HTTP readback test first reopens successfully and then removes clock/frontier availability before reading an exact existing terminal result. Its HTTP provider remains observable, and the total observed request count stays one; no provider-outage execution is credited. The real-Chain provider-unavailability assertion was never reached. They confer no new authorization during an outage.

## Actual real-Chain blocker

The explicitly selected ignored case ran at frozen Hepta `ee57` against the freshly built and verified original `04be` Node. The authoritative job `1a1ac341327-fc05-52dc` exited **100**, without timeout or cancellation. Nextest recorded **1 run / 0 passed / 1 failed / 259 skipped** in 1.235 seconds. Both original attempts reported exactly:

```text
Error: real Chain packet is 49508 bytes, beyond ordinary Agentd's 24576-byte limit
```

The first `legacy-v2` iteration completed actual Node `status` and `make`, then stopped at the preserved budget assertion. It did not construct `PqFixture` or the ordinary PQ host, call ordinary `execute`, consume a grant, or emit `PON_ORDINARY_PQ_PAIR`; the receipt's observation list is empty. `authenticated-v1` was not reached. This is an observed failed test and an unavailable full-path qualification, not an end-to-end rejection/dispatch success.

The [fixed-source proof](TRANSPORT-BLOCKER.md) establishes why the observed packet is already minimal: header 318 + transaction-count 2 + fixed proof 49,188 = **49,508 bytes, with zero transactions**. Both the base and code-freeze protocol constants remain 24,576 bytes for decoded effect wire and 65,536 bytes for a control frame. The RPC's hexadecimal packet alone is **99,016 bytes**, exceeding the control frame before the authorization envelope; it also exceeds the hex parser's 49,152-character bound. The lower-level adapter's 1-MiB allowance does not override the ordinary host or RPC.

The required new CI step and original test remain unchanged. The PR therefore remains **Draft with a known failing native qualification gate**. Passing the existing lower-level adapter tests cannot qualify this ordinary composition. No budget increase, compression, payload truncation, alternate work profile or assertion relaxation is included. A future repair requires a separately reviewed, versioned large-payload interface or coordinated protocol/capacity change that preserves complete-payload authorization and durable recovery identity. It cannot be credited to the unchanged original packet/24-KiB path.

## Build and harness conditions

The Hepta commands used Rust/Cargo 1.96.0, the repository's original `just test` wrapper and `local` nextest profile, and the normal local Cargo test build profile. `CARGO_BUILD_JOBS=2` limited build resource use. No source/test assertion, retry setting, timeout, workload, packet limit or sandbox flag was relaxed. No dependency or lockfile was changed.

X230 used just 1.51.0 and nextest 0.9.151. ROG used just 1.58.0 and the original native-pair CI's nextest 0.9.103. These harness versions are recorded, not treated as interchangeable report producers. The shared nextest configuration SHA256 is `3ec2f9a8ed35c5582fe5d59b4ad427e5e87249c5e7d84cf149dd9874c1f9d222`.

The original default timeout remains 30 seconds per slow interval with termination after two intervals, and the original retry count remains one. In the actual [0.9.103 retry/timeout implementation](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/config/core/imp.rs), unset custom values fall back to the default profile. Its warning about the newer `inherits` key does not remove those defaults. No retry/failure was present in the four completed test scopes' logs.

ROG's original 0.9.103 configuration produced no JUnit file: the exact workspace and independent-target locations were inspected and are retained in [the path inspection](native/rog/agentd-ee57cd57-junit-path-review.stdout.log). The [version's JUnit path implementation](https://github.com/nextest-rs/nextest/blob/d2e7b879fb79975e8b47a8e3ce569b651e6381c0/nextest-runner/src/config/elements/junit.rs) selects an unset custom profile path without falling back to the default path. The complete nextest log, command receipt and authoritative process terminal are the evidence for these ROG runs. No XML was fabricated and no test was rerun to generate it.

X230's JUnit files were written under the worktree's `codex-rs/target/nextest/local/` despite a separate Cargo target. They were located, checked against the command interval and copied before the next command overwrote that path. The initial model-provider receipt's null JUnit field is preserved; the [separate discovery record](native/x230/b0b7-model-provider-junit-locate.json) and original XML resolve it without rewriting that receipt.

The Agentd formatter and scoped `just fix --locked -p codex-hepta-agentd --lib` both exited 0 at `ee57`, with zero patch and clean source before the first effects test. Native lint still emitted warnings, including six `expect_used` occurrences in new test fixtures; exit 0 is not a warning-free claim. No tests were repeated solely because formatting/lint was run. Later source corrections were published before the first applicable test execution.

Local native checks use the lower-level original `just` commands. They do not claim execution of the whole `hepta_ci_exec.py` source/checkout gate: the independent worktrees used authorized sparse materialization, while that CI wrapper separately requires the complete checkout. The added CI step, its prospective-merge matrix and other repository workflows retain their own pending/running/failed status until they produce actual results.

### Broader GitHub CI status

The [updated workflow snapshot](CI-SNAPSHOT.json) and [failure review](CI-FAILURES.md) retain two broader completed failures at `ee57`: each five-package gate ran 1,972 cases with 1,967 passes, four failures, one timeout and 30 skipped. The public-initial pass count includes one flaky case. Three Agentd failures report a signed Evidence checkpoint/frontier mismatch, an inference-host environment test rejects Python loader overrides, and the fleet test hits the unchanged approximately 60-second watchdog on both attempts. Public-initial material reconstruction additionally reports `public plan bytes differ`.

These overlapping CI counts are separate from the five local commands above and are not summed. The continued CI step's superficial `success` label does not override its actual exit 100 and failed required-outcome gate. No base reproduction was performed, so no claim is made that these failures predate or result from this PQ change. Source/pair/merge CI remains unqualified.

### Native executable identities

| Artifact | SHA256 | Bytes |
| --- | --- | ---: |
| Fresh model-provider test ELF | `fdc493b6fc9acf89f15d2b3689b100c16bd0e509d01847bc52be4702d4853cd5` | 418,620,176 |
| Fresh authorized_effect test ELF | `0fc92d02e31d64d0d8e7ede50d0a45f237bb1bcd570f69ad486048ea10321ba8` | 267,799,416 |
| Fresh Agentd library test ELF | `c2d19ddbea51e84257a2db6968f3d541ac858955a05d026762b716293907ed92` | 1,284,198,808 |
| Fresh qualification-rejection test ELF | `1e8e50d862920ba5de1a8dc6d914cf5bc7df7762daa9c5dccad62c968afa7d96` | 830,743,216 |
| Actual fixed Chain release Node | `095458755051afd137478145a42b5edb94ee32587837e4723931317900a955d9` | 14,519,384 |

The large test ELF files and complete per-file source manifests remain in their recorded isolated native targets/validation directories. Their original paths, file identities, modification times, hashes and freshness checks are in the receipts; their binary bodies are not committed here.

After all three ROG native jobs had reached authoritative terminal states, only this task's regenerable `debug/incremental` cache was removed under a nonblocking exclusive Cargo lock to relieve disk pressure. The actual test executables in `debug/deps` were retained with identical inode, size and SHA256; source HEAD/tree/lock remained unchanged. No test was rerun. The exact path, guards and free-space observations are retained in the [cleanup receipt](native/rog/rog-own-incremental-cleanup-ee57.native.json) and [terminal](native/rog/rog-own-incremental-cleanup-ee57-terminal.json).

## Actual Chain input build

The ai395 build used a new source checkout, Cargo home and target, with no prior target reused. It checked the exact source/tree/lock tuple and all 51 entries in the existing V10 source manifest before and after execution, with clean source. Original `bash scripts/project-preflight.sh --audit` passed. Rust 1.95.0 was installed separately without changing the default toolchain. The actual command was:

```sh
cargo +1.95.0 build --locked --release \
  --manifest-path trillionnium/Cargo.toml \
  -p trnm-pon-node --bin trnm-pon-node
```

The Node-only release build exited 0 in 55.59 seconds after locked metadata/dependency preparation. It used eight build jobs and nice 10 as scheduling limits, retaining the original release profile. It did not build the separate signed-task example because the new ordinary case does not call that example. [Build binding](native/chain-input-04be/node-build-binding.json), [build log](native/chain-input-04be/node-release-build.stderr), [preflight](native/chain-input-04be/preflight-before-build.stdout), [rustc version](native/chain-input-04be/rustc-195.stdout) and [Cargo version](native/chain-input-04be/cargo-195.stdout) are retained.

The original typed transfer encountered RPC timeouts. Its unfinished staging upload was explicitly aborted after an independent transfer through existing verified SSH aliases had succeeded. The actual Node arrived with mode 0555, link count 1 and the exact SHA256 above; its ELF interpreter and dynamic dependencies were verified. The original transfer job's later unflagged `--help` check exited 1 with `EXPLICIT_DEVELOPMENT_REQUIRED`; that record is retained, and the separate artifact validation exited 0. The formal test continued to use the original `--development` command arguments. [Transfer history](native/chain-input-04be/TRANSFER-HISTORY.json), [original transfer terminal](native/rog/main-cli-chain-transfer-terminal.json), [validation](native/chain-input-04be/node-cli-validation.json) and [staging abort](native/chain-input-04be/typed-upload-abort.json) keep these outcomes separate.

The exact source-pair/environment meaning is unchanged: `HEPTA_PON_CHAIN_SOURCE` is the 40-character commit ID, not a source-directory path; `HEPTA_PON_CHAIN_BINARY` is the actual Node path; `HEPTA_PON_CHAIN_SHA256` is its verified digest. A `public_v3_from_zero` executable from an old CI artifact was inspected and rejected as an unrelated input, rather than substituted for the Node.

## Unsuccessful attempts retained

Setup and compilation failures are not counted as test failures or passes. See [attempt records](native/attempts/).

| Attempt | Observed outcome and resolution |
| --- | --- |
| `1f26` scoped native lint, X230 and ROG | Exit 101 because sparse checkout omitted tracked `docs/modules/MODULES.json` required at compile time. Materialized the tracked directory; no source substitute and no tests claimed. |
| `369` model-provider/automation lint | Exit 0 with two automatic Copy-related fixture edits. Published those exact edits before testing; did not test a dirty uncommitted tree. |
| `369` Agentd lint | Exit 101: existing native comparison fixture omitted required `runtime_snapshot`. Added operator-pinned snapshot input and the complete existing source-pin set. No successful neural campaign is inferred. |
| `9ce` format check / guarded X230 runner | Format check exit 1 on two assertion wraps; guard refused to start tests. Published exact native formatting as `b0b7`. |
| `b0b7` Agentd lint | Exit 101: a second existing rejection fixture omitted `runtime_snapshot`. Added explicit invalid bytes while preserving qualification/no-side-effect assertions. Its actual one-case execution later passed. |
| `5957` Agentd lint | Exit 101: two new tests imported undeclared `pretty_assertions`. Removed only those imports, using existing standard equality macros and preserving all comparisons. No dependency/lockfile change. |

Runtime control requests occasionally timed out while native processes continued. Authoritative terminal records, not the RPC timeout, determine each command's completion. Unknown launches were not restarted under new identities; running Rust processes were not killed by PID.

## Further review

- [Observed real-Chain failure and exact protocol size boundary](TRANSPORT-BLOCKER.md)
- [Configuration migration and separate neural fixture correction](CONFIGURATION-MIGRATION.md)
- [Seven-object whole-chain boundary and concrete remaining Browser/network paths](SCOPE-AND-CLAIM-BOUNDARY.md)
- [CI entrypoint scan, exact source-pair wiring and new ordinary Chain continuation](CI-ENTRYPOINT-REVIEW.md)
- [Additional observed GitHub CI failures and original outcomes](CI-FAILURES.md)

No production authority, release root, external clock/frontier registration, installed model, node listener, account migration or consensus rule was activated by this change.
