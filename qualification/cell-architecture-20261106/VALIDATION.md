# Cell architecture validation and adoption boundary

**The frozen Rust candidate passed 990 tests, with 66 skipped by the original
runner, followed by strict Clippy.** The final formatted-source caller proof also
passed independently. These results qualify the stated code paths and source
identities; they do not enable production lifecycle authority, complete missing
workers, or establish model quality and service-cost gains.

The later `4ce8808d` GitHub architecture lanes also completed successfully:
Neuron/Automation/Runtime passed 351 tests with zero skipped on the targeted
second attempt, and Agentd passed 639 with 66 skipped on its original attempt.
Both lanes passed strict Clippy, scoped formatting and clean-source checks.
These executions provide independent confirmation of the same four packages;
their overlapping tests are not counted as additional distinct coverage.

The six requirements, existing baseline mechanisms, new implementation and
remaining integration work are mapped in [ARCHITECTURE.md](ARCHITECTURE.md).
Original failed, superseded and preparation-only executions remain separate from
the successful executions below.

## Exact product source

| Identity | Value |
| --- | --- |
| Frozen product-test commit | `87cce8066b5f41e2d462b9469a301245f43d8c23` |
| Complete product-test tree | `60604de0d6ea4805fd248574ba83fe49f16b261a` |
| Rust subtree | `3deb8503bc873331518c0c536a269c00d754a8bf` |
| Original implementation baseline | `a6f3aa12ba187448c35449c7da0a9798ae4ca987` |
| Rust toolchain | `1.96.0` |
| nextest | Official `0.9.103`, verified before dispatch |
| nextest profile and run ID | `local`; `aa0d04a1-d9a0-4d47-b71f-76a135023c16` |
| nextest binary SHA-256 | `e999c122a02c3fe74a1b66d254b6419a8a665e8bf540b1d31de7933a6d3753f1` |

The native source was clean before and after both product gates. It used a
separate target directory, two build jobs and two test threads. The repository's
original `just` recipes, `scripts/run-nextest.py`, locked dependencies and
`scripts/hepta_ci_exec.py` recorded the actual command, source, exit status,
deadline and complete output. No sandbox environment was changed to qualify the
tests. The V8 material used the repository resolver and verified official release
checksums.

The later upstream formatting merge has parents `87cce806` and `e01c860f` and
preserves the entire tested tree. The subsequent app JavaScript correction is a
separate formatter-only change with strict AST comparison. Evidence and prose
commits do not change the Rust subtree or the eight caller-audit inputs. The
tested commit and complete tree above remain the product receipt's original
identity; they are not relabeled as a later whole-repository head.

## Rust product execution

The original configured-host job was `1a1b3d38d48-fc05-84ef` on `desktop`.
Its original helper receipts and complete controller/command output are retained
in the [native evidence index](native/README.md).

```sh
just test --locked \
  -p codex-hepta-neuron \
  -p codex-hepta-automation \
  -p codex-hepta-runtime \
  -p codex-hepta-agentd \
  --retries 0

just clippy --locked \
  -p codex-hepta-neuron \
  -p codex-hepta-automation \
  -p codex-hepta-runtime \
  -p codex-hepta-agentd \
  -- -D warnings
```

| Gate | Observed result | Time and scope |
| --- | --- | --- |
| Original four-package test command | Exit 0; **990 passed, 0 failed, 66 skipped** | 1,070.945 seconds including cold compilation; original budget 4,200 seconds |
| nextest terminal summary | **990 tests run across 31 binaries**, 1 slow test | Test execution 228.914 seconds; no retry |
| Strict Clippy on the same four packages | Exit 0 | 288.667 seconds; original budget 900 seconds |
| Source identity | Clean and unchanged before/after | Commit, complete tree and Rust subtree above |

The 990 original PASS lines group as **Neuron 177, Automation 143, Runtime 31,
Agentd 639**. These are executed package totals, not counts of newly added tests.

The 66 skipped cases are retained as skipped, not counted as passes. The raw log
does not enumerate individual skip identities, so this report does not invent
their reasons. A read-only search did not obtain a usable JUnit report; failed
file-information observations remain failures and are not evidence of absence.
Twenty-nine binaries produced individual PASS lines; 31 is the
runner's binary count and is not replaced with that different observation.

The single slow test was
`actual_reconciler_asks_original_issuer_for_same_k_d_and_does_not_resend_unknown`;
it ultimately passed. The executed suites include the new representation binding,
cold recovery, generic-entry refusal, deadline/clock, queue/backpressure,
Circuit settlement-reserve and complete lifecycle-state regressions.

This is a Linux native qualification for those four packages with the original
selected configuration. It is not an all-workspace, all-feature, GPU/model-quality,
Windows Rust-product or complete SDK qualification. The separate Python SDK zstd
image prerequisite repair is not assigned product coverage from this Rust run.

## Python, caller closure and evidence checks

Native07 used the same clean published `87cce806` source. Its original sequence is
retained as **failed overall**, because the full caller proof timed out and the
initial underlying Prettier check failed. Individual passing gates remain valid
only for their own recorded scope.

| Gate | Observed outcome | Source/scope |
| --- | --- | --- |
| Actual PR `just fmt --base a6f3aa12... --check` | Passed | Published `87cce806` |
| Typed caller regressions | **56 passed** | Final formatted scanner and tests |
| Independent B4 regressions | **69 passed** | Original B4 command |
| Archive regressions | **14 passed** | Final formatted archive script/tests |
| Complete original archive verification | Passed | All 4,087 original members; pinned source and listing |
| Archive checkout-tree budgets | Passed | 157 files in the migrated evidence prefix |
| Original codespell 2.4.3 CLI | Passed | Binary parts excluded narrowly; source, prose and JSON still checked |
| Native full caller proof | **Timed out** | Original 900-second budget; 900.165 seconds, exit 124, no stdout |
| Independent local full caller proof | **Passed** | 324.424493 seconds, unchanged 900-second budget, one execution |

The successful local command was the unchanged:

```sh
python3 -B scripts/verify_hepta_callers.py verify
```

It reported **171 boundaries across 5,315 Rust files**, with
`authorityGranted=false`. Before and after execution, all **9,451 tracked Rust
subtree blobs, totaling 128,230,122 bytes**, matched their Git object identities;
all eight audit inputs also matched. The final scanner SHA-256 is
`0774d796759876fab1873a2a1dcbb4c91210533d34edbe32707fb8f52b9d569c`;
the typed regression SHA-256 is
`059d636fe604217c7c01975e50c5d8a3074445fd5bc31ef8652b09220c4dd0d5`.

The local checkout retained the original baseline HEAD and an incomplete Git
object database; no complete, clean local checkout of the published
whole-repository head is asserted. The qualification binds the complete verified
Rust subtree and relevant audit inputs, not a fictitious clean local `87cce806`
HEAD.
[The final caller manifest](audit/final-caller.json) and adjacent archive preserve
the execution receipt, exact before/after snapshots, complete Git listing and
original stdout/stderr. The native timeout is not rewritten by this pass; no
unverified CPU, I/O or contention cause is assigned to it.

## Formatting repair and existing diagnostic drift

The original full Prettier glob failed on 31 app JavaScript files. All 31 files,
the formatter configuration and lock inputs were independently verified to be
unchanged from the original baseline. The correction uses the observed pinned
Prettier 3.5.3 in a separate copy and a separate commit. All 31 formatted files
pass the formatter check and strict bundled-Babel AST comparison.

The strict comparison retains actual literal values, regular-expression
pattern/flags and `TemplateElement.value.raw`; it removes only source positions,
comments and explicit formatting metadata under `extra`. The preliminary
comparison that excluded `raw` more broadly, and the first stricter helper's
`TypeError`, are preserved separately and are not the final semantic evidence.
The complete patch has SHA-256
`cf6ccb3cd512878b4e5f91fa93f546fa77aef0374cfa574ece941941454f98cd`;
the successful strict AST result has SHA-256
`06d94fc81690d02a0dd2e803fcca211ad02061995355d8bbf6f6ffdf33b64638`.

Pinned pnpm provisioning did not succeed on the native host. The recorded check
executes the exact package-script glob using the separately verified underlying
Prettier 3.5.3 entry point. It is not reported as a successful `pnpm run format`
invocation. The completed whole-glob recheck is indexed with the native repair
and publication records.

A separate full-tree Ruff diagnostic reported three unchanged baseline files:
`scripts/hepta_ci_chef.py`, `scripts/test_hepta_ci_chef.py` and
`scripts/test_hepta_module_status_facts.py`. They were not changed to broaden this
candidate. That diagnostic failure is preserved separately from the passing
required PR-scoped formatting check.

## Platform archive results and preserved earlier failures

| Original job | Source | Actual outcome |
| --- | --- | --- |
| [Windows checkout 128184561094](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42302804112/job/128184561094) | `a6f3aa12` | Checkout failed with six long paths; product tests skipped |
| [Windows archive 128252598172](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42323275294/job/128252598172) | `b4afdbad` | Checkout, 14 archive regressions, full integrity and path/blob budgets passed |
| [Ubuntu archive 128252598512](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42323275294/job/128252598512) | `b4afdbad` | Checkout, 14 archive regressions, full integrity and path/blob budgets passed |
| [Windows archive 128279386114](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42331671872/job/128279386114) | `4ce8808d` | Checkout, 14 archive regressions, full integrity and path/blob budgets passed again |
| [Ubuntu archive 128279386486](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42331671872/job/128279386486) | `4ce8808d` | Checkout, 14 archive regressions, full integrity and path/blob budgets passed again |
| [Three-owner Rust CI 128252597941](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42323275303/job/128252597941) | `b4afdbad` | Compile exit 101: 14 ambiguous `assert_eq` diagnostics; zero product tests executed |
| [Agentd Rust CI 128252598332](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42323275303/job/128252598332) | `b4afdbad` | Compile exit 101: 18 ambiguous `assert_eq` diagnostics; zero product tests executed |
| [Three-owner preparation 128279386660](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42331671861/job/128279386660) | `4ce8808d` | `cargo metadata` exited 101 after a crates.io TLS transport failure; product test, lint and format steps skipped |
| [Agentd Rust CI 128279386888](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42331671861/job/128279386888) | `4ce8808d` | Original attempt: 639 passed, 66 skipped across 17 binaries; strict Clippy, scoped format and source checks passed |
| [Three-owner Rust retry 128286366849](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42331671861/job/128286366849) | `4ce8808d` | Second attempt: 351 passed, zero skipped across 14 binaries; strict Clippy, scoped format and source checks passed |

The macro imports were repaired before the successful `87cce806` run. The earlier
CI jobs' skipped strict-lint steps remain skipped for those jobs. Their complete
logs are retained with [Neuron CI](ci/b4-neuron.json), [Agentd CI](ci/b4-agentd.json),
[Windows archive](ci/windows-archive.json) and [Ubuntu archive](ci/b4-linux-archive.json)
receipts. [The original codespell failure](ci/codespell-b4.json) contains 354
diagnostics from compressed binary parts; only that binary path was excluded,
and the subsequent original codespell command passed.

The later [Windows](ci/4ce-windows-archive.json) and
[Ubuntu](ci/4ce-linux-archive.json) archive receipts preserve their own complete
logs. The `4ce8808d` [native preparation failure](ci/4ce-native-preparation.json)
records a `percent-encoding` sparse-index transfer failure with curl error 55 and
`SSL_ERROR_SYSCALL`. It occurred before product tests. A targeted rerun request
was rejected because another job in the same workflow was still running; that
request did not start a rerun. After the workflow completed, a second
[single-job rerun request](ci/4ce-rerun-request.json) was accepted. Its
[three-owner execution](ci/4ce-three-owner-retry.json) passed 351 tests
(Neuron 177, Automation 143, Runtime 31), with zero skipped, in 198.700 seconds
including compilation; nextest execution took 6.809 seconds. Strict Clippy took
85.673 seconds and passed. The separate original
[Agentd execution](ci/4ce-agentd.json) passed 639 tests with 66 skipped in
533.570 seconds including compilation; nextest execution took 114.052 seconds.
Its strict Clippy passed in 201.684 seconds. Both retain clean before/after
`4ce8808d` source and complete tree `0b668cec797c009c7ba710607931f011f4338e52`.
Every command used zero test retries. No dependency source, TLS verification,
test gate or test retry policy was weakened. The original preparation failure
and rejected request remain their original outcomes. This confirms these
architecture lanes; it does not claim every repository workflow or later head
is green.

The native evidence additionally preserves the initial V8 resolver input error,
first pre-compiler preparation failure, actual ambiguous-macro compilation
failure, successful compiler/formatter repair, wrong installed nextest version
before dispatch, Python launcher syntax failure before its gates, pnpm preparation
failures, the full caller timeout and formatter/AST-helper failures. Preparation
failures are not converted into product failures or passes. Separate attempts and
their original job identities, command output and source bindings remain separate.

Historical evidence migration preserves **4,087 files and 116,240,752 original
bytes** in **143 bounded payload parts** plus three compressed member manifests.
Actual restoration matched original bytes, Git blobs and modes. The longest new
archive-relative repository path is 84 UTF-16 units; each archive file is at most
480,000 bytes. See [the migration record](../cell-unification-20261106/MIGRATION.json)
and [restore instructions](../cell-unification-20261106/README.md). Historical
failure paths remain original facts even though those members now live inside
the archive.

## Final evidence and text closure

Native job `1a1b40b1a4e-fc05-85f6` checked the published evidence head
`e585b90d09a2565e04394d47e1576092b0e9be70`, complete tree
`81ff0f7e2ed7a06f677168c9cd4ccc6ec133073a`. The original codespell 2.4.3 CLI,
both evidence-prefix checkout budgets and actual `git diff --check` from
`4ce8808d` all passed. The architecture prefix contained 75 files and the
unification prefix 157 at that source. Only 28 qualification files changed;
the clean before/after source, Rust subtree and eight audit inputs were equal.

The [final text manifest](final-text/manifest.json) and
[complete closure archive](final-text/closure.tar.gz) preserve 55 original
command/controller/readback records, totaling 160,187 decoded bytes. The archive
is 33,739 bytes with SHA-256
`bea26ce5cb39f7d755a031b3af6049abe94d2f854889d67ffb73fd2ee6e5bd4f`.
The archive and every member were independently verified before publication.
This is a text and evidence check on `e585b90d`; no Rust, caller, AST or Prettier
execution is attributed to this job. Later receipt and prose publication does
not change the identity of these completed executions.

## Adoption remains separate

The candidate adds versioned representation contracts, a guarded typed execution
path, bounded queues and recovery reserves, complete state bindings and portable
evidence. Existing Circuit V2, lifecycle V1 and three-speed learning mechanisms
are explicitly identified as baseline work, not credited as new implementation.

Ordinary-daemon scheduling, actual model/GPU batch drivers, all non-global
representation workers, running-work cancellation/watchdogs, complete physical
cross-owner migration and production lifecycle admission remain unqualified.
Lifecycle V2 currently requires a quiescent snapshot with zero in-flight requests
and zero unknown effects. No external effect is rolled back as model state.

No result here establishes a general V1-to-V2 compiler, complete training and
credit-assignment services, joint backpropagation, indefinite journal rollover/GC,
or same-candidate quality/p99/throughput/RAM/VRAM/state-growth/full-cost gains.
Those require their actual owners and independent service evidence. No archived
record grants deployment, effect, training, learning-adoption or lifecycle authority.
