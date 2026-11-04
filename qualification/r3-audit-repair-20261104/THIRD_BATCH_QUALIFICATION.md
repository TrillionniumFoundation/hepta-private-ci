# Third repair batch — exact-source qualification record

## Status

This follow-up is based on published commit ff72d462d74f9eb856aa9edbc368caad9c466708. Its complete original CI ended with 13 successful, 2 failed, 1 cancelled and 2 skipped workflow runs. The required blocking workflow had 24 successful, 9 failed and 4 skipped jobs. The candidate remains Draft and main qualification remains open.

The complete original 48-name ledger preserves 121 original platform associations. Its mutually exclusive current evidence tiers are 8 names with visible exact-case failure, 13 with a visible exact-case pass in some execution scope, 11 with only a noncached original-platform target pass, and 16 with no visible case output. Full original-matrix closures remain zero. Eighteen additional visible names are a lower bound: eight appear in final failed-target/final-log/full-JUnit evidence, while ten are retained as retry-stage observations.

See [the terminal snapshot](third-original-ci-terminal.json), [the complete case ledger](third-original-failure-reconciliation.json), and [the current Chinese project audit](CURRENT_AUDIT_PROGRESS.zh-CN.md).

## Source composition

| Stage | Git tree | Scope |
|---|---|---|
| Published second batch | f780fe13946102a33b329898af48810be9c7bf0c | ff72 source and qualification files; ordinary CI merge 8e20cb5ec8261053ea472f06f79a0def072f3dce has the same tree |
| Three Core repairs | eb5a108497371514f4b87f35a77fc2a0e989c459 | Exact local baseline edcc50b93a0b95342567bdfe98e5c0d96c85e52f plus four source paths |
| Historical-index repairs | 12d2a91ebe037263e9642e39e5d926f7146a3e9a | Existing qualification files materialized and seven historical indexes plus their README repaired |
| Failed-shard collector / Windows helper workflow | 2d69ec4e9118a2760c49a49c2da795d60a06a691 | Four additional source/workflow files |
| Queue causal baseline | 508ce2bf2d1b7258c0a0e9add35f2d59e5ea4a56 | Actual owned database-ack negative control; failed baseline preserved |
| Queue and Skills repairs | 869971be4145f5e4eea64cfba6e5fef9d5b037a9 | Two final fixture files |
| Intel diagnostics, PTY/Fleet and UI repairs | a69b20c4c3cfee9cf483496742d6bea1469d847a | Nine final files; independently reconstructed from f780 plus exactly 27 entries: 19 source/CI and eight historical qualification changes |

The complete original Rustfmt diff changes six test files from a69b to 06f7c229f020d2dae174f91e0ed411a08e62070c. The recovered original Ruff formatter changes four Python files to 7aa959b44ed8d2bdad2ab83fb103c40a3333cf0b. Root independently reconstructed both trees from every exact preimage and postimage. Adding the one new musl workflow yields code/CI composition tree aa1b76d8591358be2f591c8e411b9e0364a818fd: exactly 20 source/CI paths plus the eight previously reviewed historical qualification repairs relative to f780. Subsequent current-audit documents are outside that code/CI composition tree. See [the exact map](third-code-ci-source-manifest.json).

Tests below are bound to their own recorded trees. Final formatting, any permitted lint transformations, qualification-document additions and a separate new musl workflow are recorded as subsequent changes. The resulting publication commit and actual next CI checkout are recorded separately in PR #4797.

## Behavior and fixture changes

- Core tools: inspect the full ordered durable history and actual bounded internal attempted-call observations while retaining namespace dispatch, replay, truncation and backslash oracles. Nonofficial wire metadata remains unchanged.
- Core turn state: use the existing thread-settings submission helper with its default override. Preserve the three requests, one handshake, original turn-state sequence and original deadline.
- Suspension/resume: keep the exact original environment identity, manager and rollout history when constructing the fresh resumed manager. Linux observations and original Wine-exec qualification remain separate.
- Queue: register the notification before observing durable queue state and wait for the actual acknowledgement within the original shared 25-second tail budget. The added owned-binding negative control gates the real database completion operation; it does not assert that the external unbound enqueue path takes that same production branch.
- Executor Skills: align the existing canonical workspace with the fixture's automatic environment cwd. Preserve the original permitted-reference, listing, rejection and symlink contracts.
- PTY readiness: send one initial split-marker execution probe and at most one replacement after the first observed prompt. Input echo alone cannot satisfy readiness. The existing negative control deliberately flushes the queued probe before starting the real Python REPL, exercising the replacement path.
- PTY drain: record two bounded phases in the test-owned progress file around the original 4 MiB write. Preserve the original 2-second exit wait and 10-second child alarm. The Intel cause remains open.
- Fleet: refresh through one ordinary supervisor tick after the existing direct health/ingress checks, requiring all six process identities to remain equal. The tick exposes the latest available cached probe result; it does not guarantee a new network response after those direct checks.
- Forward, Supervisord and infer-worker: add stage attribution to the original errors and deadlines. Preserve RPC counts, expected rejections, join races, authority and physical-send assertions. Supervisord retains at most 65,536 raw log bytes and separately caps the fully escaped UTF-8 body to 65,536 bytes; its owned append stream can include both daemon generations.

## CI and evidence changes

The failed-target collector retains existing logs and XML from the selected failed targets, including available shards and attempts, while explicitly recording missing files or collection errors. It preserves the original Bazel exit status and original retry policy. Full GitHub job-log transport did not recover the test stdout suppressed by the old 1 MiB renderer cap; real collected artifacts must be checked on the next CI run.

The Windows exec-authorized-read workflow builds both original setup and command-runner binaries in the same isolated Cargo target directory before running the unchanged scopes. The old source and merge artifacts each show server 253 PASS / 1 FAIL before the capability oracle because setup was missing. This preparation change still needs original Windows execution.

The UI workflow fetches only the two immutable source/base histories after a shallow checkout, verifies unchanged clean HEAD/tree, and constructs the original two-parent merge. The token is confined to the one authenticated fetch subprocess. Its thirteen build commands retain their original bytes and ordering; four steps expose elapsed time without increasing the original 60-minute job budget. Seven real Git fixture cases cover source and merge ancestry, excluded unrelated history/blob data, fetch failure, wrong source and unexpected authenticated origin.

The seven historical helper JSON records are explicit indexes referencing their unchanged original bytes at ff72. Current path validation uses the indexes, while historical command, lock and generator records remain available at pinned objects. Neither the document checker nor the original execution receipts was rewritten.

The new hepta-musl-product-smoke workflow (blob 6aad46b1fe0edcf315ef8b1a5546225c59efe235) builds the existing explicit x64 musl Hepta binary with the original Bazel wrapper and lockfile mode. Cquery must establish the same explicit musl target platform for the outer platform_data wrapper and inner binary, and select the actual executable from DefaultInfo. It validates static ELF properties and runs those exact hashed bytes once for --version and --help. It records source/raw-parent identities, actual executable paths, cache/BEP projections and source/binary stability. Original required budgets and tests remain unchanged. The separate new job's 120-minute/110-minute build-step limits apply only to its new scope. PyYAML and all four complete inline Python blocks pass syntax checks; no hosted build/process execution is claimed here. This is narrow x64 static-CLI process scope, not full musl behavior, ARM, Alpine, sandbox or normal Root product acceptance. See [scope](MUSL_PRODUCT_SMOKE_SCOPE_ZH.md) and [independent review](third-musl-workflow-independent-review.json).

## Actual native execution

| Phase | Actual result | Exact scope |
|---|---|---|
| Core baseline | namespaced FAIL; turn-state TIMEOUT at the original 60 seconds; Linux suspension PASS | edcc; original failures preserved |
| Core repaired | 3/3 PASS, zero retries | eb5a, Linux x86_64 |
| Queue acknowledgement causal baseline | one intended FAIL at the actual early-empty oracle | 508c; real owned database gate |
| Queue repaired | 4/4 PASS, zero retries | 8699; original external queue case 50.681 s overall |
| Executor Skills | 5/5 PASS, zero retries | 8699; complete original Linux roster, macOS remains a separate gate |
| Existing docs checker | PASS_HEPTA_DEVELOPMENT_DOCS_V8 | Historical evidence was indexed, not re-executed |
| Failed-log collector | 13/13 PASS | Nine existing tests retained with four added filesystem/log controls |
| Final isolated UI Git controls | 7/7 PASS | Final source files; actual local Git operations |
| Complete UI Python discover | 13/13 PASS, zero retries, 47.297 s | a69b; seven Git controls plus six unchanged Gateway tests |
| Supervisord actual Rust body-cap proof | both inputs PASS | 65,536 invalid UTF-8/control bytes expand to 196,610/327,682 bytes; final body 65,536 each |

On a69b, the five exact Rust phases executed eight selected cases, all PASS with zero retries: PTY 3 (0.075 / 0.136 / 0.367 s), Fleet 2 (11.856 / 12.176 s), forward 1 (20.094 s), Supervisord 1 (31.033 s), and worker 1 (1.869 s). Every phase has fresh exact-roster JUnit and unchanged source/test-harness digests.

The original nextest summaries also retain 62 cases outside the selected roster as skipped: PTY 25, Supervisord 1 and worker 36. Selected-roster skipped is zero; whole-package skipped is not zero. Successful captured stdout was not displayed by the original nextest settings, so no unobserved final health transition or daemon phase log is inferred.

The six unchanged Gateway Python tests use their authored Git HEAD graph lookup at 907d4f512819a71bece82e7f89944e9406466e36. The receipt identifies this limit explicitly; the current working-tree UI source checks and actual next GitHub source/merge job are separately recorded.

The controller's actual exit code is 1 and its original success=false is preserved. The initial three-package source-bound build produced Agentd hash 9b0a8828…, while the later package-scoped nextest catalog recompiled Agentd from the same a69b worktree; terminal hash is d24b62d5…. The following original just test log contains no additional Compiling line. Codex and Linux sandbox retain their initial hashes, and all five actual test harnesses remain hash-stable across execution.

The initial-all-fixtures equality field therefore remains false from Fleet onward. External fixture hashes were not independently sampled between catalog compilation and just test. Current-source rebuild provenance is supported by the retained source, compilation and catalog chain, with this missing sampling point explicit. The original controller result is not rewritten into a global qualification pass. Forward dispatches its own current executable; worker uses the unchanged codex and Linux sandbox binaries. See [the complete eight-case evidence](third-intel-ui-complete-native.json) and [independent Fleet review](third-fleet-and-report-independent-review.json).

## Windows scoped closures and remaining boundary

B12 satisfies its original private-state exit conditions at ff72: two positives, the two real negatives with one intended failure and one passing control each, actual filesystem observations and clean source restoration.

B14 satisfies its original thirteen-case Windows resume scope at both source head and base merge: 13/13 each, zero retries. Rollout is 121/121 in each lane. Root independently unpacked and verified both original artifact ZIPs and complete JUnit sets. The distinct server helper failure remains open until its next original run succeeds.

Three strict Windows token/legacy DELETE tests still fail. The normalized effective/inherit-only ACE recognition gap establishes the idempotence cause. The exact outside-delete authorization mechanism remains unresolved; the design preserves original rights and loader/IPC controls. See [the reviewed design](WINDOWS_BOUNDARY_REPAIR_DESIGN.md). Production boundary changes have not been applied. Prior assistant and audit records report an automatic approval rejection; its original tool receipt, decision identifier and stated reason were not recovered. That limitation is retained explicitly.

Windows CodeMode remains unresolved where final shard output was capped. Retained 532 executed passes retain their seven original skips. Target-level helper, TUI, Queue and lifecycle successes remain at the level evidenced by their actual outputs.

## Final hygiene and qualification

The original scoped just fix command ran for seven affected crates with --locked --offline, exited 0 in 442.883 seconds and changed no source. The first just fmt actually exited 1 because uv was absent from the task PATH; its completed Rust formatting and complete failed-controller receipt are retained. A real existing uv 0.11.3 binary was then reused without modifying its owner directory. The original frozen formatter used Ruff 0.15.13 and exited 0 in 5.895 seconds. All four changed Python ASTs remain equal; the entire Rust subtree remains 818ce45f8d9a96b01b86c61df9a09ab74341cbd6. Root independently reviewed and reconstructed all ten formatting postimages. git diff --check passed. No Rust or unit tests were rerun after fix/fmt. See [initial attempt](third-hygiene-first-attempt.json), [recovery](third-fmt-recovery-native.json) and [root review](third-hygiene-root-review.json).

The new workflow also passed syntax-only YAML/four-inline-Python checks, without Bazel or workflow execution. Final assembly adds the reviewed workflow and qualification files, then repeats the original just fmt, original development documentation verifier and exact whole-tree/source guards before publication. The resulting terminal receipt and final publication identity are recorded in the PR, separately from this frozen preassembly record. Failure of any required final check prevents publication of a claimed passing result.

The PR remains Draft. Original Windows, macOS ARM/Intel, Wine, UI and whole-candidate checks must be judged from their actual new source/merge executions. Normal product entry, operator acceptance, external Bao/Chain/HIA acceptance and the scientific adoption HOLD remain independent gates. The canonical architecture and ownership documents are unchanged by this audit report.

## Evidence navigation

The accompanying evidence index lists every added record with Git blob identity and scope. Large original logs retain immutable source URLs, original byte lengths and hashes; they are not inserted as oversized product blobs. The complete original native files remain preserved in the recorded evidence directory. [Project direction](PROJECT_DIRECTION_AND_PLAN.zh-CN.md) and the current blocker ledger provide the subsequent execution order.
